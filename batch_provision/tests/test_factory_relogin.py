"""Stage A: station lost -> close -> relogin decisions (factory/relogin.py) and the supervisor glue around them."""
import logging
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from factory import db, relogin
from factory.relogin import (FOREIGN, GONE, LOST, OK, Watch, check_entered, decide_watch, health, may_kill,
                             other_login_running, relogin_delay, relogin_due, relogin_mark)
from factory.schedule import PullPolicy
from factory.supervisor import Relogin, Supervisor
from provisioner import native
from provisioner.config import Account, Station

ME = 199366


class HealthTest(unittest.TestCase):
    def test_states(self):
        self.assertEqual(health(False, True, native.WORLD_STAGE, ME, ME), GONE)
        self.assertEqual(health(True, False, native.WORLD_STAGE, ME, ME), FOREIGN)
        self.assertEqual(health(True, True, native.WORLD_STAGE, ME, ME), OK)

    def test_login_screen_with_process_alive_is_lost(self):
        """2026-10-14 live: 伏地魔1 back on the account/password screen, process alive."""
        self.assertEqual(health(True, True, native.WORLD_STAGE, None, ME), LOST)
        self.assertEqual(health(True, True, native.SELECTION_STAGE, None, ME), LOST)

    def test_other_character_in_the_process_is_lost(self):
        self.assertEqual(health(True, True, native.WORLD_STAGE, 202000, ME), LOST)


class WatchTest(unittest.TestCase):
    def test_clock_starts_then_kills_after_lost_after(self):
        self.assertEqual(decide_watch(LOST, None, 100.0, 30), 'lost')
        self.assertEqual(decide_watch(LOST, 100.0, 129.0, 30), 'wait')
        self.assertEqual(decide_watch(LOST, 100.0, 130.0, 30), 'kill')

    def test_readable_again_or_gone_resets(self):
        for h in (OK, GONE, FOREIGN):
            self.assertEqual(decide_watch(h, 100.0, 500.0, 30), h)

    def test_may_kill_only_the_same_window(self):
        self.assertTrue(may_kill(0x10, 0x10, False))
        self.assertTrue(may_kill(None, 0x10, False))       # supervisor started while the station was lost
        self.assertFalse(may_kill(0x10, 0x20, False))      # pid reused by another window
        self.assertFalse(may_kill(None, 0x10, True))       # pid now one of our alt windows


class ReloginDecisionTest(unittest.TestCase):
    def test_backoff(self):
        self.assertEqual([relogin_delay(n) for n in range(0, 8)], [0, 30, 60, 120, 240, 600, 600, 600])

    def test_due_only_when_process_gone(self):
        w = Watch()
        self.assertTrue(relogin_due(GONE, w, 0.0))
        self.assertTrue(relogin_due(FOREIGN, w, 0.0))
        self.assertFalse(relogin_due(LOST, w, 0.0))        # the watcher closes it first
        self.assertFalse(relogin_due(OK, w, 0.0))

    def test_due_respects_backoff_and_block(self):
        self.assertFalse(relogin_due(GONE, Watch(next_try=50.0), 49.0))
        self.assertTrue(relogin_due(GONE, Watch(next_try=50.0), 50.0))
        self.assertFalse(relogin_due(GONE, Watch(blocked='wrong role'), 1e9))

    def test_other_login_running(self):
        now = 10_000.0
        self.assertTrue(other_login_running('relogin', now - 10, now))
        self.assertFalse(other_login_running('relogin', now - relogin.RELOGIN_FRESH, now))   # stale mark
        self.assertFalse(other_login_running('online', now, now))
        self.assertFalse(other_login_running(None, now, now))

    def test_mark_of_a_live_process_blocks(self):
        now = 10_000.0
        self.assertEqual(relogin_mark(4321), 'relogin:4321')
        with mock.patch('factory.relogin.native.alive', return_value=True) as alive:
            self.assertTrue(other_login_running(relogin_mark(4321), now - 10, now))
            alive.assert_called_once_with(4321)
            self.assertFalse(other_login_running(relogin_mark(4321), now - relogin.RELOGIN_FRESH, now))

    def test_mark_of_a_killed_process_is_ignored_at_once(self):
        """2026-10-20 production: every process killed mid-login, 一键登录工位.cmd then refused all 11 stations."""
        now = 10_000.0
        with mock.patch('factory.relogin.native.alive', return_value=False):
            self.assertFalse(other_login_running(relogin_mark(4321), now - 1, now))

    def test_own_process_counts_as_alive(self):
        now = 10_000.0
        self.assertTrue(other_login_running(relogin_mark(os.getpid()), now - 1, now))

    def test_check_entered(self):
        ok = {'ok': True, 'char_id': ME, 'role': '伏地魔1'}
        self.assertEqual(check_entered(ok, ME, '伏地魔1'), (None, False))
        self.assertEqual(check_entered(ok, ME, ''), (None, False))
        err, permanent = check_entered({'ok': False, 'error': 'LoginFailed: x'}, ME, '伏地魔1')
        self.assertEqual((err, permanent), ('LoginFailed: x', False))
        err, permanent = check_entered({**ok, 'char_id': 1}, ME, '伏地魔1')
        self.assertTrue(permanent)
        self.assertIn('ID=1', err)
        err, permanent = check_entered({**ok, 'role': '别人'}, ME, '伏地魔1')
        self.assertTrue(permanent)


def make_sup(tmp, stations):
    path = Path(tmp) / 'f.db'
    s = SimpleNamespace(
        factory=SimpleNamespace(db_path=path),
        login=SimpleNamespace(accounts=(Account('mw09', 'x'),), slots=(1,), launch_interval=0.0, min_free_memory_mb=0),
        policy=PullPolicy(), coast_max_wait=90.0, well_max_wait=90.0, parallel_logins=2, idle_close=60.0,
        not_served=frozenset(),
        relogin=Relogin(SimpleNamespace(), {x.station_id: x for x in stations}, 30.0), relogin_error=None)
    sup = Supervisor(s, logging.getLogger('test'))
    db.register_station(sup.conn, 'well1', 'well', ME, 'qooqp6', '伏地魔1', 4242, time.time())
    return sup


def close(sup):
    sup.conn.close()
    sup.logins.shutdown()
    sup.chores.shutdown()


WELL1 = Station('well1', 'well', Account('qooqp6', 'pw', 1), '伏地魔1')
OK_SUMMARY = {'ok': True, 'char_id': ME, 'role': '伏地魔1', 'pid': 5151, 'hwnd': 0x99, 'map_id': 1}


class SupervisorReloginTest(unittest.TestCase):
    def test_lost_station_is_closed_after_lost_after(self):
        with tempfile.TemporaryDirectory() as tmp:
            sup = make_sup(tmp, [WELL1])
            try:
                with mock.patch('factory.supervisor.probe', return_value=(LOST, 0x77)), \
                        mock.patch('factory.supervisor.native.kill') as kill, \
                        mock.patch('factory.supervisor.time.monotonic', side_effect=[100.0, 131.0]):
                    sup.watch_stations()
                    kill.assert_not_called()
                    sup.watch_stations()
                    kill.assert_called_once_with(4242)
                self.assertGreaterEqual(sup.watch('well1').next_try, 131.0)
            finally:
                close(sup)

    def test_unconfigured_station_is_not_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            sup = make_sup(tmp, [])
            try:
                with mock.patch('factory.supervisor.probe', return_value=(LOST, 0x77)), \
                        mock.patch('factory.supervisor.native.kill') as kill, \
                        mock.patch('factory.supervisor.time.monotonic', side_effect=[100.0, 131.0]):
                    sup.watch_stations()
                    sup.watch_stations()
                kill.assert_not_called()
            finally:
                close(sup)

    def test_relogin_registers_the_new_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            sup = make_sup(tmp, [WELL1])
            try:
                st = db.station(sup.conn, 'well1')
                with mock.patch('factory.supervisor.probe', return_value=(GONE, None)), \
                        mock.patch('factory.supervisor.foreign_windows', return_value=[]), \
                        mock.patch('factory.supervisor.EnterJob') as job:
                    job.return_value.run.return_value = OK_SUMMARY
                    self.assertTrue(sup.try_relogin(sup.conn, st, logging.getLogger('test')))
                row = db.station(sup.conn, 'well1')
                self.assertEqual((row['pid'], row['status']), (5151, 'online'))
                self.assertEqual(sup.watch('well1').fails, 0)
            finally:
                close(sup)

    def test_failed_relogin_backs_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            sup = make_sup(tmp, [WELL1])
            try:
                st = db.station(sup.conn, 'well1')
                with mock.patch('factory.supervisor.probe', return_value=(GONE, None)), \
                        mock.patch('factory.supervisor.foreign_windows', return_value=[]), \
                        mock.patch('factory.supervisor.native.alive', return_value=False), \
                        mock.patch('factory.supervisor.EnterJob') as job:
                    job.return_value.run.return_value = {'ok': False, 'error': 'LoginFailed: 网络', 'pid': None}
                    self.assertTrue(sup.try_relogin(sup.conn, st, logging.getLogger('test')))
                    st = db.station(sup.conn, 'well1')
                    self.assertFalse(sup.try_relogin(sup.conn, st, logging.getLogger('test')))   # backing off
                    self.assertEqual(job.call_count, 1)
                w = sup.watch('well1')
                self.assertEqual(w.fails, 1)
                self.assertEqual(db.station(sup.conn, 'well1')['status'], 'offline')
            finally:
                close(sup)

    def test_wrong_character_is_closed_and_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            sup = make_sup(tmp, [WELL1])
            try:
                st = db.station(sup.conn, 'well1')
                with mock.patch('factory.supervisor.probe', return_value=(GONE, None)), \
                        mock.patch('factory.supervisor.foreign_windows', return_value=[]), \
                        mock.patch('factory.supervisor.native.alive', return_value=True), \
                        mock.patch('factory.supervisor.native.kill') as kill, \
                        mock.patch('factory.supervisor.EnterJob') as job:
                    job.return_value.run.return_value = {**OK_SUMMARY, 'char_id': 1, 'role': '别人'}
                    sup.try_relogin(sup.conn, st, logging.getLogger('test'))
                    kill.assert_called_once_with(5151)
                self.assertIsNotNone(sup.watch('well1').blocked)
                self.assertEqual(db.station(sup.conn, 'well1')['pid'], 4242)      # not registered
            finally:
                close(sup)

    def test_foreign_window_of_the_same_name_blocks_the_login(self):
        """Logging in would kick the user's own window."""
        with tempfile.TemporaryDirectory() as tmp:
            sup = make_sup(tmp, [WELL1])
            try:
                st = db.station(sup.conn, 'well1')
                with mock.patch('factory.supervisor.probe', return_value=(GONE, None)), \
                        mock.patch('factory.supervisor.foreign_windows', return_value=[777]), \
                        mock.patch('factory.supervisor.EnterJob') as job:
                    self.assertFalse(sup.try_relogin(sup.conn, st, logging.getLogger('test')))
                    job.assert_not_called()
            finally:
                close(sup)

    def test_login_by_stations_cmd_in_progress_is_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            sup = make_sup(tmp, [WELL1])
            try:
                db.heartbeat(sup.conn, 'well1', 'well', ME, relogin.RELOGIN_STATUS, time.time())
                st = db.station(sup.conn, 'well1')
                with mock.patch('factory.supervisor.probe', return_value=(GONE, None)), \
                        mock.patch('factory.supervisor.foreign_windows', return_value=[]), \
                        mock.patch('factory.supervisor.EnterJob') as job:
                    self.assertFalse(sup.try_relogin(sup.conn, st, logging.getLogger('test')))
                    job.assert_not_called()
            finally:
                close(sup)

    def test_mark_left_by_a_killed_login_does_not_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            sup = make_sup(tmp, [WELL1])
            try:
                db.heartbeat(sup.conn, 'well1', 'well', ME, relogin_mark(99999), time.time())
                st = db.station(sup.conn, 'well1')
                with mock.patch('factory.supervisor.probe', return_value=(GONE, None)), \
                        mock.patch('factory.supervisor.foreign_windows', return_value=[]), \
                        mock.patch('factory.relogin.native.alive', return_value=False), \
                        mock.patch('factory.supervisor.EnterJob') as job:
                    job.return_value.run.return_value = OK_SUMMARY
                    self.assertTrue(sup.try_relogin(sup.conn, st, logging.getLogger('test')))
                    job.assert_called_once()
                self.assertEqual(db.station(sup.conn, 'well1')['status'], 'online')
            finally:
                close(sup)

    def test_relogin_marks_the_station_with_its_own_pid(self):
        with tempfile.TemporaryDirectory() as tmp:
            sup = make_sup(tmp, [WELL1])
            try:
                st = db.station(sup.conn, 'well1')
                seen = []
                with mock.patch('factory.supervisor.probe', return_value=(GONE, None)), \
                        mock.patch('factory.supervisor.foreign_windows', return_value=[]), \
                        mock.patch('factory.supervisor.EnterJob') as job:
                    job.return_value.run.side_effect = lambda: (
                        seen.append(db.station(sup.conn, 'well1')['status']) or OK_SUMMARY)
                    sup.try_relogin(sup.conn, st, logging.getLogger('test'))
                self.assertEqual(seen, [relogin_mark(os.getpid())])
            finally:
                close(sup)


class FailedBatchReleaseTest(unittest.TestCase):
    def test_failed_batch_members_go_back_to_their_queue(self):
        """2026-10-14 runner: after the 35 min stall every batch timed out; its members stayed held for hours."""
        with tempfile.TemporaryDirectory() as tmp:
            sup = make_sup(tmp, [WELL1])
            try:
                for cid in (1, 2):
                    db.register_alt(sup.conn, cid, 'mw09', cid, f'mw09r{cid}', 0.0)
                    sup.conn.execute("UPDATE alts SET phase='queue_coast' WHERE char_id=?", (cid,))
                me = SimpleNamespace(session=SimpleNamespace(pid=4242))

                def body(conn, st, leader, lg):
                    db.claim(conn, 'well1', [1, 2], 1200, time.time())
                    sup.stop.set()
                    raise RuntimeError('1800s 内没有完成')

                with mock.patch.object(sup, 'scan', return_value={ME: me}),                         mock.patch('factory.supervisor.native.alive', return_value=True):
                    sup.worker(dict(db.station(sup.conn, 'well1')), body)
                self.assertEqual(db.held(sup.conn, 'well1', time.time()), [])
                self.assertEqual(len(db.waiting(sup.conn, 'queue_coast', time.time())), 2)
            finally:
                close(sup)


if __name__ == '__main__':
    unittest.main()
