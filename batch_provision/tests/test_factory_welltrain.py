"""Unit tests for stage 4b (well travel, battle commands, talent points, return), no game needed."""
import struct
import unittest
from dataclasses import replace

from factory.phase import MEADOW_MAP, SCROLL_ITEM, VILLAGE_MAP, WELL_MAP
from factory.welltrain import (CLICK_WAIT, ENTRANCE, ENTRANCE_NPC, FOLLOW_WAIT, MAX_CLICKS, MAX_SKILL_SENDS, NAV_RETRY,
                               PATROL, RESEND, RETURN_WAIT, SETTLE, STALL, TALENT_BACKOFF, TALENT_MISSES, TALENT_WAIT,
                               Fight, Home, Route, Talent, decide_battle, decide_fighter, decide_leader_return,
                               decide_member_return, decide_route, decide_talent, scroll_slot)
from provisioner.game import talent_body
from provisioner.world import (STALE_TARGET_AFTER, BagSlot, Battle, Dialog, Fighter, Team, WorldState, _client_pos,
                               _still_for)

LEADER = 900
W = WorldState(char_id=LEADER, map_id=VILLAGE_MAP, x=1266.0, y=1174.0, target_x=0.0, target_y=0.0, flags=0,
               busy=False, in_battle=False, nav_active=False, verification=False)
AT_ENTRANCE = replace(W, map_id=MEADOW_MAP, x=ENTRANCE[0], y=ENTRANCE[1])
IN_WELL = replace(W, map_id=WELL_MAP, x=2160.0, y=1580.0)


def route_at(w, **kw):
    """Memo that has already seen w at t=0 (the first sight of a map resets the per-map fields), then kw."""
    memo = Route()
    memo.observe(w, 0.0)
    for k, v in kw.items():
        setattr(memo, k, v)
    return memo


class RouteTests(unittest.TestCase):
    def test_village_navigates_to_meadow_entrance(self):
        d = decide_route(W, [VILLAGE_MAP], route_at(W), 100)
        self.assertEqual((d.kind, d.arg), ('navigate', (MEADOW_MAP, *ENTRANCE, None)))

    def test_no_renavigate_too_soon_and_wait_while_walking(self):
        memo = route_at(W, last_nav=99.5)
        self.assertEqual(decide_route(W, [], memo, 100).kind, 'wait')
        walking = replace(W, nav_active=True)
        memo = route_at(walking)
        self.assertEqual(decide_route(walking, [], memo, 1).kind, 'wait')

    def test_stalled_navigation_is_cancelled(self):
        walking = replace(W, nav_active=True)
        memo = route_at(walking)
        self.assertEqual(decide_route(walking, [], memo, STALL + 1).kind, 'cancel_nav')

    def test_battle_and_verification(self):
        self.assertEqual(decide_route(replace(W, in_battle=True), [], route_at(W), 1).kind, 'battle')
        self.assertEqual(decide_route(replace(W, verification=True), [], route_at(W), 1).kind, 'wait')

    def test_entrance_clicks_after_settling_with_members_there(self):
        memo = route_at(AT_ENTRANCE)
        self.assertEqual(decide_route(AT_ENTRANCE, [MEADOW_MAP], memo, SETTLE / 2).kind, 'wait')
        d = decide_route(AT_ENTRANCE, [MEADOW_MAP] * 4, memo, SETTLE + 0.1)
        self.assertEqual((d.kind, d.arg), ('click', ENTRANCE_NPC))

    def test_entrance_waits_for_followers_then_goes_anyway(self):
        memo = route_at(AT_ENTRANCE)
        self.assertEqual(decide_route(AT_ENTRANCE, [VILLAGE_MAP, MEADOW_MAP], memo, 5).kind, 'wait')
        self.assertEqual(decide_route(AT_ENTRANCE, [VILLAGE_MAP], memo, FOLLOW_WAIT + 1).kind, 'click')

    def test_entrance_cancels_navigation_first(self):
        w = replace(AT_ENTRANCE, nav_active=True)
        self.assertEqual(decide_route(w, [], route_at(w), 5).kind, 'cancel_nav')

    def test_click_waits_then_gives_up(self):
        memo = route_at(AT_ENTRANCE, clicked_at=10.0, clicks=1)
        self.assertEqual(decide_route(AT_ENTRANCE, [], memo, 10 + CLICK_WAIT - 1).kind, 'wait')
        self.assertEqual(decide_route(AT_ENTRANCE, [], memo, 10 + CLICK_WAIT + 1).kind, 'click')
        memo = route_at(AT_ENTRANCE, clicked_at=10.0, clicks=MAX_CLICKS)
        self.assertEqual(decide_route(AT_ENTRANCE, [], memo, 100).kind, 'fail')

    def test_entrance_dialog_option(self):
        w = replace(AT_ENTRANCE, dialog=Dialog('', ((1, '进入阴森古井'), (0, '离开'))))
        d = decide_route(w, [], route_at(w), 5)
        self.assertEqual((d.kind, d.arg), ('select', 1))
        w = replace(AT_ENTRANCE, dialog=Dialog('', ((1, '甲'), (2, '乙'), (0, '离开'))))
        self.assertEqual(decide_route(w, [], route_at(w), 5).kind, 'fail')

    def test_well_patrols_between_points(self):
        d = decide_route(IN_WELL, [], route_at(IN_WELL), 100)
        self.assertEqual((d.kind, d.arg), ('navigate', (WELL_MAP, *PATROL[0], 0)))
        at_a = replace(IN_WELL, x=PATROL[0][0], y=PATROL[0][1], nav_active=True)
        memo = route_at(at_a, last_nav=99.9)
        d = decide_route(at_a, [], memo, 100)
        self.assertEqual((d.kind, d.arg), ('navigate', (WELL_MAP, *PATROL[1], 1)))
        memo.record(d, at_a, 100)
        self.assertEqual(memo.patrol, 1)
        self.assertEqual(decide_route(at_a, [], memo, 100.1).kind, 'wait')   # walking to B now

    def test_unknown_map_fails(self):
        self.assertEqual(decide_route(replace(W, map_id=81), [], route_at(W), 1).kind, 'fail')

    def test_map_change_resets_entrance_memory(self):
        memo = route_at(AT_ENTRANCE, clicked_at=5.0, clicks=2)
        memo.observe(IN_WELL, 6.0)
        self.assertIsNone(memo.clicked_at)


class FighterTests(unittest.TestCase):
    def test_acts_on_first_sp_and_each_change(self):
        memo = Fight()
        self.assertEqual(decide_fighter(Fighter(12, 0, False), memo, 0, True, 'x').kind, 'cast')
        memo.record(0, 0)
        self.assertEqual(decide_fighter(Fighter(12, 0, False), memo, 1, True, 'x').kind, 'none')
        self.assertEqual(decide_fighter(Fighter(12, 1, False), memo, 1, True, 'x').kind, 'cast')

    def test_no_resend_at_sp_zero(self):
        memo = Fight()
        memo.record(0, 0)
        self.assertEqual(decide_fighter(Fighter(12, 0, False), memo, RESEND * 3, True, 'x').kind, 'none')

    def test_resend_then_normal_attack(self):
        memo = Fight()
        memo.record(1, 0)
        self.assertEqual(decide_fighter(Fighter(12, 1, False), memo, RESEND - 0.1, True, 'x').kind, 'none')
        for i in range(1, MAX_SKILL_SENDS):
            self.assertEqual(decide_fighter(Fighter(12, 1, False), memo, i * RESEND, True, 'x').kind, 'cast')
            memo.record(1, i * RESEND)
        self.assertEqual(memo.sends, MAX_SKILL_SENDS)
        self.assertEqual(decide_fighter(Fighter(12, 1, False), memo, 99, True, 'x').kind, 'attack')

    def test_cannot_cast_attacks_dead_does_nothing(self):
        self.assertEqual(decide_fighter(Fighter(12, 1, False), Fight(), 0, False, 'x').kind, 'attack')
        self.assertEqual(decide_fighter(Fighter(12, 1, True), Fight(), 0, True, 'x').kind, 'none')
        self.assertEqual(decide_fighter(None, Fight(), 0, True, 'x').kind, 'none')

    def test_battle_targets_first_live_enemy(self):
        b = Battle(me=Fighter(12, 1, False), pet=Fighter(17, 1, False), enemies=(3, 5))
        out = dict(decide_battle(b, Fight(), Fight(), 0, True, False))
        self.assertEqual((out['me'].kind, out['me'].arg), ('cast', 3))
        self.assertEqual((out['pet'].kind, out['pet'].arg), ('attack', 3))

    def test_battle_without_enemies_or_object(self):
        b = Battle(me=Fighter(12, 1, False), pet=None, enemies=())
        self.assertTrue(all(d.kind == 'none' for _, d in decide_battle(b, Fight(), Fight(), 0, True, True)))
        self.assertEqual(decide_battle(None, Fight(), Fight(), 0, True, True), [])


class PetPos(unittest.TestCase):
    def test_pet_uses_own_side_test(self):
        # own real pos 12 (> 10): no conversion for anybody, like GetMyPetPos
        self.assertEqual(_client_pos(3, 1, my_real=12), 3)
        # own real pos 2 on the flipped side: pet real 7 -> client 12
        self.assertEqual(_client_pos(7, 1, my_real=2), 12)
        self.assertEqual(_client_pos(2, 1), 17)


class StaleTarget(unittest.TestCase):
    def test_walk_target_left_by_a_teleport_is_not_moving(self):
        w = replace(W, target_x=2100.0, target_y=1500.0)
        self.assertTrue(w.moving)
        self.assertTrue(replace(w, still_for=STALE_TARGET_AFTER - 0.1).moving)
        self.assertFalse(replace(w, still_for=STALE_TARGET_AFTER).moving)

    def test_still_for_tracks_position_per_handle(self):
        class Mem:
            pass
        mem = Mem()
        self.assertEqual(_still_for(mem, 1, 2, now=10), 0.0)
        self.assertEqual(_still_for(mem, 1, 2, now=10.5), 0.5)
        self.assertEqual(_still_for(mem, 3, 2, now=11), 0.0)
        self.assertEqual(_still_for(Mem(), 3, 2, now=11), 0.0)


class TalentTests(unittest.TestCase):
    def test_adds_all_points(self):
        d = decide_talent(5, Talent(), 0)
        self.assertEqual((d.kind, d.arg), ('add', 5))
        self.assertEqual(decide_talent(0, Talent(), 0).kind, 'none')

    def test_verified_when_points_drop(self):
        memo = Talent(sent_at=0, before=5)
        self.assertEqual(decide_talent(5, memo, 1).kind, 'wait')
        self.assertEqual(decide_talent(0, memo, 1).kind, 'verified')
        self.assertEqual(decide_talent(5, memo, TALENT_WAIT + 1).kind, 'unconfirmed')

    def test_backoff_after_misses(self):
        memo = Talent(misses=TALENT_MISSES, last_miss=10)
        self.assertEqual(decide_talent(5, memo, 10 + TALENT_BACKOFF - 1).kind, 'wait')
        self.assertEqual(decide_talent(5, memo, 10 + TALENT_BACKOFF + 1).kind, 'add')

    def test_body(self):
        self.assertEqual(talent_body(5), struct.pack('<6i', 0, 0, 0, 5, 0, 0))
        self.assertRaises(ValueError, talent_body, 0)


ALT = 7
AW = replace(IN_WELL, char_id=ALT)
IN_TEAM = Team((LEADER, ALT), (70, 11), 0)
NO_TEAM = Team((), (), 0)


class MemberReturn(unittest.TestCase):
    def test_shoe_first_then_scroll_then_stuck(self):
        memo = Home()
        self.assertEqual(decide_member_return(AW, IN_TEAM, LEADER, True, 4, memo, 0).kind, 'shoe')
        memo.method, memo.sent_at = 'shoe', 0
        self.assertEqual(decide_member_return(AW, IN_TEAM, LEADER, True, 4, memo, RETURN_WAIT - 1).kind, 'wait')
        self.assertEqual(decide_member_return(AW, IN_TEAM, LEADER, True, 4, memo, RETURN_WAIT + 1).kind,
                         'unconfirmed')
        memo.tried.add('shoe')
        memo.sent_at = None
        d = decide_member_return(AW, IN_TEAM, LEADER, True, 4, memo, 9)
        self.assertEqual((d.kind, d.arg), ('scroll', 4))
        memo.tried.add('scroll')
        self.assertEqual(decide_member_return(AW, IN_TEAM, LEADER, True, 4, memo, 9).kind, 'stuck')

    def test_no_shoe_uses_scroll(self):
        self.assertEqual(decide_member_return(AW, IN_TEAM, LEADER, False, 2, Home(), 0).kind, 'scroll')
        self.assertEqual(decide_member_return(AW, IN_TEAM, LEADER, False, None, Home(), 0).kind, 'stuck')

    def test_home_still_in_team_leaves(self):
        home = replace(AW, map_id=VILLAGE_MAP)
        self.assertEqual(decide_member_return(home, IN_TEAM, LEADER, True, 1, Home(), 0).kind, 'leave')
        self.assertEqual(decide_member_return(home, IN_TEAM, LEADER, True, 1, Home(left_at=0), 1).kind, 'wait')
        self.assertEqual(decide_member_return(home, NO_TEAM, LEADER, True, 1, Home(), 0).kind, 'done')

    def test_waits_in_battle(self):
        self.assertEqual(decide_member_return(replace(AW, in_battle=True), IN_TEAM, LEADER, True, 1, Home(), 0).kind,
                         'wait')


class LeaderReturn(unittest.TestCase):
    def test_scroll_then_done(self):
        d = decide_leader_return(IN_WELL, 3, Home(), 0)
        self.assertEqual((d.kind, d.arg), ('scroll', 3))
        self.assertEqual(decide_leader_return(IN_WELL, 3, Home(sent_at=0), 1).kind, 'wait')
        self.assertEqual(decide_leader_return(IN_WELL, 3, Home(sent_at=0), RETURN_WAIT + 1).kind, 'unconfirmed')
        self.assertEqual(decide_leader_return(W, None, Home(), 0).kind, 'done')

    def test_stops_patrol_first_and_fails_without_scroll(self):
        self.assertEqual(decide_leader_return(replace(IN_WELL, nav_active=True), 3, Home(), 0).kind, 'cancel_nav')
        self.assertEqual(decide_leader_return(IN_WELL, None, Home(), 0).kind, 'fail')
        self.assertEqual(decide_leader_return(IN_WELL, 3, Home(tried={'a', 'b'}), 0).kind, 'fail')

    def test_scroll_slot(self):
        self.assertEqual(scroll_slot((BagSlot(0, 1, 1), BagSlot(5, SCROLL_ITEM, 20))), 5)
        self.assertIsNone(scroll_slot(()))


if __name__ == '__main__':
    unittest.main()
