"""Unit tests for stage 7 (coast leaders farm legs and rumps), no game needed."""
import unittest
from pathlib import Path
from dataclasses import replace

from factory.coast import (ARRIVE, ESCAPE_FALLBACK, LANDING, LEAVE_WAIT, NAV_RETRY, NEAR_LEADER, RECORD_SETTLE,
                           RECORD_TRIES, RECORD_WAIT, RENDEZVOUS, RETURN_WAIT, SETTLE, STALL, Approach, Away, Record,
                           NO_GAIN_LIMIT, Walk, choose_spot, decide_approach, decide_away, decide_disband, decide_farm,
                           decide_goto, decide_record, gain_misses)
from factory.config import ROOT, load_settings
from provisioner.world import WorldState

W = WorldState(char_id=900, map_id=81, x=float(RENDEZVOUS[0]), y=float(RENDEZVOUS[1]), target_x=0.0, target_y=0.0,
               flags=0, busy=False, in_battle=False, nav_active=False, verification=False, still_for=5.0)
LEGS = ((678, 1821), (400, 1880))


class Away_(unittest.TestCase):
    def setUp(self):
        self.w = replace(W, map_id=651)

    def test_shoe_first_then_scroll_then_fail(self):
        memo = Away()
        self.assertEqual(decide_away(self.w, True, 7, memo, 0).kind, 'shoe')
        memo.tried.add('shoe')
        d = decide_away(self.w, True, 7, memo, 0)
        self.assertEqual((d.kind, d.arg), ('scroll', 7))
        memo.tried.add('scroll')
        self.assertEqual(decide_away(self.w, True, 7, memo, 0).kind, 'fail')

    def test_shoe_not_on_coast_goes_to_scroll(self):
        self.assertEqual(decide_away(self.w, False, 7, Away(), 0).kind, 'scroll')
        self.assertEqual(decide_away(self.w, False, None, Away(), 0).kind, 'fail')

    def test_sent_waits_then_unconfirmed(self):
        memo = Away(method='shoe', sent_at=0)
        self.assertEqual(decide_away(self.w, True, 7, memo, RETURN_WAIT - 1).kind, 'wait')
        self.assertEqual(decide_away(self.w, True, 7, memo, RETURN_WAIT + 1).kind, 'unconfirmed')

    def test_battle_waits_and_nav_cancels(self):
        self.assertEqual(decide_away(replace(self.w, in_battle=True), True, 7, Away(), 0).kind, 'wait')
        self.assertEqual(decide_away(replace(self.w, nav_active=True), True, 7, Away(), 0).kind, 'cancel_nav')


class Record_(unittest.TestCase):
    def setUp(self):
        self.w = replace(W, x=float(LANDING[0]), y=float(LANDING[1]), still_for=RECORD_SETTLE)
        self.old = (181, 520, 1756)

    def test_already_at_landing(self):
        self.assertEqual(decide_record(self.w, (81, 1150, 930), Record(), 0).kind, 'done')

    def test_records_when_settled_at_landing(self):
        self.assertEqual(decide_record(self.w, self.old, Record(), 0).kind, 'record')
        self.assertEqual(decide_record(replace(self.w, still_for=0.2), self.old, Record(), 0).kind, 'wait')
        self.assertEqual(decide_record(replace(self.w, in_battle=True), self.old, Record(), 0).kind, 'wait')

    def test_not_at_landing_skips(self):
        self.assertEqual(decide_record(W, self.old, Record(), 0).kind, 'skip')
        self.assertEqual(decide_record(replace(self.w, map_id=1), self.old, Record(), 0).kind, 'skip')

    def test_verify_wait_unconfirmed_give_up(self):
        self.assertEqual(decide_record(self.w, (81, *LANDING), Record(sent_at=0, tries=1), 1).kind, 'verified')
        self.assertEqual(decide_record(self.w, self.old, Record(sent_at=0, tries=1), RECORD_WAIT - 1).kind, 'wait')
        self.assertEqual(decide_record(self.w, self.old, Record(sent_at=0, tries=1), RECORD_WAIT + 1).kind,
                         'unconfirmed')
        self.assertEqual(decide_record(self.w, self.old, Record(tries=RECORD_TRIES), 9).kind, 'give_up')


class Goto(unittest.TestCase):
    def test_far_navigates_then_waits_then_stall(self):
        far = replace(W, x=1152.0, y=932.0)
        d = decide_goto(far, RENDEZVOUS, Walk(), 10, '集合点')
        self.assertEqual((d.kind, d.arg), ('navigate', (81, *RENDEZVOUS, None)))
        self.assertEqual(decide_goto(far, RENDEZVOUS, Walk(last_nav=9.5), 10, '集合点').kind, 'wait')
        walking = replace(far, nav_active=True)
        self.assertEqual(decide_goto(walking, RENDEZVOUS, Walk(progress_at=9), 10, '').kind, 'wait')
        self.assertEqual(decide_goto(walking, RENDEZVOUS, Walk(progress_at=0), STALL + 1, '').kind, 'cancel_nav')

    def test_arrive_needs_settle(self):
        self.assertEqual(decide_goto(W, RENDEZVOUS, Walk(), 0, '').kind, 'arrived')
        self.assertEqual(decide_goto(replace(W, still_for=SETTLE / 2), RENDEZVOUS, Walk(), 0, '').kind, 'wait')
        self.assertEqual(decide_goto(replace(W, nav_active=True), RENDEZVOUS, Walk(), 0, '').kind, 'cancel_nav')

    def test_battle_and_lost(self):
        self.assertEqual(decide_goto(replace(W, in_battle=True), RENDEZVOUS, Walk(), 0, '').kind, 'battle')
        self.assertEqual(decide_goto(replace(W, map_id=1), RENDEZVOUS, Walk(), 0, '').kind, 'lost')


class Spot(unittest.TestCase):
    def test_order(self):
        self.assertEqual(choose_spot([(10, 0), (9, 20)]), 'legs')
        self.assertEqual(choose_spot([(10, 0), (12, 20)]), 'rumps')
        self.assertEqual(choose_spot([(10, 20), (11, 25)]), 'done')
        self.assertEqual(choose_spot([]), 'done')

    def test_materials_done_farms_exp_until_18(self):
        done = [(10, 20), (11, 25)]
        self.assertEqual(choose_spot(done, [12, 18]), 'level')
        self.assertEqual(choose_spot(done, [18, None]), 'level')     # unread: not there yet
        self.assertEqual(choose_spot(done, [18, 19]), 'done')
        self.assertEqual(choose_spot([(9, 20), (10, 20)], [18, 18]), 'legs')    # materials still come first
        self.assertEqual(choose_spot([(10, 20), (10, 3)], [12, 12]), 'rumps')

    def test_exp_farming_counts_no_misses(self):
        self.assertEqual(gain_misses({1: (10, 20)}, {1: (10, 20)}, 'level', {1: 2}), {1: 2})


class GainMisses(unittest.TestCase):
    def test_member_left_out_while_teammates_gain_counts_up(self):
        misses = {}
        before = {1: (0, 0), 2: (3, 0), 3: (3, 0)}
        for n in range(1, NO_GAIN_LIMIT + 1):
            after = {1: (0, 0), 2: (3 + n, 0), 3: (3 + n, 0)}
            misses = gain_misses(before, after, 'legs', misses)
            before = after
        self.assertEqual(misses, {1: NO_GAIN_LIMIT, 2: 0, 3: 0})

    def test_battle_without_target_changes_nothing(self):
        same = {1: (0, 0), 2: (3, 0)}
        self.assertEqual(gain_misses(same, same, 'legs', {1: 2}), {1: 2})

    def test_gain_resets(self):
        self.assertEqual(gain_misses({1: (2, 0), 2: (2, 0)}, {1: (3, 0), 2: (3, 0)}, 'legs', {1: 2}), {1: 0, 2: 0})

    def test_member_that_has_enough_is_not_counted(self):
        # farming rumps: member 1 is done with rumps, member 2 gains
        m = gain_misses({1: (10, 20), 2: (10, 5)}, {1: (10, 20), 2: (10, 6)}, 'rumps', {})
        self.assertEqual(m, {2: 0})

    def test_new_member_without_earlier_count_is_skipped(self):
        self.assertEqual(gain_misses({}, {1: (0, 0), 2: (1, 0)}, 'legs', {}), {})


class Farm(unittest.TestCase):
    def test_walks_to_current_point_then_alternates(self):
        memo = Walk(spot='legs')
        d = decide_farm(W, LEGS, memo, 10)
        self.assertEqual((d.kind, d.arg), ('navigate', (81, *LEGS[0], 0)))
        at_a = replace(W, x=float(LEGS[0][0]), y=float(LEGS[0][1] + ARRIVE - 1))
        d = decide_farm(at_a, LEGS, memo, 10)
        self.assertEqual((d.kind, d.arg), ('navigate', (81, *LEGS[1], 1)))
        memo.patrol = 1
        at_b = replace(W, x=float(LEGS[1][0]), y=float(LEGS[1][1]))
        self.assertEqual(decide_farm(at_b, LEGS, memo, 10).arg, (81, *LEGS[0], 0))

    def test_battle_lost_busy(self):
        memo = Walk(spot='legs')
        self.assertEqual(decide_farm(replace(W, in_battle=True), LEGS, memo, 0).kind, 'battle')
        self.assertEqual(decide_farm(replace(W, map_id=1), LEGS, memo, 0).kind, 'lost')
        self.assertEqual(decide_farm(replace(W, busy=True), LEGS, memo, 0).kind, 'wait')
        self.assertEqual(decide_farm(W, LEGS, Walk(spot='legs', last_nav=10 - NAV_RETRY / 2), 10).kind, 'wait')


class Approach_(unittest.TestCase):
    def setUp(self):
        self.far = replace(W, char_id=7, x=1780.0 - 600, y=1370.0)

    def test_near_and_far(self):
        near = replace(W, char_id=7, x=W.x + NEAR_LEADER - 10)
        self.assertEqual(decide_approach(near, W, Approach(), 0).kind, 'near')
        self.assertEqual(decide_approach(replace(near, nav_active=True), W, Approach(), 0).kind, 'cancel_nav')
        d = decide_approach(self.far, W, Approach(), 10)
        self.assertEqual((d.kind, d.arg), ('navigate', (81, *RENDEZVOUS)))

    def test_escapes_battles(self):
        fight = replace(self.far, in_battle=True, my_sp=0)
        self.assertEqual(decide_approach(fight, W, Approach(), 0).kind, 'escape')
        memo = Approach(last_sp=0, last_escape=0)
        self.assertEqual(decide_approach(fight, W, memo, 1).kind, 'wait')
        self.assertEqual(decide_approach(fight, W, memo, ESCAPE_FALLBACK + 1).kind, 'escape')
        self.assertEqual(decide_approach(replace(fight, my_sp=1), W, memo, 1).kind, 'escape')

    def test_other_map_fails(self):
        self.assertEqual(decide_approach(replace(self.far, map_id=1), W, Approach(), 0).kind, 'fail')


class Disband(unittest.TestCase):
    def test_leader_leaves_first(self):
        self.assertEqual(decide_disband(True, 4, None, None, 0).kind, 'leader_leave')

    def test_team_gone(self):
        self.assertEqual(decide_disband(False, 0, 0, None, 1).kind, 'done')

    def test_members_leave_after_wait_then_fail(self):
        self.assertEqual(decide_disband(False, 2, 0, None, LEAVE_WAIT - 1).kind, 'wait')
        self.assertEqual(decide_disband(False, 2, 0, None, LEAVE_WAIT + 1).kind, 'members_leave')
        self.assertEqual(decide_disband(False, 2, 0, 10, 10 + LEAVE_WAIT - 1).kind, 'wait')
        self.assertEqual(decide_disband(False, 2, 0, 10, 10 + LEAVE_WAIT + 1).kind, 'fail')

    def test_leader_already_out_on_restart(self):
        self.assertEqual(decide_disband(False, 3, None, None, 100).kind, 'members_leave')


class Settings_(unittest.TestCase):
    def test_coast_settings_load(self):
        s = load_settings(ROOT / 'factory.toml')
        self.assertEqual(s.coast_legs_patrol[0], (678, 1821))
        self.assertEqual(s.coast_rumps_patrol[0], (1170, 2883))
        self.assertTrue(1 <= s.coast_team_size <= 4)
        self.assertEqual(len(s.coast_level_patrol), 2)
        self.assertGreaterEqual(s.coast_farm_timeout, 3600)        # farming on to 18 takes hours

    def test_switches_set_the_phase_defaults(self):
        import tempfile
        from factory import phase
        old, old_level = phase.DISH_TRADE, phase.HANDIN_LEVEL
        try:
            self.assertFalse(load_settings(ROOT / 'factory.toml').dish_trade)     # 2026-10-25: 料理不能交易
            self.assertFalse(phase.DISH_TRADE)
            with tempfile.TemporaryDirectory() as d:
                cfg = Path(d) / 'f.toml'
                cfg.write_text('[factory]\ndish_trade = true\n', 'utf-8')
                self.assertTrue(load_settings(cfg).dish_trade)
                self.assertTrue(phase.DISH_TRADE)
                cfg.write_text('[factory]\ndish_trade = "no"\n', 'utf-8')
                with self.assertRaises(ValueError):
                    load_settings(cfg)
                self.assertEqual(load_settings(ROOT / 'factory.toml').handin_level, phase.HANDIN_LEVEL)
                cfg.write_text('[factory]\nhandin_level = 15\n', 'utf-8')
                self.assertEqual(load_settings(cfg).handin_level, 15)
                self.assertEqual(phase.HANDIN_LEVEL, 15)
                self.assertEqual(choose_spot([(10, 20)], [15]), 'done')       # the coast follows the setting
                self.assertEqual(choose_spot([(10, 20)], [14]), 'level')
                for bad in ('10', '"18"', 'true', '18.5'):
                    cfg.write_text(f'[factory]\nhandin_level = {bad}\n', 'utf-8')
                    with self.assertRaises(ValueError):
                        load_settings(cfg)
        finally:
            phase.DISH_TRADE, phase.HANDIN_LEVEL = old, old_level


if __name__ == '__main__':
    unittest.main()
