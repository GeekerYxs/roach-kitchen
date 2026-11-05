"""Unit tests for projects/fullcrit_mage_leveling_70/policy.py (no game client needed)."""
import sys
import tomllib
import unittest
from collections import namedtuple
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent / 'projects' / 'fullcrit_mage_leveling_70'
sys.path.insert(0, str(PROJECT))

import policy as P  # noqa: E402

Item = namedtuple('Item', 'item_id name')


class StageTest(unittest.TestCase):
    def test_fresh_team_starts_at_the_well_not_at_1100(self):
        self.assertEqual(P.LADDER[P.stage_index(1)][0], '阴森古井')

    def test_thresholds(self):
        cases = {9: '阴森古井', 10: '轮回之城', 17: '暗影迷城', 18: '八阵图', 27: '遗忘洞穴', 28: '通天塔一区',
                 42: '通天塔二区', 43: '巨石之城东部遗址', 47: '巨石之城东部遗址', 48: '惊魂监狱',
                 53: '陷阱囚牢', 58: '禁锢之地', 69: '禁锢之地'}
        for level, name in cases.items():
            self.assertEqual(P.LADDER[P.stage_index(level)][0], name, level)

    def test_done_at_70(self):
        self.assertIsNone(P.stage_index(70))

    def test_every_stage_has_a_route(self):
        sys.path.insert(0, str(PROJECT))
        from route import ROUTES
        for name, map_id, _until in P.LADDER:
            self.assertEqual(ROUTES[name][0], map_id, name)


class StopTest(unittest.TestCase):
    def test_soda(self):
        self.assertEqual(P.classify_stop(f'{P.SODA_EMPTY}，立即停止'), 'soda')

    def test_death_by_text_or_state(self):
        self.assertEqual(P.classify_stop("{'元素使03': 1} 本段倒下 1 次，已停下"), 'death')
        self.assertEqual(P.classify_stop("['元素使03'] 不在 曾经不曾 的队里了（掉线或死亡？）"), 'death')
        self.assertEqual(P.classify_stop("有人离开禁锢之地，停止巡逻：{'元素使01': 1}"), 'death')
        self.assertEqual(P.classify_stop('anything', maps_split=True), 'death')
        self.assertEqual(P.classify_stop('anything', party_incomplete=True), 'death')

    def test_stuck(self):
        self.assertEqual(P.classify_stop('寻路连续卡住 20 次'), 'stuck')
        self.assertEqual(P.classify_stop('曾经不曾 在意外的地图 170'), 'stuck')
        self.assertEqual(P.classify_stop('巡逻到 (1000, 2900) 连续停滞 5 次'), 'stuck')

    def test_offline(self):
        self.assertEqual(P.classify_stop('元素使01 的窗口没找到'), 'offline')
        self.assertEqual(P.classify_stop(f'元素使01 读不到等级（{P.OFFLINE}）'), 'offline')

    def test_resource_is_the_only_give_up(self):
        self.assertEqual(P.classify_stop('队长金币不足，不能给 元素使01 转 60000'), 'resource')
        self.assertEqual(P.classify_stop('队长金币 100 不够买 1485 个劲爆汽水（约 141075）'), 'resource')
        self.assertEqual(P.classify_stop('队长背包空格 2 不够放 1485 个劲爆汽水（需要 15 格）'), 'resource')

    def test_unknown_is_still_recoverable(self):
        self.assertEqual(P.classify_stop('汉尼拔汽水未到账：请求 99'), 'other')
        self.assertEqual(P.classify_stop('元素使01 铁男入城选项不唯一'), 'other')
        self.assertEqual(P.classify_stop('6s 内没等到: 惊魂监狱入口确认页'), 'other')


class RetryTest(unittest.TestCase):
    def test_never_gives_up_and_backs_off(self):
        b = P.RetryBook(base=30, cap=600, fallback_after=3)
        acts = [b.failed('x', 200) for _ in range(20)]
        self.assertEqual([a.wait for a in acts[:7]], [0, 30, 60, 120, 240, 480, 600])
        self.assertTrue(all(a.wait == 600 for a in acts[6:]))
        self.assertEqual(acts[-1].streak, 20)

    def test_fallback_every_third_failure_in_a_row(self):
        b = P.RetryBook(fallback_after=3)
        self.assertEqual([b.failed('x', 1).fallback for _ in range(7)],
                         [False, False, True, False, False, True, False])

    def test_level_progress_restarts_the_streak(self):
        b = P.RetryBook()
        for _ in range(3):
            b.failed('x', 240)
        a = b.failed('x', 241)
        self.assertEqual((a.streak, a.wait, a.fallback), (1, 0, False))

    def test_success_clears(self):
        b = P.RetryBook()
        b.failed('x', 1)
        b.failed('x', 1)
        b.succeeded('x')
        self.assertEqual(b.failed('x', 1).streak, 1)

    def test_recovery_backoff(self):
        self.assertEqual([P.backoff(i) for i in (1, 2, 3, 6, 9)], [30, 60, 120, 600, 600])


class FallbackTest(unittest.TestCase):
    def name(self, i):
        return P.LADDER[i][0] if i is not None else None

    def test_one_tier_down_skipping_prison(self):
        idx = {n: i for i, (n, _m, _u) in enumerate(P.LADDER)}
        self.assertEqual(self.name(P.fallback_index(idx['禁锢之地'])), '陷阱囚牢')
        self.assertEqual(self.name(P.fallback_index(idx['陷阱囚牢'])), '巨石之城东部遗址')
        self.assertEqual(self.name(P.fallback_index(idx['惊魂监狱'])), '巨石之城东部遗址')
        self.assertEqual(self.name(P.fallback_index(idx['轮回之城'])), '阴森古井')
        self.assertIsNone(P.fallback_index(idx['阴森古井']))


class YamTest(unittest.TestCase):
    def test_only_plain_yams(self):
        items = {i.item_id: i for i in (
            Item(31404, '(御)加钙地瓜礼包'), Item(32000, '加钙地瓜'), Item(32004, '(御)加钙地瓜'),
            Item(32410, '【还需程序支持】超级加钙地瓜'), Item(32450, '(御)倍能加钙地瓜'))}
        self.assertEqual(P.yam_ids(items), {32000, 32004})


class BagTest(unittest.TestCase):
    def test_stacks(self):
        self.assertEqual(P.stacks_needed([], 1485), 15)
        self.assertEqual(P.stacks_needed([99, 99, 50], 1485 - 248), 12)   # 49 room in the partial stack
        self.assertEqual(P.stacks_needed([99, 99, 50], 1485 - 247), 13)
        self.assertEqual(P.stacks_needed([60], 39), 0)


class ShoeTest(unittest.TestCase):
    def test_plan(self):
        self.assertEqual(P.shoe_plan(0, 600, True), 'fly')
        self.assertEqual(P.shoe_plan(120, 600, True), 'wait')
        self.assertEqual(P.shoe_plan(3000, 600, True), 'paid')
        self.assertEqual(P.shoe_plan(0, 600, False), 'paid')


class TeamConfigTest(unittest.TestCase):
    def test_team_toml(self):
        with open(PROJECT / 'team.toml', 'rb') as f:
            cfg = tomllib.load(f)
        self.assertTrue(cfg['leader'])
        self.assertEqual(len(cfg['apprentices']), 4)
        self.assertFalse(cfg['sell_worn_white'])


if __name__ == '__main__':
    unittest.main()
