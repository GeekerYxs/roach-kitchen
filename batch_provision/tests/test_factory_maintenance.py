"""Stage B2 planned maintenance: schedule, phases and the drain file (factory/maintenance.py)."""
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from factory import maintenance as m
from factory.maintenance import CLOSED, DRAIN, RUN, MaintSettings

# the official routine: every Thursday 10:00-12:00 (2026-10-22 is a Thursday)
THU = MaintSettings(weekly=(m.parse_weekly('thu 10:00-12:00'),))
START, END = datetime(2026, 10, 22, 10, 0), datetime(2026, 10, 22, 12, 0)


def at(day, hh, mm=0):
    return datetime(2026, 10, day, hh, mm)


class ParseTest(unittest.TestCase):
    def test_weekly(self):
        self.assertEqual(m.parse_weekly('thu 10:00-12:00'), (3, (10, 0), (12, 0)))
        self.assertEqual(m.parse_weekly(' Wed 9:30 - 11:00 '), (2, (9, 30), (11, 0)))

    def test_once(self):
        self.assertEqual(m.parse_once('2026-10-16 18:00-19:00'), (at(16, 18), at(16, 19)))

    def test_bad(self):
        for text in ('thursday 10:00-12:00', 'thu 10-12', 'thu 12:00-10:00', 'thu 25:00-26:00'):
            with self.assertRaises(ValueError, msg=text):
                m.parse_weekly(text)
        with self.assertRaises(ValueError):
            m.parse_once('10-16 18:00-19:00')

    def test_load(self):
        self.assertIsNone(m.load_maintenance({}))
        self.assertIsNone(m.load_maintenance({'maintenance': {'enabled': False, 'weekly': ['thu 10:00-12:00']}}))
        s = m.load_maintenance({'maintenance': {'weekly': ['thu 10:00-12:00'], 'once': ['2026-10-16 18:00-19:00']}})
        self.assertEqual((s.drain, s.close, s.canary_every), (600.0, 300.0, 1200.0))
        with self.assertRaises(ValueError):
            m.load_maintenance({'maintenance': {'drain_minutes': 3, 'close_minutes': 5}})

    def test_shipped_supervisor_toml(self):
        from provisioner import config
        s = m.load_maintenance(config._read(Path(__file__).resolve().parent.parent / 'supervisor.toml'))
        self.assertEqual(s.weekly, ((3, (10, 0), (12, 0)),))


class PhaseTest(unittest.TestCase):
    def test_thursday_timeline(self):
        self.assertEqual(m.phase(at(22, 9, 49), THU), (RUN, None))
        self.assertEqual(m.phase(at(22, 9, 50), THU), (DRAIN, (START, END)))
        self.assertEqual(m.phase(at(22, 9, 54), THU), (DRAIN, (START, END)))
        self.assertEqual(m.phase(at(22, 9, 55), THU), (CLOSED, (START, END)))
        self.assertEqual(m.phase(at(22, 11, 59), THU), (CLOSED, (START, END)))
        self.assertEqual(m.phase(at(22, 12, 0), THU), (RUN, None))

    def test_other_days_and_weeks(self):
        self.assertEqual(m.phase(at(21, 10, 30), THU)[0], RUN)          # Wednesday
        self.assertEqual(m.phase(at(29, 10, 30), THU), (CLOSED, (at(29, 10), at(29, 12))))
        self.assertEqual(m.phase(datetime(2026, 10, 15, 11, 0), THU)[0], CLOSED)

    def test_monday_sees_last_weeks_sunday_window(self):
        late = MaintSettings(weekly=(m.parse_weekly('sun 23:00-24:00'),))
        self.assertEqual(m.phase(datetime(2026, 10, 25, 23, 30), late)[0], CLOSED)
        self.assertEqual(m.phase(datetime(2026, 10, 26, 0, 0), late)[0], RUN)
        # drain for Monday 00:05 starts on Sunday
        mon = MaintSettings(weekly=(m.parse_weekly('mon 00:05-01:00'),))
        self.assertEqual(m.phase(datetime(2026, 10, 25, 23, 58), mon)[0], DRAIN)

    def test_once_entry(self):
        s = MaintSettings(weekly=THU.weekly, once=(m.parse_once('2026-10-16 18:00-19:00'),))
        self.assertEqual(m.phase(datetime(2026, 10, 16, 17, 52), s)[0], DRAIN)
        self.assertEqual(m.phase(datetime(2026, 10, 16, 18, 30), s), (CLOSED, (at(16, 18), at(16, 19))))

    def test_closed_beats_drain_when_windows_overlap(self):
        s = MaintSettings(once=(m.parse_once('2026-10-22 10:00-10:30'), m.parse_once('2026-10-22 10:07-12:00')))
        self.assertEqual(m.phase(at(22, 10, 0), s), (CLOSED, (at(22, 10), at(22, 10, 30))))

    def test_next_window(self):
        self.assertEqual(m.next_window(at(21, 12), THU), (START, END))
        self.assertEqual(m.next_window(at(22, 11), THU), (START, END))
        self.assertEqual(m.next_window(at(22, 12), THU), (at(29, 10), at(29, 12)))
        self.assertIsNone(m.next_window(at(22, 12), MaintSettings()))


class DrainFileTest(unittest.TestCase):
    def test_write_read_clear(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'state' / 'drain.json'
            self.assertIsNone(m.drain_reason(m.read_drain(path), 0))
            m.write_drain(path, 1000.0, '计划维护 10-22 10:00 前收尾')
            self.assertEqual(m.drain_reason(m.read_drain(path), 999.0), '计划维护 10-22 10:00 前收尾')
            self.assertIsNone(m.drain_reason(m.read_drain(path), 1000.0))      # expired: a dead guard blocks nothing
            m.clear_drain(path)
            m.clear_drain(path)
            self.assertIsNone(m.read_drain(path))


class SupervisorDrainTest(unittest.TestCase):
    def test_supervisor_reads_drain_file(self):
        import logging
        from unittest import mock
        from factory import supervisor
        sup = object.__new__(supervisor.Supervisor)
        sup.log = logging.getLogger('test.drain')
        sup.log.addHandler(logging.NullHandler())
        sup.log.propagate = False
        sup._drain = (-supervisor.DRAIN_EVERY, None)
        with tempfile.TemporaryDirectory() as d, mock.patch.object(m, 'DRAIN_PATH', Path(d) / 'drain.json'),                 mock.patch.object(supervisor.time, 'monotonic') as mono:
            mono.return_value = 100.0
            self.assertIsNone(sup.draining())
            m.write_drain(m.DRAIN_PATH, 4e9, '计划维护 10-22 10:00 前收尾')
            self.assertIsNone(sup.draining())                   # cached for DRAIN_EVERY s
            mono.return_value = 100.0 + supervisor.DRAIN_EVERY
            self.assertEqual(sup.draining(), '计划维护 10-22 10:00 前收尾')
            m.clear_drain(m.DRAIN_PATH)
            mono.return_value = 100.0 + 2 * supervisor.DRAIN_EVERY
            self.assertIsNone(sup.draining())


if __name__ == '__main__':
    unittest.main()
