"""teamwalk.leave_all / each / regroup_all and their use in dew_team / scorpion_water (user 2026-11-01: the members
left, gathered / placed and re-joined one by one at every 通天花 / 水源, minutes per batch)."""
import ast
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

HERE = Path(__file__).resolve().parent.parent / 'research' / 'shitu'
sys.path.insert(0, str(HERE))

import teamwalk  # noqa: E402


class Each(unittest.TestCase):
    def test_runs_at_the_same_time(self):
        cs = [NS(name=n) for n in 'abcd']
        live, peak, lock = [0], [0], threading.Lock()

        def fn(c):
            with lock:
                live[0] += 1
                peak[0] = max(peak[0], live[0])
            time.sleep(0.2)
            with lock:
                live[0] -= 1
            return c.name.upper()
        start = time.monotonic()
        self.assertEqual(teamwalk.each(fn, cs), {'a': 'A', 'b': 'B', 'c': 'C', 'd': 'D'})
        self.assertLess(time.monotonic() - start, 0.6)
        self.assertEqual(peak[0], 4)

    def test_stop_is_a_result_other_errors_raise(self):
        def fn(c):
            if c.name == 'a':
                raise teamwalk.t.Stop('no dialog')
            if c.name == 'x':
                raise ValueError('bug')
            return 1
        out = teamwalk.each(fn, [NS(name='a'), NS(name='b')])
        self.assertIsInstance(out['a'], teamwalk.t.Stop)
        self.assertEqual(out['b'], 1)
        with self.assertRaises(ValueError):
            teamwalk.each(fn, [NS(name='x'), NS(name='b')])


class LeaveAll(unittest.TestCase):
    def test_all_leaves_before_waiting(self):
        log = []

        class C:
            def __init__(self, n):
                self.name, self.t = n, (1, 2)
                self.game = NS(team_leave=lambda: log.append(('leave', n)) or setattr(self, 't', ()))

            def team(self):
                log.append(('check', self.name))
                return self.t
        cs = [C('a'), C('b')]
        with mock.patch.object(teamwalk.t, 'wait', lambda cond, timeout, what: cond()):
            teamwalk.leave_all(cs)
        leaves = [i for i, x in enumerate(log) if x[0] == 'leave']
        self.assertEqual(len(leaves), 2)
        self.assertEqual(leaves, sorted(leaves)[:2])
        self.assertTrue(all(c.t == () for c in cs))


class RegroupAll(unittest.TestCase):
    def test_walk_together_invite_together_then_fallback(self):
        log = []
        lead = NS(name='M', char_id=1, team=lambda: (1, 10) if log.count('invite') else (), dialog=lambda: None,
                  world=lambda: NS(x=100, y=100))
        cs = [NS(name=n, char_id=i, dialog=lambda: None) for n, i in (('a', 10), ('b', 11))]
        with mock.patch.object(teamwalk, 'step_to', lambda c, xy, near: log.append(('walk', c.name, xy))), \
                mock.patch('well10.invite_near', lambda l, out: log.append('invite')), \
                mock.patch.object(teamwalk, 'regroup', lambda l, ms: log.append('regroup')):
            teamwalk.regroup_all(lead, cs)
        self.assertEqual(sorted(log[:2]), [('walk', 'a', (100, 100)), ('walk', 'b', (100, 100))])
        self.assertEqual(log[2:], ['invite', 'regroup'])


class Scripts(unittest.TestCase):
    def calls(self, name):
        tree = ast.parse((HERE / name).read_text(encoding='utf-8'))
        return {n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, 'id', None)
                for n in ast.walk(tree) if isinstance(n, ast.Call)}

    def test_dew_and_water_use_the_parallel_helpers(self):
        for name in ('dew_team.py', 'scorpion_water.py'):
            c = self.calls(name)
            self.assertTrue({'leave_all', 'each', 'regroup_all'} <= c, name)
            self.assertNotIn('regroup', c, name)
            self.assertNotIn('team_leave', c, name)


if __name__ == '__main__':
    unittest.main()
