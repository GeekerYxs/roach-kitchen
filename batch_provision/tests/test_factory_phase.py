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


def phase(obs, ledger=READY):
    return derive_phase(obs, ledger, STATIONS)


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
        self.assertEqual(phase(replace(FARMING, legs=10, rumps=21)).phase, P.HANDIN)

    def test_legs_alone_are_not_enough(self):
        self.assertEqual(phase(replace(FARMING, legs=10, rumps=19)).phase, P.QUEUE_COAST)

    def test_died_at_coast_goes_back_by_transport(self):
        died = replace(FARMING, map_id=P.VILLAGE_MAP, legs=4)
        self.assertEqual(phase(died).phase, P.QUEUE_TRANSPORT)

    def test_died_without_gold_asks_gold(self):
        died = replace(FARMING, map_id=P.VILLAGE_MAP, gold=120)
        self.assertTrue(phase(died).needs_gold)


class Finish(unittest.TestCase):
    def test_dish_goes_to_receiver(self):
        self.assertEqual(phase(replace(FARMING, quest=P.QUEST_DONE, dishes=1)).phase, P.QUEUE_RECEIVER)

    def test_dish_in_team_leaves_first(self):
        obs = replace(FARMING, quest=P.QUEST_DONE, dishes=1, team_leader=COAST_LEADER)
        self.assertEqual(phase(obs).phase, P.LEAVE_TEAM)

    def test_dish_in_village_goes_back_to_coast(self):
        obs = replace(AT_11, quest=P.QUEST_DONE, dishes=1)
        self.assertEqual(phase(obs).phase, P.QUEUE_TRANSPORT)

    def test_dish_handed_over_deletes(self):
        self.assertEqual(phase(replace(FARMING, quest=P.QUEST_DONE)).phase, P.DELETE)


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

    def test_not_again_within_55_min(self):
        self.assertFalse(should_eat_potato(FRESH, replace(READY, potato_at=0.0), now=P.POTATO_RENEW - 1))

    def test_second_after_55_min(self):
        self.assertTrue(should_eat_potato(FRESH, replace(READY, potato_at=0.0), now=P.POTATO_RENEW))

    def test_none_left_or_already_11(self):
        self.assertFalse(should_eat_potato(replace(FRESH, potatoes=0), READY, now=0.0))
        self.assertFalse(should_eat_potato(AT_11, READY, now=0.0))


if __name__ == '__main__':
    unittest.main()
