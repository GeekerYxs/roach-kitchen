"""mail_sell.tap_pids: a relogged apprentice's older windows are read too (2026-10-29 亿万60: 0 of 33 mails)."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'shitu'))

import mail_sell  # noqa: E402


class TapPids(unittest.TestCase):
    def test_current_first_then_old(self):
        state = {'亿万60': {'tap_62848': {'pid': 62848}, 'tap_82184': {}, 'supply_gold': {}, 'tap_x': {}}}
        with mock.patch('bai_shi.load_state', lambda: state):
            self.assertEqual(mail_sell.tap_pids(NS(name='亿万60', pid=82184)), [82184, 62848])
            self.assertEqual(mail_sell.tap_pids(NS(name='亿万59', pid=5)), [5])


if __name__ == '__main__':
    unittest.main()
