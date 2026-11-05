"""2026-11-05 live (欧皇 team, apprentices at 20): after a relog the recovery scrolled everybody to 逍遥村 and the maze
step failed with 「在意外的地图 1」 on every retry -> 停摆. lunhui15 / maze_train only know the way from 平静海岸2区 on,
so the route rides the PP鸡 there first (PP_COAST), and the 八阵图 stage knows the way from 81 / 555 too."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'shitu'))

from line import route as R  # noqa: E402


class Route(unittest.TestCase):
    def test_lunhui_and_maze_ride_to_the_coast_from_home(self):
        for route in (R.ROUTE, R.ROUTE_BPLUS, R.ROUTE_YUANSU):
            steps = {s.name: s for s in route}
            for name, script in (('lunhui', 'lunhui15.py'), ('maze', 'maze_train.py')):
                cmds = steps[name].cmds
                i = next(k for k, c in enumerate(cmds) if c.args[0] == script)
                self.assertGreater(i, 0, name)
                pp = cmds[i - 1]
                self.assertEqual((pp.args, pp.when), (('pp_chain.py', '平静海岸2区'), 'master_on 1'), name)


class MazeLegs(unittest.TestCase):
    def test_bazhen_stage_knows_81_and_555(self):
        import maze_train
        bz = next(s for s in maze_train.STAGES if s['name'] == '八阵图')
        self.assertEqual(bz['legs'][81][:2], ('walk', 82))
        self.assertEqual(bz['legs'][555][:2], ('click', 10157))
        for m in (600, 82, 140):
            self.assertIn(m, bz['legs'])
        mc = next(s for s in maze_train.STAGES if s['name'] == '暗影迷城')
        for m in (555, 81, 82):
            self.assertIn(m, mc['legs'])


if __name__ == '__main__':
    unittest.main()
