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


class FightOut(unittest.TestCase):
    def test_casts_until_the_battle_ends(self):
        left = [3]

        def world():
            return NS(in_battle=left[0] > 0)
        ticks = []

        def tick(now):
            ticks.append(now)
            left[0] -= 1
        lead = NS(name='M', world=world)
        with mock.patch.object(teamwalk.t, 'say', lambda s: None), mock.patch.object(teamwalk.time, 'sleep', lambda s: None):
            teamwalk.fight_out(lead, NS(tick=tick))
        self.assertEqual(len(ticks), 3)

    def test_no_battle_no_caster(self):
        lead = NS(name='M', world=lambda: NS(in_battle=False))
        teamwalk.fight_out(lead)          # would build lunhui15.Caster (game memory) if it went on

    def test_timeout(self):
        lead = NS(name='M', world=lambda: NS(in_battle=True))
        with mock.patch.object(teamwalk.t, 'say', lambda s: None), mock.patch.object(teamwalk.time, 'sleep', lambda s: None):
            with self.assertRaises(teamwalk.t.Stop):
                teamwalk.fight_out(lead, NS(tick=lambda now: None), timeout=0)


class Scripts(unittest.TestCase):
    def calls(self, name):
        tree = ast.parse((HERE / name).read_text(encoding='utf-8'))
        return {n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, 'id', None)
                for n in ast.walk(tree) if isinstance(n, ast.Call)}

    def test_dew_and_water_use_the_parallel_helpers(self):
        for name in ('dew_team.py', 'scorpion_water.py'):
            c = self.calls(name)
            self.assertTrue({'fight_out', 'leave_all', 'each', 'regroup_all'} <= c, name)
            self.assertNotIn('regroup', c, name)
            self.assertNotIn('team_leave', c, name)

    def test_team_npc_fights_out_then_talks_at_once(self):
        c = self.calls('team_npc.py')
        self.assertTrue({'fight_out', 'leave_all', 'each'} <= c)
        self.assertNotIn('team_leave', c)
        src = (HERE / 'team_npc.py').read_text(encoding='utf-8')
        self.assertLess(src.index('d.fight_out(lead)'), src.index('d.leave_all(apps)'))

    def test_team_npc_main_collects_stops(self):
        import team_npc
        lead, apps = NS(name='M'), [NS(name='a'), NS(name='b')]
        calls = []

        def talk(c, *a):
            calls.append(c.name)
            if c.name == 'b' and calls.count('b') == 1:
                raise team_npc.t.Stop('no dialog')
        clients = {'M': lead, 'a': apps[0], 'b': apps[1]}
        with mock.patch.object(team_npc.t, 'Client', lambda n: clients[n]), \
                mock.patch.object(team_npc, 'talk', talk), \
                mock.patch.object(team_npc.d, 'fight_out', lambda l: calls.append('fight')), \
                mock.patch.object(team_npc.d, 'leave_all', lambda cs: calls.append('leave')), \
                mock.patch.object(team_npc.t, 'say', lambda s: None), \
                mock.patch.object(team_npc.time, 'sleep', lambda s: None), \
                mock.patch.dict(team_npc.os.environ, {'PAIRS': ''}):
            team_npc.main(650, 986, (2542, 3442), '水晶', 181, 'M', ['a', 'b'], regroup=False)
        self.assertEqual(calls[:2], ['fight', 'leave'])
        self.assertEqual(sorted(calls[2:4]), ['a', 'b'])
        self.assertEqual(calls[4:], ['b'])          # only the one without a dialog goes again


if __name__ == '__main__':
    unittest.main()
