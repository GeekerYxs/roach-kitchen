"""line/pool.py: a team that takes its apprentices' accounts from a range (user 2026-11-05, no game)."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'shitu'))

from line import plan, pool  # noqa: E402

NAMES = ['欧花徒01', '欧花徒02', '欧花徒03', '欧花徒04']


class Scan:
    def __init__(self, rosters):
        self.rosters, self.calls = rosters, []

    def __call__(self, accs):
        self.calls.append(list(accs))
        return {a: self.rosters.get(a, []) for a in accs}


class Pool(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        self.files = dict(alloc_file=d / 'alloc.json', roster_file=d / 'rosters.json')

    def alloc(self, team, batch, scan, names=NAMES, spec='mw01-mw20'):
        return pool.allocate(team, batch, spec, names, scan, say=lambda m: None, **self.files)

    def test_expand(self):
        self.assertEqual(pool.expand('mw01-mw03'), ['mw01', 'mw02', 'mw03'])
        self.assertEqual(pool.expand('mw98-mw101')[-1], 'mw101')
        with self.assertRaises(ValueError):
            pool.expand('mw01')

    def test_skips_full_accounts(self):
        scan = Scan({'mw01': ['a', 'b', 'c', 'd'], 'mw02': ['a', 'b'], 'mw04': ['a', 'b', 'c', 'd']})
        self.assertEqual(self.alloc('o', 1, scan), ['mw02', 'mw03', 'mw05', 'mw06'])

    def test_stored_allocation_is_kept(self):
        scan = Scan({})
        first = self.alloc('o', 1, scan)
        calls = len(scan.calls)
        self.assertEqual(self.alloc('o', 1, scan), first)
        self.assertEqual(len(scan.calls), calls)                     # no second login round

    def test_two_teams_never_share(self):
        a = self.alloc('o', 1, Scan({}))
        b = self.alloc('z', 1, Scan({}), names=['自三徒01', '自三徒02', '自三徒03', '自三徒04'])
        self.assertFalse(set(a) & set(b))
        self.assertEqual(b, ['mw05', 'mw06', 'mw07', 'mw08'])

    def test_next_batch_moves_on_then_comes_back(self):
        self.alloc('o', 1, Scan({}))
        self.alloc('z', 1, Scan({}), names=['z1', 'z2', 'z3', 'z4'])
        o2 = self.alloc('o', 2, Scan({}), names=['o5', 'o6', 'o7', 'o8'])
        self.assertEqual(o2, ['mw09', 'mw10', 'mw11', 'mw12'])     # mw01-08 are the teams' latest batches
        z2 = self.alloc('z', 2, Scan({}), names=['z5', 'z6', 'z7', 'z8'])
        self.assertEqual(z2, ['mw01', 'mw02', 'mw03', 'mw04'])     # o's batch 1 is over: its accounts are free again

    def test_cache_counts_planned_roles(self):
        scan = Scan({'mw01': ['a', 'b', 'c']})                      # one slot left
        self.alloc('o', 1, scan)
        self.alloc('z', 1, Scan({}), names=['z1', 'z2', 'z3', 'z4'])
        o2 = self.alloc('o', 2, Scan({'mw01': ['a', 'b', 'c', '欧花徒01']}), names=['o5', 'o6', 'o7', 'o8'])
        self.assertNotIn('mw01', o2)

    def test_login_failure_skips(self):
        class Bad(Scan):
            def __call__(self, accs):
                return {a: ('LoginError' if a == 'mw02' else []) for a in accs}
        self.assertEqual(self.alloc('o', 1, Bad({})), ['mw01', 'mw03', 'mw04', 'mw05'])

    def test_not_enough_accounts(self):
        full = {f'mw{i:02d}': ['a', 'b', 'c', 'd'] for i in range(1, 21)}
        full['mw07'] = ['a']
        with self.assertRaises(RuntimeError):
            self.alloc('o', 1, Scan(full))

    def test_account_holding_the_name_is_not_picked(self):
        scan = Scan({'mw01': ['欧花徒02']})                          # that name is taken there already
        self.assertNotIn('mw01', self.alloc('o', 1, scan))


class PlanPool(unittest.TestCase):
    def test_pairs_use_the_allocation(self):
        team = plan.Team('欧皇丨花花乀', 0, 10000, names='欧花徒', digits=2, pool='mw01-mw20')
        with mock.patch.dict(plan.TEAMS, {'po': team}), \
                mock.patch.object(pool, 'accounts', lambda t, b: ['mw03', 'mw05', 'mw06', 'mw09']):
            b = plan.Batch('po', 2)
            self.assertEqual(b.pairs, ['mw03:欧花徒05', 'mw05:欧花徒06', 'mw06:欧花徒07', 'mw09:欧花徒08'])

    def test_env_marks_pool_teams(self):
        team = plan.Team('欧皇丨花花乀', 0, 10000, names='欧花徒', pool='mw01-mw20')
        with mock.patch.dict(plan.TEAMS, {'po': team}), mock.patch.object(pool, 'accounts', lambda t, b: None),                 mock.patch.object(plan, '_tower2_rows', lambda: []):
            self.assertEqual(plan.Batch('po', 1).env()['SHITU_POOL'], '1')    # make_apprentices skips the slot guard

    def test_unallocated_has_no_pairs(self):
        team = plan.Team('欧皇丨花花乀', 0, 10000, names='欧花徒', pool='mw01-mw20')
        with mock.patch.dict(plan.TEAMS, {'po': team}), mock.patch.object(pool, 'accounts', lambda t, b: None):
            self.assertEqual(plan.Batch('po', 1).pairs, [])

    def test_load_rejects_pool_without_names(self):
        d = Path(tempfile.mkdtemp()) / 'line.toml'
        d.write_text('[team.x]\nmaster = "m"\npool = "mw01-mw20"\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            plan.load_teams(d)
        d.write_text('[team.x]\nmaster = "m"\npool = "mw01-mw20"\nnames = "欧花徒"\n', encoding='utf-8')
        self.assertEqual(plan.load_teams(d)['x'].pool, 'mw01-mw20')


if __name__ == '__main__':
    unittest.main()
