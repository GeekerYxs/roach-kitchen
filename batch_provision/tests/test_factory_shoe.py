"""Unit tests for the 飞鞋 record stage decision (no game needed)."""
import unittest
from dataclasses import replace

from factory.phase import VILLAGE_MAP
from factory.shoe import CONFIRM_WAIT, SETTLE, Memo, decide
from provisioner.game import OP_SHOE_RECORD, OP_SHOE_RETURN, SHOE_BODY
from provisioner.world import WorldState

IDLE = WorldState(
    char_id=1, map_id=VILLAGE_MAP, x=1266.0, y=1174.0, target_x=0.0, target_y=0.0, flags=0,
    busy=False, in_battle=False, nav_active=False, verification=False)
ROW = {'shoe_recorded_at': None}
OLD = (0, 0, 0)                       # recorded point before (fresh character: unknown)
HERE = (VILLAGE_MAP, 1266, 1174)


def settled(world=IDLE, start=0.0):
    memo = Memo()
    memo.observe(world, start)
    return memo


class Shoe(unittest.TestCase):
    def test_records_after_standing_still(self):
        self.assertEqual(decide(IDLE, OLD, ROW, settled(), SETTLE).kind, 'record')

    def test_waits_until_settled(self):
        self.assertEqual(decide(IDLE, OLD, ROW, settled(), SETTLE - 0.1).kind, 'wait')

    def test_movement_restarts_the_settle_clock(self):
        memo = settled()
        memo.observe(replace(IDLE, x=1270.0), 5.0)
        self.assertEqual(decide(replace(IDLE, x=1270.0), OLD, ROW, memo, 5.0 + SETTLE - 0.1).kind, 'wait')

    def test_ledger_done(self):
        self.assertEqual(decide(None, None, {'shoe_recorded_at': 1.0}, Memo(), 0.0).kind, 'done')

    def test_verified_when_record_matches_position(self):
        memo = settled()
        memo.sent_at = 10.0
        self.assertEqual(decide(IDLE, HERE, ROW, memo, 10.2).kind, 'verified')

    def test_stale_record_waits_then_unconfirmed(self):
        memo = settled()
        memo.sent_at = 10.0
        lagged = (VILLAGE_MAP, 1280, 1182)
        self.assertEqual(decide(IDLE, lagged, ROW, memo, 10.0 + CONFIRM_WAIT - 0.1).kind, 'wait')
        self.assertEqual(decide(IDLE, lagged, ROW, memo, 10.0 + CONFIRM_WAIT).kind, 'unconfirmed')

    def test_record_on_other_map_does_not_verify(self):
        memo = settled()
        memo.sent_at = 10.0
        self.assertEqual(decide(IDLE, (130, 1266, 1174), ROW, memo, 10.2).kind, 'wait')

    def test_only_in_village(self):
        self.assertEqual(decide(replace(IDLE, map_id=651), OLD, ROW, settled(), SETTLE).kind, 'fail')

    def test_busy_waits(self):
        for s in (replace(IDLE, in_battle=True), replace(IDLE, verification=True), replace(IDLE, nav_active=True)):
            self.assertEqual(decide(s, OLD, ROW, settled(), SETTLE).kind, 'wait', s)

    def test_packets(self):
        self.assertEqual((OP_SHOE_RECORD, OP_SHOE_RETURN, SHOE_BODY), (0x82, 0x83, b'\0\0\0\0'))


if __name__ == '__main__':
    unittest.main()
