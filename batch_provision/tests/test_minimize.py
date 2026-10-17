"""Unit tests for keeping the tool's game windows minimized (no game or window needed)."""
import threading
import unittest
from unittest import mock

from provisioner import minimize
from provisioner.config import merge_local
from provisioner.minimize import Minimizer, Win, pick


class Pick(unittest.TestCase):
    def test_only_our_windows_not_yet_minimized(self):
        wins = [Win(10, 1, False), Win(10, 2, True), Win(20, 3, False), Win(30, 4, False)]
        self.assertEqual(pick(wins, {10, 30}), [Win(10, 1, False), Win(30, 4, False)])

    def test_user_window_is_never_picked(self):
        self.assertEqual(pick([Win(16276, 9, False)], set()), [])

    def test_a_window_restored_by_the_user_stays_open(self):
        self.assertEqual(pick([Win(10, 1, False), Win(10, 2, False)], {10}, done={1}), [Win(10, 2, False)])

    def test_station_windows_are_skipped(self):
        self.assertEqual(pick([Win(10, 1, False), Win(20, 2, False)], {10, 20}, skip={20}), [Win(10, 1, False)])


class Switch(unittest.TestCase):
    def test_local_toml_batch_turns_it_on_for_every_tool(self):
        merged = merge_local({'batch': {'minimize': False, 'launch_interval': 2.0}}, {'batch': {'minimize': True}})
        self.assertEqual(merged['batch'], {'minimize': True, 'launch_interval': 2.0})


class Loop(unittest.TestCase):
    def _run(self, passes, skip=None):
        log, stop = mock.Mock(), threading.Event()
        self.args = []
        calls = iter(passes)

        def fake(done, skip):
            self.args.append((set(done), skip))
            p = next(calls, None)
            if p is None:
                stop.set()
                return []
            if isinstance(p, Exception):
                raise p
            return p

        with mock.patch.object(minimize, 'minimize_ours', fake):
            Minimizer(log, stop, every=0, skip=skip).start().thread.join(2)
        return log

    def test_logs_each_process_once(self):
        log = self._run([[Win(10, 1, False)], [Win(10, 1, False), Win(20, 2, False)]])
        pids = [c.args[1] for c in log.info.call_args_list if c.args[0].startswith('最小化游戏窗口')]
        self.assertEqual(pids, [10, 20])

    def test_each_window_minimized_once_and_skip_read_every_pass(self):
        self._run([[Win(10, 1, False)], [Win(20, 2, False)], []], skip=lambda: {30})
        self.assertEqual(self.args, [(set(), {30}), ({1}, {30}), ({1, 2}, {30}), ({1, 2}, {30})])

    def test_an_error_does_not_stop_the_loop(self):
        log = self._run([OSError('x'), [Win(10, 1, False)]])
        self.assertEqual(log.warning.call_count, 1)
        self.assertTrue(any(c.args[0].startswith('最小化游戏窗口') for c in log.info.call_args_list))


if __name__ == '__main__':
    unittest.main()
