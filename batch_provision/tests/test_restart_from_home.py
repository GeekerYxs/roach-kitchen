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


# scripts that walk the team from a map they expect (maze_train / lunhui15 loops, team talks in a field or town)
WALKERS = {'lunhui15.py', 'maze_train.py', 'go_goal.py', 'go_cave.py', 'desert_go.py', 'ruin_go.py', 'quan100.py',
           'back_longeer.py', 'bazhen25.py', 'tower28.py', 'cave_train.py', 'tower2_patrol.py', 'dts.py',
           'dew_team.py', 'scorpion_water.py', 'scorpion_king.py', 'team_npc.py', 'talk_chain.py', 'yongzhe_take.py',
           'take224.py', 'team_tp.py', 'bird.py', 'fire.py', 'buy_gear.py'}
# scripts that start from 逍遥村 by themselves (checked 2026-11-05): well10 (village -> 夕阳草原 -> 古井), supply_go
# (scrolls whoever is not on 1 / 81, PP鸡 to 81), tower1_go / tower2_go (pp_chain unless at the tower), guji_entrance
# (legs from map 1), the PP rides themselves, the trips home, bai_shi (糊涂博士 in the village); 元素使 (checked
# 2026-11-05): shuidi (scrolls apprentices not on 1 / 130 home, legs 1 -> 130), rooms (tower1_go unless the master is
# in the tower rooms already). fifth.py walks nowhere: it needs 3号房 and runs right after rooms.py in y_fifth.
STARTERS = {'well10.py', 'supply_go.py', 'tower1_go.py', 'tower2_go.py', 'guji_entrance.py', 'pp_chain.py',
            'bai_shi.py', 'pp_unlock.py', 'shuidi.py', 'rooms.py'}


class YuansuRooms(unittest.TestCase):
    def test_fifth_comes_right_after_rooms(self):
        s = next(x for x in R.ROUTE_YUANSU if x.name == 'y_fifth')
        a = [c.args[0] for c in s.cmds]
        self.assertEqual(a.index('fifth.py'), a.index('rooms.py') + 1)
        self.assertEqual(s.retry, 'home')            # a failure reruns from 逍遥村 through rooms.py again


class EveryStep(unittest.TestCase):
    """A step rerun after the recovery scrolled everybody home starts from 逍遥村: before its first walker comes a trip
    home or a PP ride, or a script that starts from the village by itself."""
    def test_no_step_walks_from_an_unknown_start(self):
        bad = []
        for route in (R.ROUTE, R.ROUTE_BPLUS, R.ROUTE_YUANSU):
            for s in route:
                for c in s.cmds:
                    a = c.args
                    if a[:2] in (('U', 'home'), ('ops', 'home_village')) or a[0] in STARTERS:
                        break
                    if a[0] in WALKERS or a[:2] == ('ops', 'take224_master'):
                        bad.append((s.name, a[0]))
                        break
        self.assertEqual(bad, [])
