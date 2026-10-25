"""Unit tests for leader supplies (no game needed)."""
import struct
import unittest
from unittest import mock

from factory import supply
from factory.supply import (HP_ITEM, MP_ITEM, NURSE, PET_ITEM, PETSHOP, SCROLL_ITEM, Gate, ShopClient, SupplySettings,
                            blocked, blocked_text, due, junk, load_supply, needs, plan_buys, sell_body, shortages)
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
        held = bag(*[(1, 1)] * 36, (SCROLL_ITEM, 50))            # 3 free = reserve; it still has 回城卷: no new slot
        self.assertEqual(plan_buys(held, 40, {SCROLL_ITEM: 50}, NURSE, 10 ** 6, 3), [])

    def test_used_up_item_gets_one_stack_in_the_reserve(self):
        full = bag(*[(1, 1)] * 37)                              # 3 free = the reserve
        plan = plan_buys(full, 40, {SCROLL_ITEM: 100, HP_ITEM: 198, MP_ITEM: 198}, NURSE, 10 ** 6, 3)
        self.assertEqual(plan, [(4, SCROLL_ITEM, 50), (0, HP_ITEM, 99), (2, MP_ITEM, 99)])
        two = bag(*[(1, 1)] * 38)                               # only 2 empty: the first two used-up items
        self.assertEqual(len(plan_buys(two, 40, {SCROLL_ITEM: 100, HP_ITEM: 198, MP_ITEM: 198}, NURSE, 10 ** 6, 3)), 2)
        self.assertEqual(plan_buys(bag(*[(1, 1)] * 40), 40, {SCROLL_ITEM: 100}, NURSE, 10 ** 6, 3), [])

    def test_reserve_only_for_used_up_items(self):
        some = bag(*[(1, 1)] * 36, (SCROLL_ITEM, 50))           # 3 free, 5 short of nothing: stack is full
        self.assertEqual(plan_buys(some, 40, {SCROLL_ITEM: 50}, NURSE, 10 ** 6, 3), [])
        topped = bag(*[(1, 1)] * 36, (SCROLL_ITEM, 10))
        self.assertEqual(plan_buys(topped, 40, {SCROLL_ITEM: 90}, NURSE, 10 ** 6, 3), [(4, SCROLL_ITEM, 40)])

    def test_reserve_respects_gold(self):
        full = bag(*[(1, 1)] * 37)
        self.assertEqual(plan_buys(full, 40, {SCROLL_ITEM: 100}, NURSE, 950, 3), [(4, SCROLL_ITEM, 9)])
        self.assertEqual(plan_buys(full, 40, {SCROLL_ITEM: 100}, NURSE, 50, 3), [])

    def test_gold_limits(self):
        self.assertEqual(plan_buys((), 40, {SCROLL_ITEM: 100}, NURSE, 950, 3), [(4, SCROLL_ITEM, 9)])

    def test_other_shops_items_are_skipped(self):
        self.assertEqual(plan_buys((), 40, {PET_ITEM: 99}, NURSE, 10 ** 6, 3), [])
        self.assertEqual(plan_buys((), 40, {PET_ITEM: 99}, PETSHOP, 10 ** 6, 3), [(7, PET_ITEM, 99)])


class Blocked(unittest.TestCase):
    TABLE = {501: Item(501, 0x103, 4, 1020, True, False, '橙武器'), 503: Item(503, 0x103, 3, 900, True, False, '蓝棒')}

    def test_room_after_selling_is_fine(self):
        self.assertIsNone(blocked(bag(*[(501, 1)] * 32), 40, 8, self.TABLE, {SCROLL_ITEM}))

    def test_unsellables_reported_biggest_first(self):
        b = bag(*[(501, 1)] * 20, *[(503, 1)] * 10, *[(9999, 1)] * 2, *[(SCROLL_ITEM, 50)] * 3)
        free, top = blocked(b, 40, 8, self.TABLE, {SCROLL_ITEM})
        self.assertEqual((free, top), (5, [('橙武器', 20), ('蓝棒', 10), ('物品 9999', 2)]))
        self.assertEqual(blocked_text('cap07', free, 40, top),
                         '！cap07 背包卖完杂物后只空 5/40 格，占地方的：橙武器×20格、蓝棒×10格、物品 9999×2格；请手动清理')


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

    def test_sell_packs_slots_into_one_request(self):
        junk_bag = bag((500, 1), (501, 4))
        self.bags = [junk_bag, ()]
        self.assertEqual(self.client.sell(NURSE, list(junk_bag)), 2)
        shop = [b for op, b in self.sent() if op == 0x55]
        self.assertEqual(shop, [struct.pack('<IIBBHBBBB', 0, 409, 2, 1, 0, 0, 1, 1, 4)])
        self.assertEqual([b for op, b in self.sent() if op == 0x51], [struct.pack('<III', 0, 2, 0)])

    def test_sell_batches_of_20_each_with_a_fresh_open(self):
        big = bag(*[(500, 1)] * 25)
        self.bags = [big, big[20:], ()]
        self.assertEqual(self.client.sell(NURSE, list(big)), 25)
        shop = [b for op, b in self.sent() if op == 0x55]
        self.assertEqual([b[8] for b in shop], [20, 5])
        self.assertEqual([len(b) for b in shop], [52, 22])
        self.assertEqual(len([op for op, _ in self.sent() if op == 0x50]), 2)

    def test_sell_counts_only_slots_that_left_the_bag(self):
        junk_bag = bag((500, 1), (501, 4))
        self.bags = [(BagSlot(1, 501, 4),)] * 40           # slot 1 refused
        self.assertEqual(self.client.sell(NURSE, list(junk_bag)), 1)

    def test_refused_batch_is_retried_slot_by_slot(self):
        # live 2026-10-25: the server refused a whole batch for its third entry; the others must still go
        junk_bag = bag((500, 1), (501, 4), (502, 1))
        state = {'bag': junk_bag}

        def shop(op, body):         # all or nothing per request; item 502 is never accepted
            if op != 0x55:
                return
            asked = {body[12 + 2 * i] for i in range(body[8])}
            have = [b for b in state['bag'] if b.slot in asked]
            if all(b.item_id != 502 for b in have):
                state['bag'] = tuple(b for b in state['bag'] if b.slot not in asked)
        self.game.send.side_effect = shop
        with mock.patch.object(supply, 'read_bag', side_effect=lambda mem: state['bag']):
            self.assertEqual(self.client.sell(NURSE, list(junk_bag)), 2)
        self.assertEqual([b[8] for op, b in self.sent() if op == 0x55], [3, 1, 1, 1])   # batch, then slot by slot
        self.assertEqual(state['bag'], (junk_bag[2],))

    def test_same_slot_is_sent_once(self):
        junk_bag = bag((500, 1), (501, 4))
        self.bags = [junk_bag, ()]
        self.assertEqual(self.client.sell(NURSE, list(junk_bag) + [junk_bag[0]]), 2)
        self.assertEqual([b[8] for op, b in self.sent() if op == 0x55], [2])

    def test_sell_body(self):
        self.assertEqual(sell_body(409, [(3, 2)]), struct.pack('<IIBBHBB', 0, 409, 1, 1, 0, 3, 2))   # live 1-slot shape
        with self.assertRaises(ValueError):
            sell_body(409, [(1, 1)] * 21)
        with self.assertRaises(ValueError):
            sell_body(409, [])

if __name__ == '__main__':
    unittest.main()
