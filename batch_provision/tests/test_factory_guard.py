"""Stage B1 guard: restart decisions (factory/guard.py) and the supervisor heartbeat (factory/heartbeat.py)."""
import logging
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from factory import guard, heartbeat, maintenance, outage
from factory.guard import (EXITED, FINAL, RUN, STALLED, GuardSettings, descendants, judge, kill_targets, load_guard,
                           may_restart, output_low)

SUP = 5000      # supervisor pid
QUIET = logging.getLogger('test.guard')
QUIET.addHandler(logging.NullHandler())
QUIET.propagate = False
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
        self.assertEqual((S.output_floor, S.output_after, S.output_waiting), (10, 5400.0, 4))
        self.assertEqual(load_guard({'guard': {'output_floor_per_hour': 0, 'output_after_minutes': 10}}).output_floor, 0)
        with self.assertRaises(ValueError):
            load_guard({'guard': {'output_after_minutes': 30}})
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
            self.assertEqual(heartbeat.read(path), {'pid': SUP, 'at': 1000.0, 'started': 900.0, 'info': None})
            heartbeat.write(path, SUP, 900.0, now=1000.0, info={'dishes_hour': 3, 'waiting': 6, 'bag_full': False})
            self.assertEqual(heartbeat.read(path)['info']['dishes_hour'], 3)
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


def beat(dishes, waiting, bag_full=False, pid=SUP):
    return {'pid': pid, 'at': 1e18, 'info': {'dishes_hour': dishes, 'waiting': waiting, 'bag_full': bag_full}}


class OutputLowTest(unittest.TestCase):
    T = 10000.0     # the child started at 0: past output_after

    def test_stuck_line(self):
        why = output_low(beat(3, 6), SUP, 0.0, self.T, S)
        self.assertIn('只收到 3 个', why)
        self.assertIn('6 个小号', why)

    def test_ramp_up_is_not_judged(self):
        self.assertIsNone(output_low(beat(0, 20), SUP, 0.0, S.output_after - 1, S))

    def test_enough_output_or_nobody_waiting(self):
        self.assertIsNone(output_low(beat(10, 20), SUP, 0.0, self.T, S))
        self.assertIsNone(output_low(beat(0, 3), SUP, 0.0, self.T, S))       # e.g. right after a wipe

    def test_full_bag_old_beat_no_info_or_off(self):
        self.assertIsNone(output_low(beat(0, 20, bag_full=True), SUP, 0.0, self.T, S))
        self.assertIsNone(output_low(beat(0, 20, pid=4000), SUP, 0.0, self.T, S))
        self.assertIsNone(output_low({'pid': SUP, 'at': 0.0, 'info': None}, SUP, 0.0, self.T, S))
        self.assertIsNone(output_low(None, SUP, 0.0, self.T, S))
        off = GuardSettings(output_floor=0)
        self.assertIsNone(output_low(beat(0, 20), SUP, 0.0, self.T, off))


class FakeClock:
    def __init__(self, start):
        self.t = start

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += timedelta(seconds=seconds)


class GuardLoop:
    """Runs the guard's loop with the supervisor, kills, logins and network faked on a fake clock."""

    def run_guard(self, start, canary_results, exits=(), net=(), outage_s=None, final_code=2, beat_fn=None):
        """exits: exit code the supervisor returns on its Nth start (None = runs until the end); after all of them
        it exits final_code. canary_results: (ok, version) per canary. net: internet_ok() answers, then True."""
        clock = FakeClock(start)
        events = []
        maint = maintenance.MaintSettings(weekly=(maintenance.parse_weekly('thu 10:00-12:00'),))
        tries, nets, starts = iter(canary_results), iter(net), iter(exits)

        def canary(i):
            ok, version = next(tries)
            events.append(('canary', clock.t.strftime('%H:%M'), ok))
            return ok, 'mw301', version

        def net_ok():
            up = next(nets, True)
            events.append(('net', clock.t.strftime('%H:%M'), up))
            return up

        g = guard.Guard(Path('x'), GuardSettings(check_every=60), ':memory:', QUIET, maint, canary, clock.now,
                        outage_s=outage_s, net_ok=net_ok)

        def start():
            events.append(('start', clock.t.strftime('%H:%M')))
            code = next(starts, final_code)
            polls = iter([None] * 3 if code is not None else [None] * 300)
            g.child = SimpleNamespace(pid=SUP, poll=lambda: next(polls, code if code is not None else final_code))
            g.started = 0.0

        def kill_all(kill_stations=None):
            events.append(('kill', clock.t.strftime('%H:%M')))
            g.child = None

        drains = []
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(maintenance, 'DRAIN_PATH', Path(d) / 'drain.json'), \
                mock.patch.object(heartbeat, 'read', beat_fn or (lambda path: {'pid': SUP, 'at': 1e18})), \
                mock.patch.object(guard.time, 'sleep', clock.sleep), \
                mock.patch.object(g, 'start', start), mock.patch.object(g, 'kill_all', kill_all):
            real_drain = g.drain
            g.drain = lambda win, reason: (drains.append(clock.t.strftime('%H:%M')), real_drain(win, reason))
            code = g.run()
            self.assertFalse((Path(d) / 'drain.json').exists())
        return code, events, drains


class MaintenanceRunTest(GuardLoop, unittest.TestCase):
    """The guard's loop around a Thursday window."""

    def test_started_inside_the_window_waits_then_canary(self):
        code, events, _ = self.run_guard(datetime(2026, 10, 22, 11, 0), [(False, False), (True, False)])
        self.assertEqual(code, 2)
        self.assertEqual(events[:4], [('kill', '11:00'), ('canary', '12:00', False), ('canary', '12:20', True),
                                      ('start', '12:20')])

    def test_running_line_drains_then_closes(self):
        code, events, drains = self.run_guard(datetime(2026, 10, 22, 9, 45), [(True, False)], exits=[None])
        self.assertEqual(events[:4], [('start', '09:45'), ('kill', '09:55'), ('canary', '12:00', True),
                                      ('start', '12:00')])
        self.assertEqual(drains[0], '09:50')

    def test_version_changed_after_maintenance_stops(self):
        code, events, _ = self.run_guard(datetime(2026, 10, 22, 11, 0), [(False, True)])
        self.assertEqual(code, outage.EXIT_VERSION)
        self.assertEqual(events[-1], ('canary', '12:00', False))


class OutageRunTest(GuardLoop, unittest.TestCase):
    """The supervisor exits 4 (mass login failure) on a Tuesday afternoon."""
    TUE = datetime(2026, 10, 20, 15, 0)

    def test_server_down_waits_an_hour_then_canary(self):
        code, events, _ = self.run_guard(self.TUE, [(False, False), (True, False)], exits=[outage.EXIT_OUTAGE],
                                         outage_s=outage.OutageSettings())
        self.assertEqual(code, 2)
        e = [x for x in events if x[0] != 'net']
        self.assertEqual(e[:5], [('start', '15:00'), ('kill', '15:04'), ('canary', '16:04', False),
                                 ('canary', '16:24', True), ('start', '16:24')])

    def test_pc_offline_checks_every_5_min_and_tries_at_once(self):
        code, events, _ = self.run_guard(self.TUE, [(True, False)], exits=[outage.EXIT_OUTAGE], net=[False, False],
                                         outage_s=outage.OutageSettings())
        self.assertEqual(events[:7], [('start', '15:00'), ('kill', '15:04'), ('net', '15:04', False),
                                      ('net', '15:09', False), ('net', '15:14', True), ('canary', '15:14', True),
                                      ('start', '15:14')])

    def test_version_exit_stops_the_guard(self):
        code, events, _ = self.run_guard(self.TUE, [], exits=[outage.EXIT_VERSION], outage_s=outage.OutageSettings())
        self.assertEqual(code, outage.EXIT_VERSION)
        self.assertEqual(events, [('start', '15:00'), ('kill', '15:04')])

    def test_low_output_restarts_once(self):
        reads = iter([beat(2, 8)])

        def beat_fn(path):
            return next(reads, {'pid': SUP, 'at': 1e18, 'info': None})
        code, events, _ = self.run_guard(self.TUE, [], exits=[None], beat_fn=beat_fn)
        self.assertEqual(code, 2)
        self.assertEqual(events[:3], [('start', '15:00'), ('kill', '15:01'), ('start', '15:01')])

    def test_low_output_ignored_while_draining(self):
        reads = iter([beat(2, 8)] * 5)

        def beat_fn(path):
            return next(reads, {'pid': SUP, 'at': 1e18, 'info': None})
        code, events, _ = self.run_guard(datetime(2026, 10, 22, 9, 50), [(True, False)], exits=[None],
                                         beat_fn=beat_fn)
        self.assertEqual(events[:2], [('start', '09:50'), ('kill', '09:55')])     # maintenance, not output

    def test_enter_failures_right_after_maintenance_stop_as_version_change(self):
        """2026-10-22 replay: canary login fine at 12:00, then nobody can enter -> stop, do not loop."""
        code, events, _ = self.run_guard(datetime(2026, 10, 22, 11, 0), [(True, False)], exits=[outage.EXIT_ENTER],
                                         outage_s=outage.OutageSettings())
        self.assertEqual(code, outage.EXIT_ENTER)
        self.assertEqual(events, [('kill', '11:00'), ('canary', '12:00', True), ('start', '12:00'), ('kill', '12:04')])

    def test_enter_failures_on_an_ordinary_day_wait_like_an_outage(self):
        code, events, _ = self.run_guard(self.TUE, [(True, False)], exits=[outage.EXIT_ENTER],
                                         outage_s=outage.OutageSettings())
        self.assertEqual(code, 2)
        e = [x for x in events if x[0] != 'net']
        self.assertEqual(e[:4], [('start', '15:00'), ('kill', '15:04'), ('canary', '16:04', True), ('start', '16:04')])

    def test_maintenance_takes_over_an_outage_wait(self):
        thu = datetime(2026, 10, 22, 9, 30)
        code, events, _ = self.run_guard(thu, [(True, False)], exits=[outage.EXIT_OUTAGE],
                                         outage_s=outage.OutageSettings())
        e = [x for x in events if x[0] != 'net']
        self.assertEqual(e[:5], [('start', '09:30'), ('kill', '09:34'), ('kill', '09:55'), ('canary', '12:00', True),
                                 ('start', '12:00')])


if __name__ == '__main__':
    unittest.main()
