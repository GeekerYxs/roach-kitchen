"""Unit tests for the sell rule (no game needed)."""
import unittest

from factory.items import (Item, inventory_lines, junk_count, load_items, sell_slots, shop_value, unequip_plan,
                           verdict)
from factory.supply import HP_ITEM, MP_ITEM, PET_ITEM, SCROLL_ITEM
from provisioner.world import BagSlot

WRENCH, DISH, MEAT, POTATO, PERFUME, LEG, RUMP = 118, 27002, 30188, 32004, 32019, 10571, 10572


def bag(*items):
    return tuple(BagSlot(i, item, qty) for i, (item, qty) in enumerate(items))


class RealTable(unittest.TestCase):
    """Against the real items.csv: what the user named must come out right."""

    @classmethod
    def setUpClass(cls):
        cls.items = load_items()

    def test_wrench_is_an_orange_weapon_sold_by_alts_kept_by_leaders(self):
        it = self.items[WRENCH]
        self.assertEqual((it.type, it.quality, it.price), (0x103, 4, 1020))
        self.assertTrue(verdict(WRENCH, self.items)[0])
        self.assertFalse(verdict(WRENCH, self.items, leader=True)[0])

    def test_every_skill_stone_is_sold_even_blue_orange_and_by_leaders(self):
        stones = [i for i, it in self.items.items() if it.type == 0x821]
        self.assertGreater(len(stones), 1500)
        for leader in (False, True):
            self.assertTrue(all(verdict(i, self.items, leader=leader)[0] for i in stones))

    def test_supplies_dish_food_perfume_and_quest_items_are_never_sold(self):
        keep = {SCROLL_ITEM, HP_ITEM, MP_ITEM, PET_ITEM}
        for item in keep | {DISH, MEAT, POTATO, PERFUME, LEG, RUMP}:
            for leader in (False, True):
                self.assertFalse(verdict(item, self.items, keep, leader)[0], item)

    def test_unknown_item_is_kept(self):
        self.assertEqual(verdict(999999, self.items), (False, '物品表里没有（无价格）'))


class Rule(unittest.TestCase):
    ITEMS = {
        1: Item(1, 0x103, 2, 80, True, False, '绿刀'),
        2: Item(2, 0x106, 5, 900, True, False, '金上衣'),
        7: Item(7, 0x103, 3, 27556, True, False, '蓝球棒'),
        3: Item(3, 0x1000, 0, 10, True, False, '杂物'),
        4: Item(4, 0x400, 1, 100, True, False, '药'),
        5: Item(5, 0x1000, 1, 7, False, True, '重要杂物'),
        6: Item(6, 0x821, 4, 50, False, True, '绑定技能石'),
    }

    def test_slots_and_keep(self):
        b = bag((1, 1), (2, 1), (3, 5), (4, 9), (5, 1), (6, 1))
        self.assertEqual([s.slot for s in sell_slots(b, self.ITEMS)], [0, 1, 2, 5])       # bound 5 kept, bound stone sold
        self.assertEqual([s.slot for s in sell_slots(b, self.ITEMS, leader=True)], [0, 2, 5])
        self.assertEqual([s.slot for s in sell_slots(b, self.ITEMS, keep={3})], [0, 1, 5])
        blue = bag((7, 1), (1, 1))
        self.assertEqual([s.slot for s in sell_slots(blue, self.ITEMS, leader=True)], [1])     # leaders keep blue+
        self.assertEqual([s.slot for s in sell_slots(blue, self.ITEMS)], [0, 1])               # alts sell it
        self.assertEqual([s.slot for s in sell_slots(b, self.ITEMS, limit=2)], [0, 1])

    def test_shop_pays_half_per_piece(self):
        self.assertEqual(shop_value(bag((1, 1), (3, 5), (5, 3)), self.ITEMS), 40 + 25 + 9)

    def test_inventory_lines(self):
        lines = inventory_lines(bag((5, 1), (777, 2)), self.ITEMS)
        self.assertIn('重要杂物 [杂物 白 重要 不可交易] 单价收 3 ×1  -> 留（绑定物品（重要且不可交易））', lines[0])
        self.assertIn('物品 777 ×2  -> 留', lines[1])


class Alt(unittest.TestCase):
    ITEMS = Rule.ITEMS

    def test_worn_sellable_items_count_and_go_to_free_slots(self):
        worn = (BagSlot(2, 1, 1), BagSlot(8, 2, 1), BagSlot(9, 4, 1))     # weapon, cloth, a kept item
        b = (BagSlot(0, 3, 5), BagSlot(1, 4, 9), BagSlot(3, 3, 1))
        self.assertEqual(junk_count(b, worn, self.ITEMS), 2 + 2)
        self.assertEqual(unequip_plan(worn, b, 40, self.ITEMS), [(2, 2), (8, 4)])
        self.assertEqual(unequip_plan(worn, b, 3, self.ITEMS), [(2, 2)])          # one free slot only
        self.assertEqual(junk_count((), (), self.ITEMS), 0)

    def test_real_wrench_is_taken_off(self):
        items = load_items()
        self.assertEqual(unequip_plan((BagSlot(2, WRENCH, 1),), bag((DISH, 1)), 40, items), [(2, 1)])


if __name__ == '__main__':
    unittest.main()
