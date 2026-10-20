"""Unit tests for the treasury top-ups (no game needed)."""
import unittest
from dataclasses import replace

from factory.supply import SupplySettings, due
from factory.treasury import (CONFIRM_WAIT, Memo, Treasury, TreasurySettings, chunks, decide, load_treasury,
                              shortfall)
from provisioner.world import WorldState

S = load_treasury({})
RECV = WorldState(char_id=7, map_id=81, x=1780.0, y=1370.0, target_x=1780.0, target_y=1370.0, flags=0,
                  busy=False, in_battle=False, nav_active=False, verification=False, still_for=5.0)
ME = replace(RECV, char_id=1, x=1760.0, y=1360.0)


class Shortfall(unittest.TestCase):
    def test_below_low_tops_up_to_target(self):
        self.assertEqual(shortfall('dispatcher', 150_000, S), 850_000)
        self.assertEqual(shortfall('dispatcher', 200_000, S), 0)
        self.assertEqual(shortfall('well', 5_000, S), 95_000)

    def test_no_rule_unknown_gold_or_off(self):
        self.assertEqual(shortfall('receiver', 0, S), 0)
        self.assertEqual(shortfall('well', None, S), 0)
        self.assertEqual(shortfall('well', 0, replace(S, enabled=False)), 0)


class Chunks(unittest.TestCase):
    def test_split_by_max_per_trade(self):
        self.assertEqual(chunks(2_500_000, 10 ** 8, S), [1_000_000, 1_000_000, 500_000])

    def test_reserve_is_kept(self):
        self.assertEqual(chunks(850_000, 900_000, S), [400_000])
        self.assertEqual(chunks(850_000, 400_000, S), [])


class Decide(unittest.TestCase):
    def run_(self, me=ME, treasury=RECV, me_gold=1000, t_gold=4_000_000, amount=850_000, memo=None, now=0.0):
        return decide(me, treasury, me_gold, t_gold, amount, memo or Memo(), now)

    def test_trade_when_next_to_each_other_and_idle(self):
        self.assertEqual(self.run_().kind, 'trade')

    def test_preconditions(self):
        self.assertEqual(self.run_(me=None).kind, 'wait')
        self.assertEqual(self.run_(me=replace(ME, map_id=1)).kind, 'fail')
        self.assertEqual(self.run_(me=replace(ME, x=1152.0, y=932.0)).kind, 'fail')
        self.assertEqual(self.run_(treasury=replace(RECV, in_battle=True)).kind, 'wait')

    def test_verified_with_quiz_slack(self):
        memo = Memo(sent_at=10.0, me_before=1000, treasury_before=4_000_000)
        self.assertEqual(self.run_(me_gold=851_000, t_gold=3_150_000, memo=memo, now=11).kind, 'verified')
        self.assertEqual(self.run_(me_gold=851_100, t_gold=3_150_100, memo=memo, now=11).kind, 'verified')
        self.assertEqual(self.run_(me_gold=1000, t_gold=4_000_000, memo=memo, now=11).kind, 'wait')
        self.assertEqual(self.run_(me_gold=1000, t_gold=4_000_000, memo=memo, now=10 + CONFIRM_WAIT).kind,
                         'unconfirmed')

    def test_one_sided_change_is_not_verified(self):
        memo = Memo(sent_at=10.0, me_before=1000, treasury_before=4_000_000)
        self.assertEqual(self.run_(me_gold=851_000, t_gold=4_000_000, memo=memo, now=10 + CONFIRM_WAIT).kind,
                         'unconfirmed')


class Config(unittest.TestCase):
    def test_override_and_validation(self):
        s = load_treasury({'treasury': {'reserve': 100, 'dispatcher': [1, 2]}})
        self.assertEqual((s.reserve, s.rules['dispatcher'], s.rules['well']), (100, (1, 2), (20_000, 100_000)))
        with self.assertRaises(ValueError):
            load_treasury({'treasury': {'well': [5, 1]}})
        with self.assertRaises(ValueError):
            load_treasury({'treasury': {'max_per_trade': 0}})


class Due(unittest.TestCase):
    def test_low_gold_alone_starts_an_errand(self):
        t = Treasury(S, lambda conn: None)
        off = SupplySettings(enabled=False)
        self.assertTrue(due('dispatcher', (), 40, off, 100_000, t))
        self.assertFalse(due('dispatcher', (), 40, off, 300_000, t))
        self.assertFalse(due('dispatcher', (), 40, off, 100_000, None))


if __name__ == '__main__':
    unittest.main()
