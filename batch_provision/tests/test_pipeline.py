"""The pipeline must never close a process it did not start."""
import logging
import unittest
from unittest import mock

from provisioner import native
from provisioner.pipeline import OwnWindows

LOG = logging.getLogger('test')
LOG.addHandler(logging.NullHandler())


class OwnWindowsTest(unittest.TestCase):
    def setUp(self):
        self.own = OwnWindows(8, LOG)
        self.mine = native.Session(pid=100, hwnd=0xAAA, base=0x400000)

    def close(self, session, alive=True, status_hwnd=0xAAA):
        with mock.patch.object(native, 'kill') as kill, \
                mock.patch.object(native, 'alive', return_value=alive), \
                mock.patch.object(native, 'read_status', return_value={'hwnd': status_hwnd}):
            self.own.close(session, LOG)
        return kill

    def test_foreign_pid_is_never_killed(self):
        self.own.add(self.mine)
        kill = self.close(native.Session(pid=200, hwnd=0xBBB, base=0x400000))
        kill.assert_not_called()

    def test_same_pid_different_window_is_never_killed(self):
        self.own.add(self.mine)
        kill = self.close(native.Session(pid=100, hwnd=0xBBB, base=0x400000))
        kill.assert_not_called()

    def test_pid_reused_by_other_process_is_never_killed(self):
        self.own.add(self.mine)
        kill = self.close(self.mine, status_hwnd=0xCCC)
        kill.assert_not_called()

    def test_own_window_is_closed_and_released(self):
        self.own.add(self.mine)
        kill = self.close(self.mine)
        kill.assert_called_once_with(100)
        self.assertEqual(self.own.count(), 0)

    def test_already_exited_is_just_released(self):
        self.own.add(self.mine)
        kill = self.close(self.mine, alive=False)
        kill.assert_not_called()
        self.assertEqual(self.own.count(), 0)


if __name__ == '__main__':
    unittest.main()
