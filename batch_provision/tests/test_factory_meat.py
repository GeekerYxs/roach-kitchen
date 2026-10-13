"""Unit tests for the meat stage decision (no game needed)."""
import unittest
from dataclasses import replace

from factory.meat import ACTION, CONFIRM_WAIT, Memo, decide
from factory.phase import MEAT_ITEM, POTATO_ITEM, VILLAGE_MAP
from provisioner.game import use_item_body
from provisioner.world import BagSlot, WorldState

IDLE = WorldState(char_id=1, map_id=VILLAGE_MAP, x=1266.0, y=1174.0, target_x=0.0, target_y=0.0, flags=0,
                  busy=False, in_battle=False, nav_active=False, verification=False)
BAG = (BagSlot(0, POTATO_ITEM, 2), BagSlot(3, MEAT_ITEM, 1))
EMPTY = (BagSlot(0, POTATO_ITEM, 2),)
ROW = {'meat_at': None, 'pending_action': None}


class Meat(unittest.TestCase):
    def test_uses_the_slot_that_holds_meat(self):
        d = decide(IDLE, BAG, ROW, Memo(), 0.0)
        self.assertEqual((d.kind, d.arg.slot), ('use', 3))

    def test_ledger_done_skips_without_reading(self):
        self.assertEqual(decide(None, None, {**ROW, 'meat_at': 5.0}, Memo(), 0.0).kind, 'done')

    def test_loading_waits(self):
        self.assertEqual(decide(None, BAG, ROW, Memo(), 0.0).kind, 'wait')

    def test_count_drop_verifies(self):
        memo = Memo(sent_at=10.0, count_before=1)
        self.assertEqual(decide(IDLE, EMPTY, ROW, memo, 10.5).kind, 'verified')

    def test_waits_for_count_then_gives_up(self):
        memo = Memo(sent_at=10.0, count_before=1)
        self.assertEqual(decide(IDLE, BAG, ROW, memo, 10.0 + CONFIRM_WAIT - 0.1).kind, 'wait')
        self.assertEqual(decide(IDLE, BAG, ROW, memo, 10.0 + CONFIRM_WAIT).kind, 'unconfirmed')

    def test_no_meat_and_never_sent_skips(self):
        self.assertEqual(decide(IDLE, EMPTY, ROW, Memo(), 0.0).kind, 'skip')

    def test_no_meat_after_crash_with_pending_counts_as_eaten(self):
        self.assertEqual(decide(IDLE, EMPTY, {**ROW, 'pending_action': ACTION}, Memo(), 0.0).kind, 'verified')

    def test_wrong_map_fails(self):
        self.assertEqual(decide(replace(IDLE, map_id=81), BAG, ROW, Memo(), 0.0).kind, 'fail')

    def test_busy_states_wait(self):
        for s in (replace(IDLE, in_battle=True), replace(IDLE, busy=True), replace(IDLE, nav_active=True),
                  replace(IDLE, verification=True), replace(IDLE, target_x=1300.0, target_y=1174.0)):
            self.assertEqual(decide(s, BAG, ROW, Memo(), 0.0).kind, 'wait', s)


class Body(unittest.TestCase):
    def test_use_item_body_matches_captured_shape(self):
        body = use_item_body(7)
        self.assertEqual(len(body), 19)
        self.assertEqual(body.hex(), '00000000' '00000000' 'ffffffff' '00000000' '000701')

    def test_slot_range(self):
        with self.assertRaises(ValueError):
            use_item_body(256)


if __name__ == '__main__':
    unittest.main()
