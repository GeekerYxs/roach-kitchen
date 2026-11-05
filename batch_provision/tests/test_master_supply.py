"""master_supply.py: the master's per-batch supply quota (no game). SUPPLY_DESIGN.md §4.0, user 2026-11-05."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'shitu'))

import master_supply as S  # noqa: E402
from provisioner.world import BagSlot  # noqa: E402

POT = S.load_potions()


def bag(*items):
    return [BagSlot(i, item, q) for i, (item, q) in enumerate(items)]


def full(item, n):
    """n full stacks of 99 (or 50 for 回城卷)."""
    return [(item, S.STACK.get(item, 99))] * n


class Table(unittest.TestCase):
    def test_standard_potions(self):
        self.assertEqual(POT[8454], ('mp', 310))        # 健康果汁
        self.assertEqual(POT[8404], ('hp', 310))        # 心情便当
        self.assertEqual(POT[8573], ('loyal', 150))     # 甜点
        self.assertEqual(POT[8456], ('mp', 590))        # 劲爆汽水

    def test_misfiled_auto_use_rows(self):
        self.assertEqual(POT[63955], ('loyal', 20))     # 鸡蛋饼干 sits in AutoUseItemID 补魔法 but gives 忠诚
        for i in (63956, 63957, 63958, 63959):          # script items, no restore
            self.assertNotIn(i, POT)
        self.assertNotIn(S.SCROLL, POT)

    def test_quota_matches_line_toml(self):
        self.assertEqual(S.load_quota(), S.QUOTA)
        self.assertEqual(S.QUOTA['mp'], 15 * 99 * 310)
        self.assertEqual(S.QUOTA['hp'], 3 * 99 * 310)
        self.assertEqual(S.QUOTA['loyal'], 4 * 99 * 150)


class Plan(unittest.TestCase):
    def test_standard_full_master_buys_nothing(self):
        b = bag(*full(8454, 15), *full(8404, 3), *full(8573, 4), (9801, 50), (9801, 50))
        p = S.plan(b, 40, POT)
        self.assertEqual((p.buys, p.cost, p.slots), ({}, 0, 0))

    def test_empty_bag(self):
        p = S.plan(bag(), 40, POT)
        self.assertEqual(p.buys, {9801: 100, 8454: 1485, 8404: 297, 8573: 396})
        self.assertEqual(list(p.buys), [9801, 8454, 8404, 8573])     # 回城卷 first: the way home needs one
        self.assertEqual(p.cost, 194140)                             # the §4.0 sum
        self.assertEqual(p.slots, 2 + 15 + 3 + 4)

    def test_zi_you_san_hao_live(self):
        # 自由三号's real bag, read 2026-11-05 after the 翠花 test (22 slots used of 40)
        b = bag(*full(8454, 14), *full(8573, 3), (8573, 90), (9801, 49), (9801, 2), (8404, 99), (8454, 1))
        p = S.plan(b, 40, POT)
        self.assertEqual(p.have, {'mp': 1387 * 310, 'hp': 99 * 310, 'loyal': 387 * 150})
        self.assertEqual(p.buys, {8454: 98, 8404: 198, 8573: 9})     # 51 回城卷 > 30: none
        self.assertEqual(p.slots, 2)                                 # 健康果汁 / 甜点 fill their partial stacks
        self.assertEqual(p.cost, 98 * 50 + 198 * 50 + 9 * 240)

    def test_borrowed_master_soda_counts(self):
        # 曾经不曾 2026-11-05: 574 劲爆汽水 = 338660 mp, 195 怀旧便当 = 115050 hp
        b = bag(*full(8456, 5), (8456, 79), *full(8406, 1), (8406, 96), (9801, 25), *full(8573, 3), (8573, 12))
        p = S.plan(b, 40, POT)
        self.assertEqual(p.buys[8454], -(-(460350 - 574 * 590) // 310))   # 393: only the gap, in 健康果汁
        self.assertNotIn(8404, p.buys)
        self.assertEqual(p.buys[9801], 75)                           # 25 <= 30 -> 100

    def test_scroll_threshold(self):
        base = [*full(8454, 15), *full(8404, 3), *full(8573, 4)]
        self.assertEqual(S.plan(bag(*base, (9801, 31)), 40, POT).buys, {})
        self.assertEqual(S.plan(bag(*base, (9801, 30)), 40, POT).buys, {9801: 70})

    def test_egg_biscuit_is_not_mp(self):
        b = bag(*full(8404, 3), *full(8573, 4), (9801, 50), (63955, 99))
        p = S.plan(b, 40, POT)
        self.assertEqual(p.have['mp'], 0)
        self.assertEqual(p.buys, {8454: 1485})


class Fit(unittest.TestCase):
    def test_fits_untouched(self):
        p = S.plan(bag(), 40, POT)
        q = S.fit(p, bag(), 24)
        self.assertEqual((q.buys, q.warnings), (p.buys, []))

    def test_cuts_juice_first(self):
        p = S.plan(bag(), 40, POT)
        q = S.fit(p, bag(), 20)                                      # 4 slots short
        self.assertEqual(q.buys, {9801: 100, 8454: 11 * 99, 8404: 297, 8573: 396})
        self.assertEqual(q.slots, 20)
        self.assertEqual(len(q.warnings), 1)
        self.assertEqual(q.cost, 100 * 100 + 11 * 99 * 50 + 297 * 50 + 396 * 240)

    def test_odd_part_goes_first(self):
        b = bag(*full(8454, 14), (8454, 1))                          # 98 to buy fills the partial stack: no slot
        p = S.plan(b, 40, POT, dict(S.QUOTA, hp=0, loyal=0, scroll_low=-1))
        self.assertEqual((p.buys, p.slots), ({8454: 98}, 0))
        self.assertEqual(S.fit(p, b, 0).buys, {8454: 98})

    def test_no_room_at_all_keeps_nothing(self):
        p = S.plan(bag(), 40, POT)
        q = S.fit(p, bag(), 0)
        self.assertEqual(q.buys, {})
        self.assertEqual(len(q.warnings), 4)


class Gold(unittest.TestCase):
    def test_gold(self):
        p = S.plan(bag(), 40, POT)
        self.assertIsNone(S.gold_problem(p, 194140))
        self.assertIn('不够', S.gold_problem(p, 194139))


if __name__ == '__main__':
    unittest.main()
