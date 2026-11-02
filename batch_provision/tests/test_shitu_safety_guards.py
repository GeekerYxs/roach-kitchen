"""Offline regression checks for the 1102 shitu safety guards."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SHITU = ROOT / 'research' / 'shitu'
sys.path.insert(0, str(SHITU))

import r4_util  # noqa: E402
from line import ops  # noqa: E402


class BagCapacityGuard(unittest.TestCase):
    def test_unreadable_capacity_stops_before_dropping(self):
        c = NS(name='apprentice', mem=object(), world=lambda: NS(moving=False, busy=False))
        import quanshou

        with mock.patch.object(r4_util.w, 'read_bag_capacity', return_value=None), \
                mock.patch.object(r4_util.w, 'read_bag', return_value=[]), \
                mock.patch.object(r4_util.t, 'wait', lambda *a, **k: None), \
                mock.patch.object(quanshou, 'flee', lambda *a, **k: None):
            with self.assertRaisesRegex(r4_util.t.Stop, '背包容量不可读'):
                r4_util.space_one(c, 2)


class FinalGatherRecheck(unittest.TestCase):
    def test_fifth_dark_gather_can_supply_last_stone(self):
        state = {'stones': 0, 'dark_runs': 0}
        c = NS(mem=object())

        def run(cmd, check):
            if 'dark' in cmd:
                state['dark_runs'] += 1
                if state['dark_runs'] == 5:
                    state['stones'] = 3

        with mock.patch.object(ops, 'M', 'master'), \
                mock.patch.object(ops.t, 'Client', return_value=c), \
                mock.patch.object(ops.w, 'read_bag', return_value=[]), \
                mock.patch.object(ops.w, 'item_count', side_effect=lambda bag, item: state['stones']), \
                mock.patch.object(ops.subprocess, 'run', side_effect=run), \
                mock.patch.object(ops.t, 'say'):
            ops.gather()

        self.assertEqual(state['dark_runs'], 5)
        self.assertEqual(state['stones'], 3)


if __name__ == '__main__':
    unittest.main()
