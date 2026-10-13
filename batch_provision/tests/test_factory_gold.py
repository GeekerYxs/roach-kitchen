"""Unit tests for the gold stage decision and the trade request bodies (no game needed)."""
import struct
import unittest
from dataclasses import replace

from factory.gold import CONFIRM_WAIT, TRADE_RANGE, Memo, decide
from factory.phase import GOLD_TOPUP_BELOW, TELEPORT_FEE, VILLAGE_MAP
from provisioner.game import trade_accept_body, trade_gold_offer_body, trade_invite_body
from provisioner.world import WorldState

ALT = WorldState(char_id=1, map_id=VILLAGE_MAP, x=1266.0, y=1174.0, target_x=0.0, target_y=0.0, flags=0,
                 busy=False, in_battle=False, nav_active=False, verification=False)
DISP = replace(ALT, char_id=9, x=1338.0, y=1155.0)


def run(alt=ALT, alt_gold=100, disp=DISP, disp_gold=1_000_000, memo=None, now=0.0):
    return decide(alt, alt_gold, disp, disp_gold, memo or Memo(), now, amount=500)


class Gold(unittest.TestCase):
    def test_short_alt_gets_a_trade(self):
        self.assertEqual(run().kind, 'trade')

    def test_enough_gold_is_done(self):
        self.assertEqual(run(alt_gold=GOLD_TOPUP_BELOW).kind, 'done')

    def test_one_teleport_worth_is_topped_up(self):
        self.assertEqual(run(alt_gold=TELEPORT_FEE + 10).kind, 'trade')

    def test_verified_once_alt_has_the_fee(self):
        memo = Memo(sent_at=10.0, gold_before=100)
        self.assertEqual(run(alt_gold=600, memo=memo, now=10.5).kind, 'verified')

    def test_lenient_any_amount_reaching_the_fee_counts(self):
        memo = Memo(sent_at=10.0, gold_before=0)
        self.assertEqual(run(alt_gold=GOLD_TOPUP_BELOW, memo=memo, now=10.5).kind, 'verified')

    def test_wait_then_unconfirmed(self):
        memo = Memo(sent_at=10.0, gold_before=100)
        self.assertEqual(run(memo=memo, now=10.0 + CONFIRM_WAIT - 0.1).kind, 'wait')
        self.assertEqual(run(memo=memo, now=10.0 + CONFIRM_WAIT).kind, 'unconfirmed')

    def test_too_far(self):
        self.assertEqual(run(disp=replace(DISP, x=ALT.x + TRADE_RANGE + 1, y=ALT.y)).kind, 'fail')

    def test_other_map(self):
        self.assertEqual(run(alt=replace(ALT, map_id=130)).kind, 'fail')

    def test_dispatcher_broke(self):
        self.assertEqual(run(disp_gold=499).kind, 'fail')

    def test_busy_either_side_waits(self):
        self.assertEqual(run(alt=replace(ALT, in_battle=True)).kind, 'wait')
        self.assertEqual(run(disp=replace(DISP, verification=True)).kind, 'wait')

    def test_unreadable_waits(self):
        self.assertEqual(run(alt_gold=None).kind, 'wait')


class Bodies(unittest.TestCase):
    def test_shapes_match_the_verified_2026_10_09_trades(self):
        self.assertEqual(trade_invite_body(202851), struct.pack('<I', 202851) + bytes(21))
        self.assertEqual(len(trade_invite_body(1)), 25)
        self.assertEqual(trade_accept_body(202231), struct.pack('<2I', 202231, 0))
        self.assertEqual(trade_gold_offer_body(500), struct.pack('<IqI', 0, 500, 0))
        self.assertEqual(trade_gold_offer_body(0), bytes(16))


if __name__ == '__main__':
    unittest.main()
