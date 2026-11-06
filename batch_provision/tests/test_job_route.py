"""Optional 元素使 line (user 2026-11-03): job = "术士" picks route.ROUTE_YUANSU, the default stays the 勇者 line and its
routes must not change at all."""
import hashlib
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'shitu'))

from line import route as R  # noqa: E402
from line import ops  # noqa: E402

# repr() fingerprints of the 勇者 routes as committed in 189b3d0 (after the no-DOUBLE-before-fairy/chushi change).
# A change to the 勇者 line itself must update these on purpose; adding the 元素使 line must not.
# Updated on purpose 2026-11-05: PR #20 (勇者 apprentices own no weapon: sell_tradable --weapons, wear_best
# --no-weapon) and PP_COAST before lunhui / maze (a team scrolled home got 「在意外的地图 1」 for ever); then
# maze_train --stay (no walk to 大个王 after 八阵图); then U space before zhuanzhi's supply and q183.
# 2026-11-05: the v5 route is deleted (user: only B+); B+ itself unchanged by that (same fingerprint).
# Updated on purpose 2026-11-05: the arm step tops the master up to the per-batch quota (U master_supply, user)
# instead of U restock_master 100.
BRAVE_FINGERPRINTS = {'bplus': '00f47090767ddc7a'}


def fp(route):
    return hashlib.sha256(repr(route).encode()).hexdigest()[:16]


class BraveUntouched(unittest.TestCase):
    def test_brave_routes_are_unchanged(self):
        self.assertIs(R.ROUTE, R.ROUTE_BPLUS)
        self.assertEqual(fp(R.ROUTE_BPLUS), BRAVE_FINGERPRINTS['bplus'])

    def test_default_and_warrior_teams_get_the_brave_routes(self):
        self.assertIs(R.route_of(NS(route='bplus')), R.ROUTE_BPLUS)           # old batches: no job attribute
        self.assertIs(R.route_of(NS(route='bplus', job='战士')), R.ROUTE_BPLUS)
        self.assertIs(R.route_of(NS(route='v5', job='战士')), R.ROUTE_BPLUS)    # v5 gone 2026-11-05: B+

    def test_fairy_words_for_183_are_the_old_ones(self):
        self.assertEqual(ops.FAIRY['183'], ['勇者的考验', '继续', '继续', '完成转职礼', '接受奖励'])


class Tower2Exit(unittest.TestCase):
    def test_mage_teams_leave_erqu_at_40_70000_brave_teams_unchanged(self):
        from line import plan
        mage = plan.Team('m', 0, 10000, job='术士', names='x', accounts=1)
        self.assertEqual(mage.tower2, plan.TOWER2_YUANSU)
        self.assertEqual(plan.TOWER2_YUANSU, '40+70000')     # 2026-11-05: 出师 gives gold, not exp
        self.assertEqual(plan.Team('m', 0, 10000).tower2, 'auto')
        self.assertEqual(plan.Team('m', 0, 10000, job='术士', tower2='39+50000').tower2, '39+50000')


class Yuansu(unittest.TestCase):
    def setUp(self):
        self.route = R.route_of(NS(route='bplus', job='术士'))
        self.names = [s.name for s in self.route]

    def test_mage_team_gets_the_yuansu_route(self):
        self.assertIs(self.route, R.ROUTE_YUANSU)

    def test_no_brave_quest_step_left(self):
        self.assertFalse(set(self.names) & set(R.BRAVE))
        args = [c.args[0] for s in self.route for c in s.cmds]
        for brave in ('quanshou.py', 'yongzhe_take.py', 'quan100.py', 'scorpion_king.py', 'scorpion_water.py'):
            self.assertNotIn(brave, args)

    def test_class_change_uses_the_books(self):
        z = self.route[self.names.index('zhuanzhi')]
        self.assertIn(('shuidi.py',), [c.args for c in z.cmds])

    def test_order_gear_before_tower2_then_187_then_189_then_fairy(self):
        n = self.names
        self.assertLess(n.index('gear'), n.index('tower2'))
        self.assertEqual(n[n.index('tower2') + 1:], ['y187', 'y_stone', 'y_yaodao', 'y_huaxiang', 'y_bird', 'y189',
                                                     'y_fire', 'y_water', 'y_wind1', 'y_doll', 'y_wind2', 'y_fifth',
                                                     'topup', 'fairy', 'chushi', 'finish'])
        self.assertEqual(self.route[n.index('fairy')].env, {'SHITU_QID': '189'})

    def test_finish_keeps_the_gold_and_sends_out_the_jiong_pet(self):
        # user 2026-11-05: an 元素使 keeps its gold; the line ends with the 囧盒仔 opened and fighting
        f = [c.args for c in self.route[self.names.index('finish')].cmds]
        self.assertNotIn('give_gold.py', [a[0] for a in f])
        self.assertEqual(f[f.index(('U', 'home')) + 1], ('jiong.py', '{APPS}'))
        self.assertEqual(f[-1], ('ops', 'close', '{APPS}'))          # user 2026-11-06: finished windows closed
        brave = [c.args[0] for c in R.ROUTE_BPLUS[[s.name for s in R.ROUTE_BPLUS].index('finish')].cmds]
        self.assertIn('give_gold.py', brave)
        self.assertNotIn('jiong.py', brave)

    def test_every_quest_step_but_wind1_ends_with_a_gate(self):
        for s in R.YUANSU_LATE:
            if s.name == 'y_wind1':          # 风娃娃 / 杰克 only switch steps on; y_doll's drops are its gate
                continue
            self.assertIn(s.cmds[-1].args[:2], (('U', 'need'), ('U', 'have')), s.name)

    def test_no_double_at_fairy_or_chushi(self):
        for s in self.route:
            if s.name in ('fairy', 'chushi'):
                self.assertNotIn(('U', 'double'), [c.args for c in s.cmds])


if __name__ == '__main__':
    unittest.main()
