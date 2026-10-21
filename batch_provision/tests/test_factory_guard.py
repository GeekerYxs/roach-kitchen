"""Stage B1 guard: restart decisions (factory/guard.py) and the supervisor heartbeat (factory/heartbeat.py)."""
import tempfile
import unittest
from pathlib import Path

from factory import heartbeat
from factory.guard import (EXITED, FINAL, RUN, STALLED, GuardSettings, descendants, judge, kill_targets, load_guard,
                           may_restart)

SUP = 5000      # supervisor pid
S = GuardSettings()


class JudgeTest(unittest.TestCase):
    def test_running_with_fresh_heartbeat(self):
        self.assertEqual(judge(None, {'pid': SUP, 'at': 1000.0}, SUP, 0.0, 1200.0, 300), RUN)

    def test_heartbeat_too_old_is_stalled(self):
        """2026-10-14 runner: the supervisor wrote nothing for 35 min."""
        self.assertEqual(judge(None, {'pid': SUP, 'at': 1000.0}, SUP, 0.0, 1300.0, 300), STALLED)

    def test_old_runs_heartbeat_ignored_clock_from_start(self):
        old = {'pid': 4000, 'at': 10.0}
        self.assertEqual(judge(None, old, SUP, 1000.0, 1200.0, 300), RUN)
        self.assertEqual(judge(None, old, SUP, 1000.0, 1300.0, 300), STALLED)
        self.assertEqual(judge(None, None, SUP, 1000.0, 1300.0, 300), STALLED)

    def test_crash_restarts_but_config_error_ctrl_c_and_second_brain_do_not(self):
        self.assertEqual(judge(1, None, SUP, 0.0, 1.0, 300), EXITED)
        self.assertEqual(judge(0, None, SUP, 0.0, 1.0, 300), EXITED)
        for code in (2, 3, 130):
            self.assertEqual(judge(code, None, SUP, 0.0, 1.0, 300), FINAL)


class RestartLimitTest(unittest.TestCase):
    def test_three_per_hour(self):
        self.assertTrue(may_restart([], 10000.0, S))
        self.assertTrue(may_restart([9000.0, 9500.0], 10000.0, S))
        self.assertFalse(may_restart([7000.0, 9000.0, 9500.0], 10000.0, S))

    def test_old_restarts_expire(self):
        self.assertTrue(may_restart([1000.0, 2000.0, 9500.0], 10000.0, S))


class KillTargetsTest(unittest.TestCase):
    ROWS = [
        (SUP, 100, 'python.exe'),
        (5100, SUP, 'launcher.exe'),
        (5200, 5100, 'waatclient.exe'),     # still logging in: no DLL yet, but started by the supervisor
        (6000, 1, 'waatclient.exe'),        # alt with our DLL (parent launcher gone)
        (6100, 1, 'waatclient.exe'),        # station with our DLL
        (7000, 1, 'waatclient.exe'),        # the user's own window, no DLL
        (8000, 1, 'notepad.exe'),
    ]

    def test_descendants(self):
        self.assertEqual(descendants(self.ROWS, SUP), {5100, 5200})
        self.assertEqual(descendants([(0, 0, 'idle')], 0), set())

    def test_all_ours_never_the_users(self):
        self.assertEqual(kill_targets(self.ROWS, SUP, [6000, 6100], {6100}, True), {5100, 5200, 6000, 6100})

    def test_stations_kept_without_kill_stations(self):
        self.assertEqual(kill_targets(self.ROWS, SUP, [6000, 6100], {6100}, False), {5100, 5200, 6000})

    def test_dll_pid_that_is_not_a_game_is_ignored(self):
        self.assertEqual(kill_targets(self.ROWS, SUP, [8000], set(), True), {5100, 5200})


class LoadGuardTest(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(load_guard({}), S)
        self.assertEqual(load_guard({'guard': {'restart_window_minutes': 30}}).restart_window, 1800.0)

    def test_rejects_stall_shorter_than_heartbeats(self):
        with self.assertRaises(ValueError):
            load_guard({'guard': {'stall_seconds': 15}})
        with self.assertRaises(ValueError):
            load_guard({'guard': {'max_restarts': 0}})

    def test_shipped_supervisor_toml(self):
        from provisioner import config
        g = load_guard(config._read(Path(__file__).resolve().parent.parent / 'supervisor.toml'))
        self.assertEqual((g.stall_seconds, g.max_restarts, g.kill_stations), (300.0, 3, True))


class HeartbeatTest(unittest.TestCase):
    def test_write_read(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'state' / 'hb.json'
            self.assertIsNone(heartbeat.read(path))
            heartbeat.write(path, SUP, 900.0, now=1000.0)
            self.assertEqual(heartbeat.read(path), {'pid': SUP, 'at': 1000.0, 'started': 900.0})
            path.write_text('garbage', encoding='utf-8')
            self.assertIsNone(heartbeat.read(path))

    def test_other_running(self):
        beat = {'pid': SUP, 'at': 1000.0}
        alive = lambda pid: True    # noqa: E731
        self.assertEqual(heartbeat.other_running(beat, 1, 1100.0, alive), SUP)
        self.assertIsNone(heartbeat.other_running(beat, SUP, 1100.0, alive))          # that is me
        self.assertIsNone(heartbeat.other_running(beat, 1, 1100.0, lambda pid: False))  # killed / crashed
        self.assertIsNone(heartbeat.other_running(beat, 1, 1000.0 + heartbeat.OTHER_FRESH, alive))
        self.assertIsNone(heartbeat.other_running(None, 1, 1100.0, alive))


if __name__ == '__main__':
    unittest.main()
