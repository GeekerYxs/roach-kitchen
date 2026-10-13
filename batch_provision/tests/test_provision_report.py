"""Role-creation report: every incomplete account must be listed with what is missing and why."""
import tempfile
import unittest
from pathlib import Path

from provisioner.__main__ import failure_rows, write_report

OK = {'account': 'mw140', 'ok': True, 'roles': {f'mw140r{i}': 'created' for i in range(1, 5)}}
MW141 = {'account': 'mw141', 'ok': False, 'step': None, 'error': '部分角色未建成，详见日志',
         'roles': {'mw141r1': 'failed', 'mw141r2': 'created', 'mw141r3': 'created', 'mw141r4': 'created'}}
LOGIN_FAIL = {'account': 'mw142', 'ok': False, 'step': '登录', 'error': 'LoginFailed: 登录失败',
              'roles': {f'mw142r{i}': None for i in range(1, 5)}}
DETAILS = {'mw141': {'mw141r1': {'status': 'failed', 'server_result': 1, 'reason': '服务器未就绪'}}}


class Report(unittest.TestCase):
    def test_only_incomplete_accounts_listed(self):
        rows = failure_rows([OK, MW141, LOGIN_FAIL], DETAILS)
        self.assertEqual([r['account'] for r in rows], ['mw141', 'mw142'])

    def test_missing_role_shows_reason(self):
        row = failure_rows([MW141], DETAILS)[0]
        self.assertEqual((row['done'], row['total']), (3, 4))
        self.assertIn('mw141r1 被拒绝：服务器未就绪', row['missing'])

    def test_login_failure_shows_step(self):
        row = failure_rows([LOGIN_FAIL], {})[0]
        self.assertEqual((row['done'], row['step']), (0, '登录'))
        self.assertIn('mw142r1 没尝试', row['missing'])

    def test_report_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'r.md'
            write_report(path, [OK, MW141], DETAILS, 12.0)
            text = path.read_text('utf-8')
        self.assertIn('完整 1，未完成 1', text)
        self.assertIn('|mw141|3/4|', text)


if __name__ == '__main__':
    unittest.main()
