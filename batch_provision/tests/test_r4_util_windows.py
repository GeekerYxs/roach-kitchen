"""r4_util.windows self-heal: an offline apprentice (window up, no world) is closed by pid without building a
trial_run.Client, whose char_id read crashed on it (2026-10-31 Gemini night run, 亿万A4: AttributeError 11 times,
team parked). Plus login() creating runtime/ in a fresh clone."""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'shitu'))

import r4_util  # noqa: E402
from provisioner import login as login_mod, native  # noqa: E402


def no_client(name):
    raise AssertionError(f'Client({name}) must not be built for an offline role')


class Windows(unittest.TestCase):
    def run_windows(self, has_dll):
        found = {'M': (1, 'm'), 'a': (2, 'a'), 'b': (3, 'b')}
        closed, killed, runs = [], [], []
        armed = {}
        with mock.patch.object(r4_util, 'MASTERS', ('M',)), \
                mock.patch.object(r4_util, 'APPRENTICES', ('a', 'b')), \
                mock.patch('common.find_roles', lambda names: {n: found[n] for n in names if n in found}), \
                mock.patch.object(r4_util, 'offline', lambda n: n == 'b'), \
                mock.patch.object(r4_util, 'keep_tap', lambda n, pid: None), \
                mock.patch.object(r4_util.t, 'Client', lambda n: NS(pid=found[n][0]) if runs else no_client(n)), \
                mock.patch.object(native, 'arm', lambda s: armed.update({s.pid: True})), \
                mock.patch.object(r4_util.t, 'say', lambda s: None), \
                mock.patch.object(r4_util.time, 'sleep', lambda s: None), \
                mock.patch.object(native, 'has_dll', lambda pid: has_dll), \
                mock.patch.object(native, 'read_status', lambda pid: {'hwnd': 9, 'game_base': 8}), \
                mock.patch.object(native, 'close', lambda s: closed.append(s.pid) or 'closed'), \
                mock.patch.object(native, 'kill', lambda pid: killed.append(pid) or True), \
                mock.patch('subprocess.run', lambda cmd, check: runs.append(cmd)):
            r4_util.windows(['cap1:a', 'cap2:b'])         # Client only after the relogin, for the fresh window
        return closed, killed, runs

    def test_offline_closed_by_pid(self):
        closed, killed, runs = self.run_windows(has_dll=True)
        self.assertEqual(closed, [3])
        self.assertEqual(killed, [])
        self.assertEqual(runs[0][-1:], ['cap2:b'])            # only the offline one is logged in again

    def test_no_dll_is_killed(self):
        closed, killed, runs = self.run_windows(has_dll=False)
        self.assertEqual(closed, [])
        self.assertEqual(killed, [3])
        self.assertEqual(runs[0][-1:], ['cap2:b'])


class LoginRuntime(unittest.TestCase):
    def test_creates_runtime(self):
        with tempfile.TemporaryDirectory() as d:
            runtime = Path(d) / 'runtime'
            seen = []

            def launch(settings, account, result_file, log):
                seen.append(result_file.parent.is_dir())
                return NS(pid=1, hwnd=2, base=3)

            throttle = NS(launch=lambda log: mock.MagicMock())
            log = mock.MagicMock()
            with mock.patch.object(native, 'launch', launch):
                login_mod.login(NS(login_retries=0), NS(name='cap1'), runtime, throttle, log)
            self.assertEqual(seen, [True])


if __name__ == '__main__':
    unittest.main()
