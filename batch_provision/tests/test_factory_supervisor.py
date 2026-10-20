"""Supervisor glue that needs no game: thread safety of registering a freshly logged-in alt."""
import logging
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from factory import db
from factory.schedule import PullPolicy
from factory.supervisor import AltWin, Supervisor
from provisioner.config import Account


def settings(db_path):
    return SimpleNamespace(
        factory=SimpleNamespace(db_path=db_path),
        login=SimpleNamespace(accounts=(Account('mw09', 'x'),), slots=(1,), launch_interval=0.0,
                              min_free_memory_mb=0),
        policy=PullPolicy(), coast_max_wait=90.0, well_max_wait=90.0, parallel_logins=2, idle_close=60.0,
        not_served=frozenset())


class KnownTest(unittest.TestCase):
    def test_roles_of_other_accounts_are_ignored(self):
        """Range switched (mw301..380 -> mw201..280) without clearing factory.db: the old rows must not be pulled."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'f.db'
            sup = Supervisor(settings(path), logging.getLogger('test'))
            db.register_alt(sup.conn, 1, 'mw09', 1, 'mw09r1', 1.0)
            db.register_alt(sup.conn, 2, 'mw301', 1, 'mw301r1', 1.0)
            sup.conn.execute("UPDATE alts SET phase='queue_coast'")
            self.assertEqual(sorted(sup.known()), ['mw09r1'])
            sup.conn.close()


class AddFromThreadTest(unittest.TestCase):
    def test_login_thread_registers_with_its_own_connection(self):
        """2026-10-13 live: every login thread used the main thread's sqlite connection -> ProgrammingError,
        and each entered role was closed again."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'f.db'
            sup = Supervisor(settings(path), logging.getLogger('test'))
            client = SimpleNamespace(char_id=202000, name='mw09r1', session=SimpleNamespace(pid=1))
            errors = []

            def login_thread():
                conn = db.connect(path)
                try:
                    sup.add(AltWin(client, 'mw09', 1), conn)
                except Exception as e:      # noqa: BLE001 - the test reports it
                    errors.append(e)
                finally:
                    conn.close()

            t = threading.Thread(target=login_thread)
            t.start()
            t.join()
            sup.conn.close()
            sup.logins.shutdown()
            sup.chores.shutdown()
            self.assertEqual(errors, [])
            self.assertIn(202000, sup.alts)
            self.assertEqual(sup.alts[202000].phase, 'unknown')


class SnapshotTest(unittest.TestCase):
    def test_unreadable_alt_is_not_offered_to_stations(self):
        """2026-10-13 live: mw19r1 fell back to the login screen (process alive) and two coast leaders each
        waited 120 s for it to join."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'f.db'
            sup = Supervisor(settings(path), logging.getLogger('test'))
            try:
                import os
                me = SimpleNamespace(pid=os.getpid())        # a live process
                ok = AltWin(SimpleNamespace(char_id=1, name='mw09r1', session=me), 'mw09', 1)
                lost = AltWin(SimpleNamespace(char_id=2, name='mw10r1', session=me), 'mw10', 1, unreadable_since=5.0)
                sup.add(ok)
                sup.add(lost)
                self.assertEqual(set(sup.snapshot()), {1})
            finally:
                sup.conn.close()
                sup.logins.shutdown()
                sup.chores.shutdown()


class WaitForTeamTest(unittest.TestCase):
    def setUp(self):
        import os
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'f.db'
        self.sup = Supervisor(settings(self.path), logging.getLogger('test'))
        self.me = SimpleNamespace(pid=os.getpid())
        self.st = {'station_id': 'well1', 'role': 'well', 'char_id': 99}

    def tearDown(self):
        self.sup.conn.close()
        self.sup.logins.shutdown()
        self.sup.chores.shutdown()
        self.tmp.cleanup()

    def queue(self, cid, since):
        self.sup.add(AltWin(SimpleNamespace(char_id=cid, name=f'mw{cid:02d}r1', session=self.me), f'mw{cid:02d}', 1))
        self.sup.conn.execute("UPDATE alts SET phase='queue_well', phase_since=? WHERE char_id=?", (since, cid))

    def wait(self, max_wait):
        """Run the gate in a thread; True if it returned by itself within 0.5 s."""
        done = threading.Event()

        def body():
            conn = db.connect(self.path)
            try:
                self.sup.wait_for_team(conn, self.st, 'queue_well', 4, max_wait, logging.getLogger('test'), self.me.pid)
                done.set()
            except Exception:       # noqa: BLE001 - Stopped when the test ends the wait
                pass
            finally:
                conn.close()

        t = threading.Thread(target=body)
        t.start()
        got = done.wait(0.5)
        self.sup.stop.set()
        t.join(5)
        return got

    def test_full_team_goes_at_once(self):
        import time
        for cid in (1, 2, 3, 4):
            self.queue(cid, time.time())
        self.assertTrue(self.wait(90))

    def test_partial_team_waits(self):
        import time
        self.queue(1, time.time())
        self.queue(2, time.time())
        self.assertFalse(self.wait(90))

    def test_station_process_gone_stops_waiting(self):
        """Stage A: a station closed as lost while waiting for a team must not wait on (its worker logs it in)."""
        conn = db.connect(self.path)
        try:
            with self.assertRaises(RuntimeError):
                self.sup.wait_for_team(conn, self.st, 'queue_well', 4, 90, logging.getLogger('test'), 0)
        finally:
            conn.close()

    def test_partial_team_goes_after_max_wait(self):
        import time
        self.queue(1, time.time() - 100)
        self.assertTrue(self.wait(90))

    def test_unreadable_alt_does_not_count(self):
        import time
        for cid in (1, 2, 3, 4):
            self.queue(cid, time.time())
        self.sup.alts[4].unreadable_since = 1.0
        self.assertFalse(self.wait(90))


class TwoWellLeadersTest(unittest.TestCase):
    """Second well leader is optional (user 2026-10-13): one leader must behave as before, two must not split
    one queue into two half teams."""

    def run_choose(self, sup, path, leader_id, waiting_ids, alts):
        from factory.supervisor import GatedWellTeamRun
        conn = db.connect(path)
        try:
            st = {'station_id': f'well{leader_id}', 'role': 'well', 'char_id': leader_id}
            s = SimpleNamespace(well_team_size=4, well_lease=1200)
            run = GatedWellTeamRun.__new__(GatedWellTeamRun)
            run.conn, run.station, run.alts, run.s, run.gate = conn, st, alts, s, sup.well_gate
            run.log = logging.getLogger('test')
            # the base choose() observes the game; replace it with the claim it ends in
            run_super = lambda team: db.claim(conn, st['station_id'], waiting_ids(conn), 1200, __import__('time').time())
            import factory.wellteam as wt
            orig = wt.WellTeamRun.choose
            wt.WellTeamRun.choose = lambda self, team: run_super(team)
            try:
                return run.choose(SimpleNamespace(members=[]))
            finally:
                wt.WellTeamRun.choose = orig
        finally:
            conn.close()

    def test_second_leader_does_not_take_a_half_team(self):
        import time
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'f.db'
            sup = Supervisor(settings(path), logging.getLogger('test'))
            try:
                for cid in (1, 2, 3, 4):
                    db.register_alt(sup.conn, cid, f'mw{cid:02d}', 1, f'mw{cid:02d}r1', time.time())
                    sup.conn.execute("UPDATE alts SET phase='queue_well', phase_since=? WHERE char_id=?",
                                     (time.time(), cid))
                alts = {c: None for c in (1, 2, 3, 4)}

                def waiting(conn):
                    return [r['char_id'] for r in db.waiting(conn, 'queue_well', time.time())][:4]

                self.assertEqual(sorted(self.run_choose(sup, path, 101, waiting, alts)), [1, 2, 3, 4])
                self.assertEqual(self.run_choose(sup, path, 102, waiting, alts), [])     # nothing left: waits
            finally:
                sup.conn.close()
                sup.logins.shutdown()
                sup.chores.shutdown()

    def test_well_buffer_scales_with_leaders(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'f.db'
            conn = db.connect(path)
            for i in (1, 2):
                db.heartbeat(conn, f'well{i}', 'well', 100 + i, 'online', 0.0)
            conn.close()
            sup = Supervisor(settings(path), logging.getLogger('test'))
            try:
                self.assertEqual(sup.policy.well_buffer, 8)
            finally:
                sup.conn.close()
                sup.logins.shutdown()
                sup.chores.shutdown()
        with tempfile.TemporaryDirectory() as tmp:
            sup = Supervisor(settings(Path(tmp) / 'f.db'), logging.getLogger('test'))
            try:
                self.assertEqual(sup.policy.well_buffer, 4)          # one or no well leader: unchanged
            finally:
                sup.conn.close()
                sup.logins.shutdown()
                sup.chores.shutdown()

    def test_coast_queue_scales_with_leaders(self):
        """2026-10-13: a third coast leader; coast_buffer / coast_backlog are per coast leader (2 leaders: 4 / 8)."""
        for leaders, want in ((3, (6, 12)), (2, (4, 8)), (0, (2, 4))):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'f.db'
                conn = db.connect(path)
                for i in range(1, leaders + 1):
                    db.heartbeat(conn, f'coast{i}', 'coast', 100 + i, 'online', 0.0)
                conn.close()
                s = settings(path)
                s.policy = PullPolicy(coast_buffer=2, coast_backlog=4)
                sup = Supervisor(s, logging.getLogger('test'))
                try:
                    self.assertEqual((sup.policy.coast_buffer, sup.policy.coast_backlog), want)
                    self.assertEqual(sup.policy.well_buffer, 4)
                finally:
                    sup.conn.close()
                    sup.logins.shutdown()
                    sup.chores.shutdown()


class NextDeleteTest(unittest.TestCase):
    def test_reserves_a_free_account_only(self):
        import os
        import time
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'f.db'
            s = settings(path)
            s.login.accounts = (Account('mw09', 'x'), Account('mw10', 'x'), Account('mw11', 'x'))
            s.delete = s.launch = SimpleNamespace(close_settle=3.0)
            s.rebuild_after = 3 * 3600
            sup = Supervisor(s, logging.getLogger('test'))
            try:
                for cid, acct in ((1, 'mw09'), (2, 'mw10'), (3, 'mw11')):
                    db.register_alt(sup.conn, cid, acct, 1, f'{acct}r1', time.time())
                    sup.conn.execute("UPDATE alts SET phase='delete', phase_since=? WHERE char_id=?", (cid, cid))
                me = SimpleNamespace(pid=os.getpid())
                # mw09 has another role online (would be kicked), mw10 was closed a moment ago
                sup.add(AltWin(SimpleNamespace(char_id=9, name='mw09r2', session=me), 'mw09', 2))
                sup.closed_at['mw10'] = time.monotonic()
                self.assertEqual(sup.next_delete(sup.conn), 'mw11r1')
                self.assertEqual(sup.deleting, 'mw11')
                # rebuild: mw11r1 deleted 4 h ago -> its account is due; mw10r1 deleted just now is not
                sup.deleting = None
                sup.conn.execute("UPDATE alts SET phase='deleted', deleted_at=? WHERE char_id=3", (time.time() - 4 * 3600,))
                sup.conn.execute("UPDATE alts SET phase='deleted', deleted_at=? WHERE char_id=2", (time.time(),))
                self.assertEqual(sup.next_rebuild(sup.conn), 'mw11')
                self.assertEqual(sup.deleting, 'mw11')
                sup.deleting = None
                db.register_alt(sup.conn, 30, 'mw11', 5, 'mw11r5', time.time())      # rebuilt already
                self.assertIsNone(sup.next_rebuild(sup.conn))
            finally:
                sup.conn.close()
                sup.logins.shutdown()
                sup.chores.shutdown()


if __name__ == '__main__':
    unittest.main()


class BagBlockedTest(unittest.TestCase):
    """status() alarm for a leader whose bag selling could not clear (factory/supply.py blocked)."""

    def sup(self):
        return SimpleNamespace(lock=threading.Lock(), bag_blocked={}, supply=SimpleNamespace(sell_below_free=8))

    def test_set_by_a_run_and_cleared_by_the_next(self):
        s = self.sup()
        Supervisor.note_blocked(s, 'coast1', {'blocked': '！cap07 背包…'}, [], 40)
        self.assertEqual(s.bag_blocked, {'coast1': '！cap07 背包…'})
        Supervisor.note_blocked(s, 'coast1', {'blocked': None}, [], 40)
        self.assertEqual(s.bag_blocked, {})

    def test_without_a_run_cleared_only_when_the_bag_has_room(self):
        s = self.sup()
        s.bag_blocked['coast1'] = 'x'
        Supervisor.note_blocked(s, 'coast1', None, [object()] * 35, 40)     # failed / paused run, 5 free: keep
        self.assertEqual(s.bag_blocked, {'coast1': 'x'})
        Supervisor.note_blocked(s, 'coast1', None, None, None)                # bag unreadable: keep
        self.assertEqual(s.bag_blocked, {'coast1': 'x'})
        Supervisor.note_blocked(s, 'coast1', None, [object()] * 30, 40)     # 10 free: cleared
        self.assertEqual(s.bag_blocked, {})
