"""Stage B3 mass login failure: verdict, settings, login hook, internet check (factory/outage.py)."""
import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from factory import outage
from factory.outage import OUTAGE, VERSION, LoginLog, OutageSettings, internet_ok, load_outage, verdict
from provisioner import login as login_mod
from provisioner import native

S = OutageSettings()
QUIET = logging.getLogger('test.outage')
QUIET.addHandler(logging.NullHandler())
QUIET.propagate = False


def fail(t, acct, code=1):
    return (t, acct, False, code)


class VerdictTest(unittest.TestCase):
    def test_three_accounts_failing_no_success(self):
        rows = [fail(100, 'mw301'), fail(200, 'mw302'), fail(300, 'mw303')]
        self.assertEqual(verdict(rows, 400, S), OUTAGE)

    def test_same_account_failing_is_not_an_outage(self):
        """A wrong password or a stuck account keeps failing on its own."""
        rows = [fail(100, 'mw301'), fail(200, 'mw301'), fail(300, 'mw301'), fail(310, 'mw302')]
        self.assertIsNone(verdict(rows, 400, S))

    def test_one_success_in_the_window_clears_it(self):
        rows = [fail(100, 'mw301'), fail(200, 'mw302'), (250, 'mw305', True, 0), fail(300, 'mw303')]
        self.assertIsNone(verdict(rows, 400, S))

    def test_old_results_fall_out_of_the_window(self):
        rows = [(0, 'mw305', True, 0), fail(10, 'mw301'), fail(500, 'mw302'), fail(550, 'mw303'), fail(590, 'mw304')]
        self.assertIsNone(verdict(rows, 599, S))           # the success at 0 still counts
        self.assertEqual(verdict(rows, 601, S), OUTAGE)     # it fell out; mw302..304 still in
        self.assertIsNone(verdict(rows, 1200, S))

    def test_version_change_wins_at_once(self):
        rows = [(100, 'mw305', True, 0), fail(110, 'mw301', outage.VERSION_EXIT)]
        self.assertEqual(verdict(rows, 120, S), VERSION)

    def test_empty(self):
        self.assertIsNone(verdict([], 0, S))


class LoadTest(unittest.TestCase):
    def test_defaults_and_off(self):
        self.assertEqual(load_outage({}), S)
        self.assertIsNone(load_outage({'outage': {'enabled': False}}))
        self.assertEqual(load_outage({'outage': {'net_hosts': ['1.2.3.4:80']}}).net_hosts, (('1.2.3.4', 80),))

    def test_bad(self):
        for bad in ({'min_accounts': 1}, {'net_hosts': []}, {'net_hosts': ['nohost']}, {'canary_every_minutes': 0.5}):
            with self.assertRaises(ValueError, msg=bad):
                load_outage({'outage': bad})

    def test_shipped_supervisor_toml(self):
        from provisioner import config
        self.assertEqual(load_outage(config._read(Path(__file__).resolve().parent.parent / 'supervisor.toml')), S)


class LoginLogTest(unittest.TestCase):
    def test_add_rows(self):
        log = LoginLog(keep=2)
        log.add('a', False, 1, now=1.0)
        log.add('b', False, 1, now=2.0)
        log.add('c', True, 0, now=3.0)
        self.assertEqual(log.rows(), [(2.0, 'b', False, 1), (3.0, 'c', True, 0)])


class InternetTest(unittest.TestCase):
    def test_any_host(self):
        seen = []

        def connect(addr, timeout):
            seen.append(addr)
            if addr[0] == 'down':
                raise OSError('no route')
            return SimpleNamespace(close=lambda: None)
        self.assertTrue(internet_ok((('down', 1), ('up', 2)), connect=connect))
        self.assertEqual(seen, [('down', 1), ('up', 2)])
        self.assertFalse(internet_ok((('down', 1),), connect=connect))


class LoginHookTest(unittest.TestCase):
    """provisioner.login.login() reports its final result once, after its retries."""

    def run_login(self, launch):
        got = []
        settings = SimpleNamespace(login_retries=1)
        throttle = SimpleNamespace(launch=lambda log: mock.MagicMock())
        with tempfile.TemporaryDirectory() as d, mock.patch.object(login_mod, 'RESULT_HOOK',
                                                                   lambda *a: got.append(a)), \
                mock.patch.object(native, 'launch', launch), mock.patch.object(login_mod.time, 'sleep'):
            try:
                login_mod.login(settings, SimpleNamespace(name='mw301', password='x'), Path(d), throttle, QUIET)
            except login_mod.LoginFailed as e:
                got.append(('raised', e.code))
        return got

    def test_success(self):
        session = native.Session(1, 2, 3)
        self.assertEqual(self.run_login(lambda *a: session), [('mw301', True, 0)])

    def test_failure_after_retries_reported_once(self):
        def launch(*a):
            raise native.LaunchError('106', {'code': 1, 'pid': None}, True)
        self.assertEqual(self.run_login(launch), [('mw301', False, 1), ('raised', 1)])

    def test_version_mismatch_not_retried(self):
        calls = []

        def launch(*a):
            calls.append(1)
            raise native.LaunchError('sha', {'code': 3}, False)
        self.assertEqual(self.run_login(launch), [('mw301', False, 3), ('raised', 3)])
        self.assertEqual(len(calls), 1)


class SupervisorCheckTest(unittest.TestCase):
    def make(self, guarded):
        import threading
        from factory import supervisor
        sup = object.__new__(supervisor.Supervisor)
        sup.s = SimpleNamespace(outage=S)
        sup.log, sup.stop, sup.guarded, sup.outage_warned = QUIET, threading.Event(), guarded, 0.0
        sup.login_log = LoginLog()
        return sup

    def test_guarded_exits_with_code(self):
        sup = self.make(True)
        self.assertIsNone(sup.check_outage())
        for acct in ('mw301', 'mw302', 'mw303'):
            sup.login_log.add(acct, False, 1)
        self.assertEqual(sup.check_outage(), outage.EXIT_OUTAGE)
        self.assertTrue(sup.stop.is_set())

    def test_version_exit(self):
        sup = self.make(True)
        sup.login_log.add('mw301', False, outage.VERSION_EXIT)
        self.assertEqual(sup.check_outage(), outage.EXIT_VERSION)

    def test_alone_only_warns(self):
        sup = self.make(False)
        for acct in ('mw301', 'mw302', 'mw303'):
            sup.login_log.add(acct, False, 1)
        self.assertIsNone(sup.check_outage())
        self.assertFalse(sup.stop.is_set())


class RealSupervisorTest(unittest.TestCase):
    """2026-10-21: self.logins (this log) was overwritten by the login thread pool of the same name, so every
    check_outage() raised and the supervisor died seconds after start. The tests above build a bare object and
    missed it; this one builds a real Supervisor."""

    def test_check_outage_and_hook_target(self):
        import time as _time
        from tests.test_factory_relogin import WELL1, close, make_sup
        with tempfile.TemporaryDirectory() as tmp:
            sup = make_sup(tmp, [WELL1])
            try:
                sup.s.outage, sup.guarded = S, True
                self.assertIsNone(sup.check_outage())
                for acct in ('mw301', 'mw302', 'mw303'):
                    sup.login_log.add(acct, False, 1, now=_time.time())
                self.assertEqual(sup.check_outage(), outage.EXIT_OUTAGE)
                self.assertTrue(hasattr(sup.logins, 'submit'))      # the login thread pool is still there
            finally:
                close(sup)


if __name__ == '__main__':
    unittest.main()
