"""Unit tests for leader supplies (no game needed)."""
import struct
import unittest
from unittest import mock

from factory import supply
from factory.supply import (HP_ITEM, MP_ITEM, NURSE, PET_ITEM, PETSHOP, SCROLL_ITEM, Gate, ShopClient, SupplySettings,
                            due, junk, load_supply, needs, plan_buys, shortages)
from factory.items import Item
from provisioner.world import BagSlot

RULES = load_supply({}).rules['well']
S = SupplySettings(rules={'well': RULES})


def bag(*items):
    """(item, qty) pairs -> BagSlots in slots 0, 1, 2..."""
    return tuple(BagSlot(i, item, qty) for i, (item, qty) in enumerate(items))


class Shortages(unittest.TestCase):
    def test_only_items_below_low_up_to_target(self):
        b = bag((SCROLL_ITEM, 19), (HP_ITEM, 30), (MP_ITEM, 99), (MP_ITEM, 99))
        self.assertEqual(shortages(b, RULES), {SCROLL_ITEM: 81, PET_ITEM: 99})

    def test_needs_splits_by_shop_and_flags_a_full_bag(self):
        b = bag((SCROLL_ITEM, 50), (SCROLL_ITEM, 50), (HP_ITEM, 99), (HP_ITEM, 99), (MP_ITEM, 99), (MP_ITEM, 99),
                (PET_ITEM, 5))
        coast, village, sell = needs(b, 40, RULES, S)
        self.assertEqual((coast, village, sell), ({}, {PET_ITEM: 94}, False))
        self.assertTrue(needs(b, 14, RULES, S)[2])         # 7 free < 8

    def test_due(self):
        full = bag((SCROLL_ITEM, 50), (SCROLL_ITEM, 50), (HP_ITEM, 99), (HP_ITEM, 99), (MP_ITEM, 99), (MP_ITEM, 99),
                   (PET_ITEM, 99))
        self.assertFalse(due('well', full, 40, S))
        self.assertTrue(due('well', full[:-1], 40, S))
        self.assertFalse(due('receiver', (), 40, S))        # no rules for that role


class PlanBuys(unittest.TestCase):
    def test_fills_the_stack_then_new_slots_in_99_chunks(self):
        b = bag((MP_ITEM, 1))
        plan = plan_buys(b, 40, {MP_ITEM: 197}, NURSE, 10 ** 6, 3)
        self.assertEqual(plan, [(2, MP_ITEM, 99), (2, MP_ITEM, 98)])

    def test_scroll_stack_is_50(self):
        plan = plan_buys(bag((SCROLL_ITEM, 38)), 40, {SCROLL_ITEM: 62}, NURSE, 10 ** 6, 3)
        self.assertEqual(sum(q for _, _, q in plan), 62)        # 12 into the stack + 50 into one new slot

    def test_keeps_free_slots(self):
        b = bag(*[(1, 1)] * 36)                                 # 4 free, keep 3 -> one new slot
        self.assertEqual(plan_buys(b, 40, {SCROLL_ITEM: 100}, NURSE, 10 ** 6, 3), [(4, SCROLL_ITEM, 50)])
        self.assertEqual(plan_buys(bag(*[(1, 1)] * 37), 40, {SCROLL_ITEM: 100}, NURSE, 10 ** 6, 3), [])

    def test_gold_limits(self):
        self.assertEqual(plan_buys((), 40, {SCROLL_ITEM: 100}, NURSE, 950, 3), [(4, SCROLL_ITEM, 9)])

    def test_other_shops_items_are_skipped(self):
        self.assertEqual(plan_buys((), 40, {PET_ITEM: 99}, NURSE, 10 ** 6, 3), [])
        self.assertEqual(plan_buys((), 40, {PET_ITEM: 99}, PETSHOP, 10 ** 6, 3), [(7, PET_ITEM, 99)])


class Junk(unittest.TestCase):
    """Leader rule from factory/items.py (tests/test_factory_items.py has the rule itself)."""
    ITEMS = {500: Item(500, 0x1000, 0, 10, True, False, '杂物'), 501: Item(501, 0x103, 4, 1020, True, False, '橙武器'),
             502: Item(502, 0x821, 3, 50, True, False, '蓝技能石'), SCROLL_ITEM: Item(SCROLL_ITEM, 0x1000, 1, 40, True, False, 'x')}

    def test_sells_by_rule_never_kept_items(self):
        b = bag((500, 1), (9999, 1), (501, 1), (502, 1), (SCROLL_ITEM, 10))
        self.assertEqual([s.slot for s in junk(b, self.ITEMS, {SCROLL_ITEM})], [0, 3])

    def test_limit(self):
        self.assertEqual(len(junk(bag(*[(500, 1)] * 30), self.ITEMS, set())), 30)          # whole bag
        self.assertEqual(len(junk(bag(*[(500, 1)] * 30), self.ITEMS, set(), limit=20)), 20)


class Config(unittest.TestCase):
    def test_defaults_and_override(self):
        s = load_supply({'supply': {'keep_free': 5, 'well': {'scroll': [10, 50]}}})
        self.assertEqual(s.keep_free, 5)
        self.assertEqual(s.rules['well'], {SCROLL_ITEM: (10, 50)})
        self.assertEqual(s.rules['coast'][PET_ITEM], (10, 99))
        self.assertNotIn(HP_ITEM, s.rules['dispatcher'])

    def test_bad_values(self):
        with self.assertRaises(ValueError):
            load_supply({'supply': {'well': {'gem': [1, 2]}}})
        with self.assertRaises(ValueError):
            load_supply({'supply': {'well': {'scroll': [60, 50]}}})


class Gating(unittest.TestCase):
    def test_retry_after_failure(self):
        t = [0.0]
        g = Gate(600, clock=lambda: t[0])
        self.assertTrue(g.open('c1'))
        g.failed('c1')
        t[0] = 599
        self.assertFalse(g.open('c1'))
        t[0] = 600
        self.assertTrue(g.open('c1'))


class Requests(unittest.TestCase):
    def setUp(self):
        self.game = mock.Mock()
        self.bags = []
        patcher = mock.patch.object(supply, 'read_bag', side_effect=lambda mem: self.bags.pop(0) if len(self.bags) > 1
                                    else self.bags[0])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.t = [0.0]

        def sleep(s):
            self.t[0] += s
        self.client = ShopClient(self.game, None, mock.Mock(), sleep=sleep, clock=lambda: self.t[0])

    def sent(self):
        return [(c.args[0], c.args[1]) for c in self.game.send.call_args_list]

    def test_buy_opens_then_one_request_and_verifies(self):
        self.bags = [bag((HP_ITEM, 1)), bag((HP_ITEM, 1)), bag((HP_ITEM, 3))]
        self.assertTrue(self.client.buy(NURSE, 0, HP_ITEM, 2))
        self.assertEqual(self.sent(), [(0x50, struct.pack('<II', 0, 409)), (0x51, struct.pack('<III', 0, 1, 0)),
                                       (0x55, struct.pack('<IIBBHBB', 0, 409, 1, 0, 0, 0, 2))])
        self.assertEqual(len(self.sent()[2][1]), 14)

    def test_buy_not_arrived(self):
        self.bags = [bag((HP_ITEM, 1))]
        self.assertFalse(self.client.buy(NURSE, 0, HP_ITEM, 2))

    def test_close_selects_leave_and_waits(self):
        with mock.patch.object(supply, 'read_dialog', side_effect=[object(), None]):
            self.assertTrue(self.client.close())
        self.game.select_dialog.assert_called_once_with(0)

    def test_pet_shop_sells_with_its_own_option(self):
        self.bags = [bag((500, 1)), ()]
        self.client.sell(PETSHOP, list(bag((500, 1))))
        self.assertEqual([b for op, b in self.sent() if op == 0x51][0], struct.pack('<III', 0, 3, 0))

    def test_sell_reopens_per_slot_with_sell_option(self):
        junk_bag = bag((500, 1), (501, 4))
        self.bags = [junk_bag, bag((501, 4)), ()]
        self.assertEqual(self.client.sell(NURSE, list(junk_bag)), 2)
        shop = [b for op, b in self.sent() if op == 0x55]
        self.assertEqual(shop, [struct.pack('<IIBBHBB', 0, 409, 1, 1, 0, 0, 1),
                                struct.pack('<IIBBHBB', 0, 409, 1, 1, 0, 1, 4)])
        self.assertEqual([b for op, b in self.sent() if op == 0x51][0], struct.pack('<III', 0, 2, 0))


if __name__ == '__main__':
    unittest.main()
