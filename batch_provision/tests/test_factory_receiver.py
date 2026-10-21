"""Unit tests for the receiver stage decision and the item offer body (no game needed)."""
import struct
import unittest
from dataclasses import replace

from factory.receiver import (CONFIRM_WAIT, NAV_RETRY, BagRoom, Memo, bag_alarm, bag_room, bag_text, decide, decide_gold,
                              dish_count, dish_slot, hours_left)
from provisioner.game import trade_item_offer_body
from provisioner.world import BagSlot, Team, WorldState

RECV = WorldState(char_id=7, map_id=81, x=1780.0, y=1370.0, target_x=1780.0, target_y=1370.0, flags=0,
                  busy=False, in_battle=False, nav_active=False, verification=False, still_for=5.0)
ALT = replace(RECV, char_id=1, x=1790.0, y=1365.0)
SOLO = Team((), (), 0)
SLOT = (12, 1)


def run(alt=ALT, team=SOLO, alt_dishes=1, slot=SLOT, recv=RECV, recv_dishes=3, memo=None, now=0.0):
    return decide(alt, team, alt_dishes, slot, recv, recv_dishes, memo or Memo(), now)


class Decide(unittest.TestCase):
    def test_trade_when_close_and_idle(self):
        d = run()
        self.assertEqual((d.kind, d.arg), ('trade', SLOT))

    def test_no_dish_is_done(self):
        self.assertEqual(run(alt_dishes=0, slot=None).kind, 'done')

    def test_far_alt_walks_to_receiver(self):
        far = replace(ALT, x=1152.0, y=932.0)
        d = run(alt=far)
        self.assertEqual((d.kind, d.arg), ('navigate', (81, 1780, 1370)))
        self.assertEqual(run(alt=far, memo=Memo(last_nav=0.0), now=NAV_RETRY - 0.1).kind, 'wait')
        self.assertEqual(run(alt=replace(far, nav_active=True), now=10.0).kind, 'wait')

    def test_busy_waits(self):
        self.assertEqual(run(alt=replace(ALT, in_battle=True)).kind, 'wait')
        self.assertEqual(run(recv=replace(RECV, verification=True)).kind, 'wait')

    def test_wrong_map_or_team_fails(self):
        self.assertEqual(run(recv=replace(RECV, map_id=1)).kind, 'fail')
        self.assertEqual(run(team=Team((9, 1), (70, 12), 9)).kind, 'fail')

    def test_loading_waits(self):
        self.assertEqual(run(alt=None).kind, 'wait')
        self.assertEqual(run(recv_dishes=None).kind, 'wait')

    def test_verified_needs_both_sides(self):
        memo = Memo(sent_at=10.0, alt_before=1, recv_before=3)
        self.assertEqual(run(alt_dishes=0, recv_dishes=4, memo=memo, now=10.5).kind, 'verified')
        self.assertEqual(run(alt_dishes=0, recv_dishes=3, memo=memo, now=10.5).kind, 'wait')
        self.assertEqual(run(alt_dishes=1, recv_dishes=3, memo=memo, now=10.0 + CONFIRM_WAIT).kind, 'unconfirmed')


def gold(alt=ALT, team=SOLO, alt_gold=1753, recv=RECV, recv_gold=5000, memo=None, now=0.0):
    return decide_gold(alt, team, alt_gold, recv, recv_gold, memo or Memo(), now)


class DecideGold(unittest.TestCase):
    def test_trade_all_gold(self):
        d = gold()
        self.assertEqual((d.kind, d.arg), ('trade', 1753))

    def test_no_gold_is_done(self):
        self.assertEqual(gold(alt_gold=0).kind, 'done')

    def test_same_preconditions_as_the_dish(self):
        self.assertEqual(gold(alt=replace(ALT, x=1152.0, y=932.0)).kind, 'navigate')
        self.assertEqual(gold(recv=replace(RECV, busy=True)).kind, 'wait')
        self.assertEqual(gold(team=Team((9, 1), (70, 12), 9)).kind, 'fail')
        self.assertEqual(gold(alt_gold=None).kind, 'wait')

    def test_verified_needs_exact_amount(self):
        memo = Memo(sent_at=10.0, alt_before=1753, recv_before=5000)
        self.assertEqual(gold(alt_gold=0, recv_gold=6753, memo=memo, now=13.2).kind, 'verified')
        self.assertEqual(gold(alt_gold=0, recv_gold=6700, memo=memo, now=11.0).kind, 'wait')
        self.assertEqual(gold(alt_gold=1753, recv_gold=5000, memo=memo, now=11.0).kind, 'wait')

    def test_not_arrived_trades_again(self):
        memo = Memo(sent_at=10.0, alt_before=1753, recv_before=5000)
        self.assertEqual(gold(alt_gold=1753, recv_gold=5000, memo=memo, now=10.0 + CONFIRM_WAIT).kind,
                         'unconfirmed')

    def test_wrong_amount_at_receiver_fails_without_retrading(self):
        memo = Memo(sent_at=10.0, alt_before=1753, recv_before=5000)
        self.assertEqual(gold(alt_gold=0, recv_gold=6700, memo=memo, now=10.0 + CONFIRM_WAIT).kind, 'fail')


class Bag(unittest.TestCase):
    def test_dish_slot_and_count(self):
        bag = (BagSlot(3, 9801, 1), BagSlot(12, 27002, 1), BagSlot(15, 27002, 2))
        self.assertEqual(dish_slot(bag), (12, 1))
        self.assertEqual(dish_count(bag), 3)
        self.assertIsNone(dish_slot(()))
        self.assertIsNone(dish_count(None))


class OfferBody(unittest.TestCase):
    def test_shape(self):
        body = trade_item_offer_body(12, 1)
        self.assertEqual(len(body), 24)
        self.assertEqual(struct.unpack('<IqIII', body), (0, 0, 1, 12, 1))

    def test_range(self):
        with self.assertRaises(ValueError):
            trade_item_offer_body(256, 1)
        with self.assertRaises(ValueError):
            trade_item_offer_body(1, 0)


if __name__ == '__main__':
    unittest.main()


class BagRoomTests(unittest.TestCase):
    def test_empty_slots_and_partial_dish_stacks(self):
        bag = (BagSlot(0, 9801, 5), BagSlot(1, 27002, 99), BagSlot(2, 27002, 40))
        self.assertEqual(bag_room(bag, 40), BagRoom(free_slots=37, capacity=40, dishes=37 * 99 + 59))

    def test_unreadable_is_none(self):
        self.assertIsNone(bag_room(None, 40))
        self.assertIsNone(bag_room((), None))
        self.assertEqual(bag_alarm(None, 3), 'unknown')
        self.assertEqual(bag_text(None), '收货人背包 未知')

    def test_full_bag_with_full_stacks_is_full(self):
        bag = tuple(BagSlot(i, 27002, 99) for i in range(39)) + (BagSlot(39, 9801, 1),)
        room = bag_room(bag, 40)
        self.assertEqual((room.free_slots, room.dishes), (0, 0))
        self.assertEqual(bag_alarm(room, 3), 'full')

    def test_no_free_slot_but_stack_not_full_is_low_not_full(self):
        bag = tuple(BagSlot(i, 27002, 99) for i in range(39)) + (BagSlot(39, 27002, 98),)
        room = bag_room(bag, 40)
        self.assertEqual((room.free_slots, room.dishes), (0, 1))
        self.assertEqual(bag_alarm(room, 3), 'low')

    def test_alarm_threshold(self):
        self.assertEqual(bag_alarm(BagRoom(3, 40, 297), 3), 'low')
        self.assertEqual(bag_alarm(BagRoom(4, 40, 396), 3), 'ok')
        self.assertEqual(bag_alarm(BagRoom(4, 40, 396), 0), 'ok')

    def test_hours_left(self):
        room = BagRoom(10, 40, 990)
        self.assertAlmostEqual(hours_left(room, 100, 3600), 9.9)
        self.assertAlmostEqual(hours_left(room, 50, 1800), 9.9)
        self.assertIsNone(hours_left(room, 0, 3600))       # nothing received yet
        self.assertIsNone(hours_left(room, 5, 300))        # under 10 minutes: no usable rate
        self.assertIsNone(hours_left(None, 100, 3600))

    def test_text(self):
        self.assertEqual(bag_text(BagRoom(5, 40, 520), 5.25), '收货人背包 空 5/40 格 还能收 520 个料理（约 5.2 小时）')
        self.assertEqual(bag_text(BagRoom(5, 40, 520)), '收货人背包 空 5/40 格 还能收 520 个料理')
