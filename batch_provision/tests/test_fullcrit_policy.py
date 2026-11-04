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
        self.assertEqual(P.classify_stop("有人离开禁锢之地，停止巡逻：{'元素使01': 1}"), 'death')
        self.assertEqual(P.classify_stop('anything', maps_split=True), 'death')
        self.assertEqual(P.classify_stop('anything', party_incomplete=True), 'death')

    def test_stuck(self):
        self.assertEqual(P.classify_stop('寻路连续卡住 20 次'), 'stuck')
        self.assertEqual(P.classify_stop('曾经不曾 在意外的地图 170'), 'stuck')
        self.assertEqual(P.classify_stop('巡逻到 (1000, 2900) 连续停滞 5 次'), 'stuck')

    def test_needs_human(self):
        self.assertIsNone(P.classify_stop('汉尼拔汽水未到账：请求 99'))
        self.assertIsNone(P.classify_stop('元素使01 铁男入城选项不唯一'))


class RetryTest(unittest.TestCase):
    def test_limit_without_progress(self):
        b = P.RetryBook(limit=3)
        self.assertEqual([b.failed('x', 200) for _ in range(4)], [True, True, True, False])

    def test_level_progress_restarts_the_count(self):
        b = P.RetryBook(limit=3)
        for _ in range(3):
            self.assertTrue(b.failed('x', 240))
        self.assertTrue(b.failed('x', 241))
        self.assertEqual(b.count['x'], 1)

    def test_success_clears(self):
        b = P.RetryBook(limit=1)
        b.failed('x', 1)
        b.succeeded('x')
        self.assertTrue(b.failed('x', 1))


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
