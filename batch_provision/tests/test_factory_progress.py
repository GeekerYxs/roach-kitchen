"""Stage B4a: a leader with no finished batch while alts wait -> close + relogin (factory/progress.py + supervisor)."""
import logging
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from factory import db, outage, progress, supervisor
from factory.phase import COAST, DISPATCHER, QUEUE_COAST, WELL
from factory.progress import Track, load_limits, observe, stalled
from provisioner import native
from provisioner.config import Account, Station
from tests.test_factory_relogin import WELL1, close, make_sup

FS = SimpleNamespace(coast_form_timeout=120.0, coast_farm_timeout=1800.0, well_form_timeout=120.0,
                     well_train_timeout=1800.0, transport_timeout=240.0)
LIMIT = 2520.0
COAST1 = Station('coast1', 'coast', Account('xq02', 'pw', 1), '伏地魔2')


class LimitsTest(unittest.TestCase):
    def test_defaults_are_batch_timeouts_plus_ten_minutes(self):
        self.assertEqual(load_limits({}, FS), {COAST: LIMIT, WELL: LIMIT, DISPATCHER: 840.0})

    def test_override_and_off(self):
        lim = load_limits({'stall_minutes_coast': 60, 'stall_minutes_dispatcher': 0}, FS)
        self.assertEqual((lim[COAST], lim[DISPATCHER]), (3600.0, None))

    def test_shorter_than_the_batch_timeout_is_refused(self):
        with self.assertRaises(ValueError):
            load_limits({'stall_minutes_well': 20}, FS)


class DecisionTest(unittest.TestCase):
    def test_stuck_while_alts_wait(self):
        t = Track(since=0.0)
        observe(t, 100.0, True, False, 4)
        self.assertIsNone(stalled(t, 50.0, 100.0 + LIMIT - 1, LIMIT))
        self.assertEqual(stalled(t, 50.0, 100.0 + LIMIT, LIMIT), LIMIT)

    def test_recent_batch_resets(self):
        t = Track(since=0.0, waiting_since=0.0)
        self.assertIsNone(stalled(t, 1000.0, 1000.0 + LIMIT - 1, LIMIT))

    def test_nobody_waiting_is_just_idle(self):
        """Upstream slow: the coast leader has nothing to do for an hour, then one alt arrives."""
        t = Track(since=0.0)
        observe(t, 3600.0, True, False, 0)
        self.assertIsNone(stalled(t, None, 3600.0, LIMIT))
        observe(t, 3601.0, True, False, 1)
        self.assertIsNone(stalled(t, None, 3602.0, LIMIT))       # the clock starts when they started to wait

    def test_queue_emptied_restarts_the_clock(self):
        t = Track(since=0.0)
        observe(t, 10.0, True, False, 3)
        observe(t, 2000.0, True, False, 0)
        observe(t, 2010.0, True, False, 2)
        self.assertIsNone(stalled(t, None, 10.0 + LIMIT, LIMIT))

    def test_offline_and_drain_reset(self):
        t = Track(since=0.0, waiting_since=0.0)
        observe(t, 1000.0, False, False, 4)                       # window gone: stage A's job
        self.assertEqual((t.since, t.waiting_since), (1000.0, None))
        observe(t, 1001.0, True, True, 4)                         # maintenance drain: no new batches on purpose
        self.assertEqual(t.since, 1001.0)

    def test_off(self):
        self.assertIsNone(stalled(Track(since=0.0, waiting_since=0.0), None, 1e9, None))


def add_waiting(conn, n, now):
    for i in range(n):
        db.register_alt(conn, 300000 + i, f'mw3{i:02d}', 1, f'mw3{i:02d}r1', now)
        conn.execute('UPDATE alts SET phase=?, phase_since=? WHERE char_id=?', (QUEUE_COAST, now, 300000 + i))


class SupervisorProgressTest(unittest.TestCase):
    """On a real Supervisor object (a bare one hid the stage B3 attribute clash)."""

    def make(self, tmp):
        sup = make_sup(tmp, [WELL1, COAST1])
        sup.s.stall = {COAST: LIMIT, WELL: LIMIT, DISPATCHER: 840.0}
        sup.s.outage = outage.OutageSettings()
        db.register_station(sup.conn, 'coast1', COAST, 777, 'xq02', '伏地魔2', 5353, time.time())
        return sup

    def test_stuck_coast_leader_is_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            sup = self.make(tmp)
            try:
                t0 = time.time()
                add_waiting(sup.conn, 4, t0)
                killed = []
                with mock.patch.object(native, 'alive', lambda pid: True), \
                        mock.patch.object(native, 'kill', lambda pid: killed.append(pid) or True), \
                        mock.patch.object(supervisor, 'probe', lambda pid, cid: ('ok', None)), \
                        mock.patch.object(sup, 'draining', lambda: None):
                    with mock.patch.object(supervisor.time, 'time', lambda: t0):
                        sup.watch_progress()
                    with mock.patch.object(supervisor.time, 'time', lambda: t0 + LIMIT - 5):
                        sup.watch_progress()
                    self.assertEqual(killed, [])
                    with mock.patch.object(supervisor.time, 'time', lambda: t0 + LIMIT + 1):
                        sup.watch_progress()
                    self.assertEqual(killed, [5353])                # coast1 only (well queue is empty)
                    with mock.patch.object(supervisor.time, 'time', lambda: t0 + LIMIT + 60):
                        sup.watch_progress()
                    self.assertEqual(killed, [5353])                # once per limit
                row = sup.conn.execute("SELECT message FROM events WHERE kind='station' AND station_id='coast1' "
                                       "AND message LIKE '无进展%'"
                                       ).fetchone()
                self.assertIn('无进展关窗', row['message'])
            finally:
                close(sup)

    def test_finished_batch_keeps_it_alive(self):
        with tempfile.TemporaryDirectory() as tmp:
            sup = self.make(tmp)
            try:
                t0 = time.time()
                add_waiting(sup.conn, 4, t0)
                db.log_event(sup.conn, t0 + 1000, 'coast_farm', '刷怪完成', station_id='coast1')
                killed = []
                with mock.patch.object(native, 'alive', lambda pid: True), \
                        mock.patch.object(native, 'kill', lambda pid: killed.append(pid) or True), \
                        mock.patch.object(supervisor, 'probe', lambda pid, cid: ('ok', None)), \
                        mock.patch.object(sup, 'draining', lambda: None):
                    for at in (t0, t0 + LIMIT + 1):
                        with mock.patch.object(supervisor.time, 'time', lambda at=at: at):
                            sup.watch_progress()
                self.assertEqual(killed, [])
            finally:
                close(sup)


if __name__ == '__main__':
    logging.getLogger('test').addHandler(logging.NullHandler())
    unittest.main()
