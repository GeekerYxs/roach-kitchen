"""Unit tests for factory.phase (no game needed).

Run: python -X utf8 -m unittest discover -s tests -v   (from batch_provision/)
"""
import unittest
from dataclasses import replace

from factory import phase as P
from factory.phase import AltObs, Ledger, derive_phase, return_method, should_eat_potato

WELL_LEADER, DISPATCHER, COAST_LEADER, RECEIVER, STRANGER = 900, 901, 902, 903, 777
STATIONS = {WELL_LEADER: P.WELL, DISPATCHER: P.DISPATCHER, COAST_LEADER: P.COAST, RECEIVER: P.RECEIVER}

FRESH = AltObs(char_id=1, map_id=P.VILLAGE_MAP, level=1, gold=0, team_leader=0, quest=P.QUEST_NONE,
               scrolls=1, potatoes=2)
READY = Ledger(meat_at=10.0, shoe_recorded_at=11.0)
AT_11 = replace(FRESH, level=11, gold=500)
ON_COAST = replace(AT_11, map_id=P.COAST_MAP, gold=310)
FARMING = replace(ON_COAST, quest=P.QUEST_ACTIVE)


def phase(obs, ledger=READY, dish_trade=True):
    return derive_phase(obs, ledger, STATIONS, dish_trade)


class Village(unittest.TestCase):
    def test_novice(self):
        self.assertEqual(phase(replace(FRESH, map_id=P.NOVICE_MAP), Ledger()).phase, P.NOVICE)

    def test_fresh_eats_meat_first(self):
        self.assertEqual(phase(FRESH, Ledger()).phase, P.EAT_MEAT)

    def test_then_records_shoe(self):
        self.assertEqual(phase(FRESH, Ledger(meat_at=1.0)).phase, P.RECORD_SHOE)

    def test_then_queues_for_well_and_asks_gold(self):
        p = phase(FRESH)
        self.assertEqual(p.phase, P.QUEUE_WELL)
        self.assertTrue(p.needs_gold)       # gold is given while waiting, off the critical path

    def test_funded_alt_needs_no_gold(self):
        self.assertFalse(phase(replace(FRESH, gold=500)).needs_gold)

    def test_unreadable_gold_is_not_a_gold_request(self):
        self.assertFalse(phase(replace(FRESH, gold=None)).needs_gold)

    def test_quarantine_wins(self):
        self.assertEqual(phase(FRESH, replace(READY, quarantined=True)).phase, P.QUARANTINED)


class Well(unittest.TestCase):
    def test_in_well_team_is_leveling_on_any_map(self):
        for m in (P.VILLAGE_MAP, P.MEADOW_MAP, P.WELL_MAP):
            self.assertEqual(phase(replace(FRESH, map_id=m, level=5, team_leader=WELL_LEADER)).phase, P.LEVELING)

    def test_reaching_11_in_team_waits_for_the_rest(self):
        self.assertEqual(phase(replace(AT_11, map_id=P.WELL_MAP, team_leader=WELL_LEADER)).phase, P.LEVELING)

    def test_lost_below_11_goes_home(self):
        for m in (P.MEADOW_MAP, P.WELL_MAP):
            self.assertEqual(phase(replace(FRESH, map_id=m, level=7)).phase, P.RETURN_HOME)

    def test_back_home_below_11_requeues_with_progress(self):
        p = phase(replace(FRESH, level=7))
        self.assertEqual(p.phase, P.QUEUE_WELL)

    def test_11_in_well_after_scroll_disband_goes_home(self):
        self.assertEqual(phase(replace(AT_11, map_id=P.WELL_MAP)).phase, P.RETURN_HOME)

    def test_stranger_team_is_left(self):
        self.assertEqual(phase(replace(FRESH, team_leader=STRANGER)).phase, P.LEAVE_TEAM)

    def test_low_level_in_dispatcher_team_is_left(self):
        self.assertEqual(phase(replace(FRESH, team_leader=DISPATCHER)).phase, P.LEAVE_TEAM)


class Transport(unittest.TestCase):
    def test_11_in_village_queues_for_transport(self):
        p = phase(AT_11)
        self.assertEqual((p.phase, p.needs_gold), (P.QUEUE_TRANSPORT, False))

    def test_11_without_gold_waits_for_gold_in_queue(self):
        p = phase(replace(AT_11, gold=100))
        self.assertEqual((p.phase, p.needs_gold), (P.QUEUE_TRANSPORT, True))

    def test_in_dispatcher_team_in_village(self):
        self.assertEqual(phase(replace(AT_11, team_leader=DISPATCHER)).phase, P.TRANSPORTING)

    def test_arrived_still_in_dispatcher_team_waits_for_disband(self):
        self.assertEqual(phase(replace(ON_COAST, team_leader=DISPATCHER)).phase, P.WAIT_DISBAND)

    def test_11_elsewhere_goes_home(self):
        self.assertEqual(phase(replace(AT_11, map_id=P.MEADOW_MAP)).phase, P.RETURN_HOME)


class Coast(unittest.TestCase):
    def test_arrived_accepts_quest(self):
        self.assertEqual(phase(ON_COAST).phase, P.ACCEPT_QUEST)

    def test_must_leave_team_before_accepting(self):
        self.assertEqual(phase(replace(ON_COAST, team_leader=COAST_LEADER)).phase, P.LEAVE_TEAM)

    def test_quest_active_queues_for_coast(self):
        self.assertEqual(phase(FARMING).phase, P.QUEUE_COAST)

    def test_partial_progress_requeues(self):
        p = phase(replace(FARMING, legs=9, rumps=2))
        self.assertEqual(p.phase, P.QUEUE_COAST)

    def test_in_coast_team_is_farming_even_when_done(self):
        # the team walks back to 海子 together; it disbands there
        done = replace(FARMING, legs=10, rumps=20, team_leader=COAST_LEADER)
        self.assertEqual(phase(done).phase, P.FARMING)

    def test_done_and_alone_hands_in(self):
        self.assertEqual(phase(replace(FARMING, legs=10, rumps=21, level=P.HANDIN_LEVEL)).phase, P.HANDIN)
        self.assertEqual(phase(replace(FARMING, legs=10, rumps=20, level=25)).phase, P.HANDIN)

    def test_materials_done_below_18_farms_on(self):
        p = phase(replace(FARMING, legs=10, rumps=21, level=P.HANDIN_LEVEL - 1))
        self.assertEqual(p.phase, P.QUEUE_COAST)
        self.assertIn('18', p.reason)
        in_team = replace(FARMING, legs=10, rumps=20, level=12, team_leader=COAST_LEADER)
        self.assertEqual(phase(in_team).phase, P.FARMING)
        self.assertEqual(phase(replace(in_team, team_leader=DISPATCHER)).phase, P.WAIT_DISBAND)

    def test_legs_alone_are_not_enough(self):
        self.assertEqual(phase(replace(FARMING, legs=10, rumps=19)).phase, P.QUEUE_COAST)

    def test_full_bag_without_a_material_sells_first(self):
        # live 2026-10-21: mw302r6 came out of the well with a full bag and farmed at 腿0 屁股0 for 2 h
        p = phase(replace(FARMING, bag_free=0, junk=12))
        self.assertEqual(p.phase, P.SELL_JUNK)
        self.assertEqual(phase(replace(FARMING, legs=4, bag_free=0, junk=12)).phase, P.SELL_JUNK)

    def test_full_bag_with_nothing_to_sell_waits_for_a_human(self):
        self.assertEqual(phase(replace(FARMING, bag_free=0, junk=0)).phase, P.QUARANTINED)

    def test_full_bag_holding_both_materials_still_farms(self):
        # both stacks exist: drops only grow them
        self.assertEqual(phase(replace(FARMING, legs=3, rumps=1, bag_free=0)).phase, P.QUEUE_COAST)
        self.assertEqual(phase(replace(FARMING, bag_free=1)).phase, P.QUEUE_COAST)
        self.assertEqual(phase(replace(FARMING, bag_free=None)).phase, P.QUEUE_COAST)

    def test_full_bag_in_coast_team_is_still_farming(self):
        # the coast leader puts it out of the team (coast.CoastRun.screen); only then it sells
        self.assertEqual(phase(replace(FARMING, team_leader=COAST_LEADER, bag_free=0, junk=5)).phase, P.FARMING)

    def test_died_at_coast_goes_back_by_transport(self):
        died = replace(FARMING, map_id=P.VILLAGE_MAP, legs=4)
        self.assertEqual(phase(died).phase, P.QUEUE_TRANSPORT)

    def test_died_without_gold_asks_gold(self):
        died = replace(FARMING, map_id=P.VILLAGE_MAP, gold=120)
        self.assertTrue(phase(died).needs_gold)


class Finish(unittest.TestCase):
    def test_dish_goes_to_receiver(self):
        self.assertEqual(phase(replace(FARMING, quest=P.QUEST_DONE, dishes=1)).phase, P.QUEUE_RECEIVER)

    def test_junk_is_sold_once_before_the_receiver(self):
        handed_in = replace(FARMING, quest=P.QUEST_DONE, dishes=1, junk=7)
        self.assertEqual(phase(handed_in).phase, P.SELL_JUNK)
        self.assertEqual(phase(handed_in, replace(READY, sold_at=20.0)).phase, P.QUEUE_RECEIVER)   # refused leftovers
        self.assertEqual(phase(replace(handed_in, junk=0)).phase, P.QUEUE_RECEIVER)
        self.assertEqual(phase(replace(handed_in, team_leader=COAST_LEADER)).phase, P.LEAVE_TEAM)

    def test_dish_in_team_leaves_first(self):
        obs = replace(FARMING, quest=P.QUEST_DONE, dishes=1, team_leader=COAST_LEADER)
        self.assertEqual(phase(obs).phase, P.LEAVE_TEAM)

    def test_dish_in_village_goes_back_to_coast(self):
        obs = replace(AT_11, quest=P.QUEST_DONE, dishes=1)
        self.assertEqual(phase(obs).phase, P.QUEUE_TRANSPORT)

    def test_dish_and_gold_handed_over_deletes(self):
        self.assertEqual(phase(replace(FARMING, quest=P.QUEST_DONE, gold=0)).phase, P.DELETE)

    def test_gold_left_goes_back_to_receiver(self):
        # crash between the 料理 trade and the gold trade: not the delete yet
        p = phase(replace(FARMING, quest=P.QUEST_DONE, gold=1753))
        self.assertEqual(p.phase, P.QUEUE_RECEIVER)
        self.assertIn('1753', p.reason)
        self.assertEqual(phase(replace(FARMING, quest=P.QUEST_DONE, gold=None)).phase, P.QUEUE_RECEIVER)

    def test_gold_left_in_team_leaves_first(self):
        obs = replace(FARMING, quest=P.QUEST_DONE, gold=1753, team_leader=COAST_LEADER)
        self.assertEqual(phase(obs).phase, P.LEAVE_TEAM)

    def test_gold_left_off_the_coast_deletes(self):
        self.assertEqual(phase(replace(AT_11, quest=P.QUEST_DONE, gold=900)).phase, P.DELETE)


class NoDishTrade(unittest.TestCase):
    """factory.toml dish_trade = false: the 料理 stays in the bag, the receiver only collects the gold."""
    HANDED_IN = replace(FARMING, quest=P.QUEST_DONE, dishes=1, gold=1753)

    def off(self, obs, ledger=READY):
        return phase(obs, ledger, dish_trade=False)

    def test_gold_goes_to_receiver_with_the_dish_in_the_bag(self):
        p = self.off(self.HANDED_IN)
        self.assertEqual(p.phase, P.QUEUE_RECEIVER)
        self.assertIn('1753', p.reason)

    def test_gold_handed_over_deletes_with_the_dish(self):
        p = self.off(replace(self.HANDED_IN, gold=0))
        self.assertEqual(p.phase, P.DELETE)
        self.assertIn('随角色删除', p.reason)

    def test_junk_is_sold_once_before_the_receiver(self):
        obs = replace(self.HANDED_IN, junk=7)
        self.assertEqual(self.off(obs).phase, P.SELL_JUNK)
        self.assertEqual(self.off(obs, replace(READY, sold_at=20.0)).phase, P.QUEUE_RECEIVER)
        self.assertEqual(self.off(replace(obs, team_leader=COAST_LEADER)).phase, P.LEAVE_TEAM)

    def test_gold_unread_waits_for_the_receiver(self):
        self.assertEqual(self.off(replace(self.HANDED_IN, gold=None)).phase, P.QUEUE_RECEIVER)

    def test_gold_off_the_coast_goes_back(self):
        self.assertEqual(self.off(replace(self.HANDED_IN, map_id=P.VILLAGE_MAP)).phase, P.QUEUE_TRANSPORT)
        self.assertEqual(self.off(replace(self.HANDED_IN, map_id=P.WELL_MAP)).phase, P.RETURN_HOME)

    def test_before_the_hand_in_nothing_changes(self):
        for obs in (FARMING, replace(FARMING, legs=10, rumps=20), FRESH, AT_11):
            self.assertEqual(self.off(obs), phase(obs))

    def test_module_switch_is_the_default(self):
        old = P.DISH_TRADE
        try:
            P.DISH_TRADE = False
            self.assertEqual(derive_phase(replace(self.HANDED_IN, gold=0), READY, STATIONS).phase, P.DELETE)
            P.DISH_TRADE = True
            self.assertEqual(derive_phase(replace(self.HANDED_IN, gold=0), READY, STATIONS).phase, P.QUEUE_RECEIVER)
        finally:
            P.DISH_TRADE = old


class ReturnHome(unittest.TestCase):
    def test_shoe_first(self):
        self.assertEqual(return_method(FRESH, READY, now=100.0), 'shoe')

    def test_shoe_cooling_down_uses_scroll(self):
        led = replace(READY, shoe_used_at=100.0)
        self.assertEqual(return_method(FRESH, led, now=100.0 + P.SHOE_COOLDOWN - 1), 'scroll')

    def test_shoe_ready_again_after_an_hour(self):
        led = replace(READY, shoe_used_at=100.0)
        self.assertEqual(return_method(FRESH, led, now=100.0 + P.SHOE_COOLDOWN), 'shoe')

    def test_no_shoe_no_scroll_walks(self):
        self.assertEqual(return_method(replace(FRESH, scrolls=0), Ledger(), now=0.0), 'walk')


class Potato(unittest.TestCase):
    def test_first_potato(self):
        self.assertTrue(should_eat_potato(FRESH, READY, now=0.0))

    def test_not_again_while_the_pair_lasts(self):
        self.assertEqual(P.POTATO_RENEW, 2 * 3600 - 300)
        self.assertFalse(should_eat_potato(FRESH, replace(READY, potato_at=0.0), now=P.POTATO_RENEW - 1))

    def test_again_after_the_pair_ran_out(self):
        self.assertTrue(should_eat_potato(FRESH, replace(READY, potato_at=0.0), now=P.POTATO_RENEW))

    def test_two_in_a_row_at_formation(self):
        just_ate = replace(READY, potato_at=100.0)
        self.assertTrue(should_eat_potato(replace(FRESH, potatoes=1), just_ate, now=105.0, eaten=1))
        self.assertFalse(should_eat_potato(FRESH, just_ate, now=110.0, eaten=P.POTATOES_AT_START))
        self.assertFalse(should_eat_potato(replace(FRESH, potatoes=0), just_ate, now=105.0, eaten=1))

    def test_none_left_or_already_11(self):
        self.assertFalse(should_eat_potato(replace(FRESH, potatoes=0), READY, now=0.0))
        self.assertFalse(should_eat_potato(AT_11, READY, now=0.0))


if __name__ == '__main__':
    unittest.main()
