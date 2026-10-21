"""Per-IP window limit: the supervisor's alt cap, the launch gate and the doctor's check. No game needed."""
import logging
import unittest
from unittest import mock

from factory.schedule import alt_window_cap
from provisioner import config, login
from provisioner.doctor import BAD, OK, WARN, window_budget
from provisioner.login import LaunchThrottle

LOG = logging.getLogger('test')


class AltCap(unittest.TestCase):
    def test_production_11_stations(self):
        # 50 - 11 stations - 1 delete/rebuild - 2 spare = 36 (production 2026-10-21 had max_windows 55)
        cap, why = alt_window_cap(55, 50, 11, 2)
        self.assertEqual(cap, 36)
        self.assertIn('36', why)

    def test_max_windows_smaller_wins(self):
        self.assertEqual(alt_window_cap(20, 50, 11, 2)[0], 20)

    def test_more_stations_less_alts(self):
        self.assertEqual(alt_window_cap(40, 50, 14, 2)[0], 33)

    def test_off(self):
        self.assertEqual(alt_window_cap(55, 0, 11, 2)[0], 55)

    def test_never_below_one(self):
        self.assertEqual(alt_window_cap(40, 10, 11, 2)[0], 1)


class Config(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(config.ip_max_clients({}), 50)
        self.assertEqual(config.ip_reserve({}), 2)

    def test_values(self):
        self.assertEqual(config.ip_max_clients({'ip_max_clients': 0}), 0)
        self.assertEqual(config.ip_max_clients({'ip_max_clients': 30}), 30)
        self.assertEqual(config.ip_reserve({'ip_reserve': 0}), 0)


class Gate(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(login.native, 'free_memory_mb', return_value=10 ** 6)
        p.start()
        self.addCleanup(p.stop)

    def test_passes_below_limit(self):
        t = LaunchThrottle(0, 0, 50, count=lambda: 48)
        with t.launch(LOG):
            self.assertEqual(t._launching, 1)
        self.assertEqual(t._launching, 0)

    def test_waits_at_limit_until_a_window_closes(self):
        procs = [49]
        sleeps = []

        def sleep(sec):
            sleeps.append(sec)
            procs[0] = 48           # an old window went away
        t = LaunchThrottle(0, 0, 50, count=lambda: procs[0])
        with mock.patch.object(login.time, 'sleep', sleep), self.assertLogs('test', 'WARNING'):
            with t.launch(LOG):
                pass
        self.assertEqual(sleeps, [3])

    def test_launches_on_their_way_count(self):
        t = LaunchThrottle(0, 0, 50, count=lambda: 47)
        sleeps = []
        with t.launch(LOG):         # 47 + 1 on its way = 48: room for one more, not two
            with t.launch(LOG):
                with mock.patch.object(login.time, 'sleep', lambda s: (sleeps.append(s), t.__setattr__(
                        '_count', lambda: 40))), self.assertLogs('test', 'WARNING'):
                    with t.launch(LOG):
                        pass
        self.assertEqual(sleeps, [3])
        self.assertEqual(t._launching, 0)

    def test_station_is_not_capped(self):
        t = LaunchThrottle(0, 0, 50, count=lambda: 60)
        with mock.patch.object(login.time, 'sleep', side_effect=AssertionError('station waited')):
            with t.uncapped().launch(LOG):
                self.assertEqual(t._launching, 1)
        self.assertEqual(t._launching, 0)

    def test_no_limit(self):
        t = LaunchThrottle(0, 0, 0, count=lambda: 99)
        with mock.patch.object(login.time, 'sleep', side_effect=AssertionError('waited')):
            with t.launch(LOG):
                pass

    def test_failed_launch_frees_its_reservation(self):
        t = LaunchThrottle(0, 0, 50, count=lambda: 10)
        with self.assertRaises(RuntimeError):
            with t.launch(LOG):
                raise RuntimeError('launch failed')
        self.assertEqual(t._launching, 0)

    def test_of_settings(self):
        s = mock.Mock(launch_interval=2.0, min_free_memory_mb=1500, max_clients=50)
        t = LaunchThrottle.of(s)
        self.assertEqual((t.interval, t.min_free_mb, t.max_clients), (2.0, 1500, 50))


class Doctor(unittest.TestCase):
    def test_fits(self):
        level, text = window_budget(50, 11, 36, 2)
        self.assertEqual(level, OK)
        self.assertIn('48', text)

    def test_over(self):
        self.assertEqual(window_budget(50, 11, 40, 2)[0], BAD)

    def test_too_many_stations(self):
        self.assertEqual(window_budget(50, 48, 1, 2)[0], BAD)

    def test_off(self):
        self.assertEqual(window_budget(0, 11, 55, 2)[0], WARN)


if __name__ == '__main__':
    unittest.main()
