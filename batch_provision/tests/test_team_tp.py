"""team_tp.py (user 2026-11-01): the B+ team takes the 外城传送员 to 无尽2路口 instead of walking map 20."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'shitu'))

import take224 as tk  # noqa: E402
import team_tp  # noqa: E402


class World:
    """Every client of one team on map 20; a teleport by the leader moves the whole team."""
    def __init__(self):
        self.pos, self.teams, self.log = {}, {}, []


class Client:
    def __init__(self, world, name, cid, xy, map_id=20):
        self.W, self.name, self.char_id, self.mem = world, name, cid, None
        world.pos[name] = (map_id, xy)
        self.game = NS(team_leave=self.leave, navigate=lambda m, x, y: world.log.append(('nav', name, (x, y))))

    def leave(self):
        self.W.log.append(('leave', self.name))
        self.W.teams.pop(self.name, None)

    def team(self):
        return self.W.teams.get(self.name, ())

    def world(self):
        m, (x, y) = self.W.pos[self.name]
        return NS(map_id=m, x=x, y=y)


def run_go(cs, talk_ok=True):
    W = cs[0].W

    def walk(c, xy, why):
        W.log.append(('walk', c.name, xy))
        W.pos[c.name] = (20, xy)

    def form(lead, members):
        W.log.append(('team', lead.name))
        ids = (lead.char_id,) + tuple(c.char_id for c in members)
        for c in [lead] + members:
            W.teams[c.name] = ids

    def talk(c, npc, steps):
        W.log.append(('talk', npc, tuple(steps)))
        if talk_ok:
            land = {tk.TP1: tk.TP1_LAND, tk.TP2: tk.TP2_LAND}[npc]
            for o in cs:
                W.pos[o.name] = (20, land)
    with mock.patch.object(team_tp.t, 'Client', lambda n: next(c for c in cs if c.name == n)), \
            mock.patch.object(tk, 'walk', walk), mock.patch.object(tk, 'talk', talk), \
            mock.patch.object(team_tp, 'form_team', form), \
            mock.patch.object(tk.w, 'read_gold', lambda mem: 0), \
            mock.patch.object(team_tp.t, 'say', lambda s: None), \
            mock.patch.object(team_tp.t, 'wait', lambda cond, timeout, what: cond() or
                              (_ for _ in ()).throw(team_tp.t.Stop(what))):
        team_tp.go([c.name for c in cs])
    return W.log


class Go(unittest.TestCase):
    def team(self):
        W = World()
        return [Client(W, 'M', 1, (4050, 303)), Client(W, 'a', 2, (4398, 2553)), Client(W, 'b', 3, (4398, 2553))]

    def test_walk_team_two_hops(self):
        cs = self.team()
        log = run_go(cs)
        self.assertEqual([x for x in log if x[0] == 'walk'][:3], [('walk', n, tk.TP1_XY) for n in 'Mab'])
        talks = [x for x in log if x[0] == 'talk']
        self.assertEqual(talks, [('talk', tk.TP1, (tk.TP1_LABEL,)), ('talk', tk.TP2, ('传送服务', tk.TP2_LABEL))])
        self.assertLess(log.index(('team', 'M')), log.index(talks[0]))
        self.assertIn(('walk', 'M', tk.TP2_XY), log)
        self.assertTrue(all(cs[0].W.pos[c.name] == (20, tk.TP2_LAND) for c in cs))

    def test_no_teleport_is_a_stop(self):
        with self.assertRaises(team_tp.t.Stop):
            run_go(self.team(), talk_ok=False)

    def test_not_on_map_20_is_a_stop(self):
        cs = self.team()
        cs[0].W.pos['M'] = (750, (1590, 3369))
        with self.assertRaises(team_tp.t.Stop):
            run_go(cs)


class Send(unittest.TestCase):
    def test_only_on_map_20(self):
        W = World()
        cs = [Client(W, 'a', 2, (4050, 303)), Client(W, 'b', 3, (1590, 3369), map_id=750)]
        with mock.patch.object(team_tp.t, 'Client', lambda n: next(c for c in cs if c.name == n)), \
                mock.patch.object(team_tp.t, 'say', lambda s: None):
            team_tp.send(['a', 'b'])
        self.assertEqual(W.log, [('nav', 'a', tk.TP1_XY)])


if __name__ == '__main__':
    unittest.main()
