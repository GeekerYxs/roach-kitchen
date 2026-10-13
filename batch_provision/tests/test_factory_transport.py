"""Unit tests for stage 5 (dispatcher transport through PP鸡), no game needed."""
import unittest
from dataclasses import replace

from factory.transport import (CLICK_WAIT, FOLLOW_RANGE, FOLLOW_WAIT, LEAVE_WAIT, MAX_CLICKS, PP_NPC, PP_POINT,
                               SELECT_RETRY, SETTLE, STALL, TELEPORT_WAIT, Trip, decide_disband, decide_trip)
from provisioner.world import Dialog, WorldState

DISP = 900
W = WorldState(char_id=DISP, map_id=1, x=float(PP_POINT[0]), y=float(PP_POINT[1]), target_x=0.0, target_y=0.0,
               flags=0, busy=False, in_battle=False, nav_active=False, verification=False, still_for=SETTLE)
NEAR = replace(W, char_id=7, x=W.x + 50)
FAR = replace(W, char_id=7, x=W.x + FOLLOW_RANGE + 100)
MENU1 = Dialog('', ((1, '传送服务'), (2, '我随便看看'), (0, '离开')))
MENU2 = Dialog('', ((1, '平静海岸2区190金币'), (2, '龙之都500金币'), (0, '离开')))


def at_npc(now=0.0, **kw):
    memo = Trip(**kw)
    memo.observe(W, now)
    return memo


class Trip_(unittest.TestCase):
    def test_far_navigates(self):
        far = replace(W, x=1266.0, y=1174.0)
        d = decide_trip(far, [], Trip(), 10)
        self.assertEqual((d.kind, d.arg), ('navigate', (1, *PP_POINT)))

    def test_walking_waits_then_stall_cancels(self):
        far = replace(W, x=1266.0, y=1174.0, nav_active=True)
        self.assertEqual(decide_trip(far, [], Trip(progress_at=9), 10).kind, 'wait')
        self.assertEqual(decide_trip(far, [], Trip(progress_at=0), STALL + 1).kind, 'cancel_nav')

    def test_click_when_settled_and_team_near(self):
        d = decide_trip(W, [NEAR, NEAR], at_npc(), 1)
        self.assertEqual((d.kind, d.arg), ('click', PP_NPC))

    def test_not_settled_waits(self):
        self.assertEqual(decide_trip(replace(W, still_for=0.1), [NEAR], at_npc(), 1).kind, 'wait')

    def test_waits_for_followers_then_clicks_anyway(self):
        memo = at_npc(now=0)
        self.assertEqual(decide_trip(W, [NEAR, FAR], memo, 1).kind, 'wait')
        self.assertEqual(decide_trip(W, [NEAR, None], memo, 1).kind, 'wait')
        self.assertEqual(decide_trip(W, [NEAR, FAR], memo, FOLLOW_WAIT + 1).kind, 'click')

    def test_member_on_other_map_is_behind(self):
        self.assertEqual(decide_trip(W, [replace(NEAR, map_id=130)], at_npc(), 1).kind, 'wait')

    def test_after_click_waits_then_clicks_again_up_to_max(self):
        memo = at_npc(clicked_at=0, clicks=1)
        self.assertEqual(decide_trip(W, [], memo, CLICK_WAIT - 1).kind, 'wait')
        self.assertEqual(decide_trip(W, [], memo, CLICK_WAIT + 1).kind, 'click')
        memo.clicks = MAX_CLICKS
        self.assertEqual(decide_trip(W, [], memo, CLICK_WAIT + 1).kind, 'fail')

    def test_menus(self):
        d = decide_trip(replace(W, dialog=MENU1), [], at_npc(), 10)
        self.assertEqual((d.kind, d.arg), ('select', 1))
        d = decide_trip(replace(W, dialog=MENU2), [], at_npc(), 10)
        self.assertEqual((d.kind, d.arg), ('destination', 1))

    def test_service_not_repeated_too_soon(self):
        self.assertEqual(decide_trip(replace(W, dialog=MENU1), [], at_npc(last_select=9), 10).kind, 'wait')
        self.assertEqual(decide_trip(replace(W, dialog=MENU1), [], at_npc(last_select=9), 9 + SELECT_RETRY).kind,
                         'select')

    def test_second_menu_answered_at_once(self):
        self.assertEqual(decide_trip(replace(W, dialog=MENU2), [], at_npc(last_select=9.9), 10).kind, 'destination')

    def test_unknown_menu_fails(self):
        d = decide_trip(replace(W, dialog=Dialog('', ((1, '确定'), (0, '离开')))), [], at_npc(), 10)
        self.assertEqual(d.kind, 'fail')

    def test_destination_menu_still_open_fails(self):
        memo = at_npc(dest_at=0, last_select=0)
        self.assertEqual(decide_trip(replace(W, dialog=MENU2), [], memo, SELECT_RETRY + 1).kind, 'fail')

    def test_after_destination_waits_then_fails(self):
        memo = at_npc(dest_at=0, last_select=0)
        self.assertEqual(decide_trip(W, [], memo, 1).kind, 'wait')
        self.assertEqual(decide_trip(W, [], memo, TELEPORT_WAIT + 1).kind, 'fail')

    def test_arrived_and_odd_maps(self):
        self.assertEqual(decide_trip(replace(W, map_id=81), [], Trip(), 0).kind, 'arrived')
        self.assertEqual(decide_trip(replace(W, map_id=130), [], Trip(), 0).kind, 'fail')
        self.assertEqual(decide_trip(None, [], Trip(), 0).kind, 'wait')

    def test_busy_and_verification_wait(self):
        self.assertEqual(decide_trip(replace(W, busy=True), [], at_npc(), 1).kind, 'wait')
        self.assertEqual(decide_trip(replace(W, verification=True), [], at_npc(), 1).kind, 'wait')

    def test_nav_still_active_at_npc_cancels(self):
        self.assertEqual(decide_trip(replace(W, nav_active=True), [], at_npc(), 1).kind, 'cancel_nav')

    def test_leaving_npc_area_resets_follow_timer(self):
        memo = at_npc(now=0)
        memo.observe(replace(W, x=1266.0, y=1174.0), 5)
        self.assertIsNone(memo.at_npc_since)


class Disband(unittest.TestCase):
    def test_nobody_left_done(self):
        self.assertEqual(decide_disband(0, 0, None, 0).kind, 'done')

    def test_scroll_disbands_so_wait_first(self):
        self.assertEqual(decide_disband(2, 0, None, LEAVE_WAIT - 1).kind, 'wait')

    def test_dispatcher_leaves_once_then_fails(self):
        self.assertEqual(decide_disband(2, 0, None, LEAVE_WAIT + 1).kind, 'leave')
        self.assertEqual(decide_disband(2, 0, 6, 6 + LEAVE_WAIT - 1).kind, 'wait')
        self.assertEqual(decide_disband(2, 0, 6, 6 + LEAVE_WAIT + 1).kind, 'fail')
        self.assertEqual(decide_disband(0, 0, 6, 6 + LEAVE_WAIT + 1).kind, 'done')


if __name__ == '__main__':
    unittest.main()
