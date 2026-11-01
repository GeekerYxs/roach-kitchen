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
    def test_nobody_walks_form_team_invites_in_place(self):
        """user 2026-11-01: invite where they stand (form_team -> invite_near), the leader walks to the far ones."""
        log = []
        lead = NS(name='M', char_id=1, team=lambda: (), dialog=lambda: None)
        cs = [NS(name=n, char_id=i, dialog=lambda: None) for n, i in (('a', 10), ('b', 11))]
        with mock.patch.object(teamwalk, 'step_to', lambda *a, **k: log.append('walk')), \
                mock.patch('well10.form_team', lambda l, ms: log.append(('form', l.name, [c.name for c in ms]))):
            teamwalk.regroup_all(lead, cs)
        self.assertEqual(log, [('form', 'M', ['a', 'b'])])

    def test_all_in_nothing_to_do(self):
        lead = NS(name='M', char_id=1, team=lambda: (1, 10))
        with mock.patch('well10.form_team', lambda l, ms: self.fail('no regroup needed')):
            teamwalk.regroup_all(lead, [NS(name='a', char_id=10)])


class ClickHere(unittest.TestCase):
    def client(self, xy, map_id=280, dialog=True):
        clicks = []
        c = NS(name='a', world=lambda: NS(map_id=map_id, x=xy[0], y=xy[1]),
               dialog=lambda: ('dlg' if dialog and clicks else None),
               game=NS(click_npc=lambda npc: clicks.append(npc)))
        return c, clicks

    def run_here(self, c, xy=(1000, 1000), map_id=None):
        with mock.patch.object(teamwalk.t, 'wait', lambda cond, timeout, what: cond() or
                               (_ for _ in ()).throw(teamwalk.t.Stop(what))), mock.patch.object(teamwalk, 'MAP', 280):
            return teamwalk.click_here(c, 954, xy, map_id)

    def test_close_enough_clicks_in_place(self):
        c, clicks = self.client((1200, 1000))
        self.assertEqual(self.run_here(c), 'dlg')
        self.assertEqual(clicks, [954])

    def test_too_far_or_other_map_does_not_try(self):
        for xy, m in (((1400, 1000), 280), ((1000, 1000), 20)):
            c, clicks = self.client(xy, map_id=m)
            self.assertIsNone(self.run_here(c))
            self.assertEqual(clicks, [])

    def test_no_dialog_is_none(self):
        c, clicks = self.client((1000, 1000), dialog=False)
        self.assertIsNone(self.run_here(c))
        self.assertEqual(clicks, [954])

    def test_map_given(self):
        c, clicks = self.client((1000, 1000), map_id=20)
        self.assertEqual(self.run_here(c, map_id=20), 'dlg')

    def test_scripts_try_in_place_before_walking(self):
        for name, walk in (('dew_team.py', 'step_to(c, xy)'), ('scorpion_water.py', 'd.step_to(c, xy)'),
                           ('team_npc.py', 'd.step_to(c, xy, near=80)'), ('talk_chain.py', 'walk(c, map_id, xy')):
            src = (HERE / name).read_text(encoding='utf-8')
            self.assertIn('click_here(', src, name)
            self.assertLess(src.index('click_here('), src.index(walk), name)


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
