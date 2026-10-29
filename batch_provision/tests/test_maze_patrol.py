"""maze_train.Route.patrol: an A point that can never be reached from B is replaced by where the leader got stuck
(2026-10-29 八阵图, 伏地魔3 wedged 20 times at (912,1984) on the way back to the landing point)."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'shitu'))

import maze_train as m  # noqa: E402


class Patrol(unittest.TestCase):
    def route(self):
        r = m.Route(dict(name='八阵图', maze=700, legs={}, patrol_b=(1200, 1800)))
        r.say = lambda msg: None
        r.walk = lambda *a: None
        r.points, r.target, r.probes = [(784, 2272), (1200, 1800)], 0, []
        return r

    def stuck(self, r, xy=(912, 1984)):
        r.stalls = 2
        r.patrol(None, NS(x=xy[0], y=xy[1], moving=False), 0)

    def test_a_replaced_after_three_failed_trips(self):
        r = self.route()
        for _ in range(2):
            self.stuck(r)                       # flip to B
            self.assertEqual(r.target, 1)
            r.patrol(None, NS(x=1200, y=1800, moving=False), 0)    # reaches B: flips reset, A failures do not
            self.assertEqual(r.target, 0)
        self.stuck(r)
        self.assertEqual(r.points[0], (912, 1984))
        self.assertEqual(r.target, 1)

    def test_reaching_a_resets_the_count(self):
        r = self.route()
        self.stuck(r)
        r.patrol(None, NS(x=1200, y=1800, moving=False), 0)
        r.patrol(None, NS(x=784, y=2272, moving=False), 0)         # A reached after all
        self.assertEqual(r.a_fails, 0)
        self.assertEqual(r.points[0], (784, 2272))


if __name__ == '__main__':
    unittest.main()


class Unstick(unittest.TestCase):
    """Every 5th stall at one spot the leader first steps aside (2026-10-29 古迹 (3840,2944), round 4's spot too)."""
    def test_side_step_every_fifth_stall(self):
        r = m.Route(dict(name='古迹', maze=650, legs={}, patrol_b=None))
        r.say = lambda msg: None
        navs = []
        lead = NS(game=NS(navigate=lambda *a: navs.append(a), cancel_navigation=lambda: None))
        st = NS(x=3840, y=2944, map_id=650, nav_active=False, moving=False)
        now = 0.0
        r.walk(lead, st, 650, (1428, 924), now, 'x')            # first call: starts the progress clock, paths once
        navs.clear()
        for _ in range(5):
            now += m.STALL + 1
            r.walk(lead, st, 650, (1428, 924), now, 'x')
        self.assertEqual(r.wedged, 5)
        self.assertEqual(navs[-1], (650, 3840 + m.UNSTICK[0][0], 2944 + m.UNSTICK[0][1]))
        r.walk(lead, st, 650, (1428, 924), now + 1, 'x')        # the side walk runs: no pathing to the goal yet
        self.assertEqual(len(navs), 1)
