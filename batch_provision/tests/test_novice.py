"""Unit tests for the novice stage decision logic (no game needed).

Run: python -X utf8 -m unittest discover -s tests -v   (from batch_provision/)
"""
import unittest
from dataclasses import replace

from provisioner.novice import (CLICK_RETRY, ESCAPE_FALLBACK, MAX_CLICKS, NAV_RETRY, NAV_TARGET, NOVICE_MAP,
                                STALL_TIMEOUT, TELEPORTER_NPC, TELEPORTER_POINT, VILLAGE_MAP, Memo, decide)
from provisioner.world import Dialog, WorldState

SPAWN = WorldState(char_id=1, map_id=NOVICE_MAP, x=280.0, y=600.0, target_x=0.0, target_y=0.0, flags=0,
                   busy=False, in_battle=False, nav_active=False, verification=False)
NEAR_NPC = replace(SPAWN, x=TELEPORTER_POINT[0] + 10, y=TELEPORTER_POINT[1], target_x=TELEPORTER_POINT[0] + 10,
                   target_y=TELEPORTER_POINT[1])
MENU = Dialog('...', ((1, '逍遥村'), (0, '离开')))


def run(state, memo=None, now=100.0):
    memo = memo or Memo()
    memo.observe(state, now)
    return decide(state, memo, now), memo


class Outcomes(unittest.TestCase):
    def test_loading(self):
        self.assertEqual(decide(None, Memo(), 0).kind, 'wait')

    def test_done_in_village(self):
        self.assertEqual(run(replace(SPAWN, map_id=VILLAGE_MAP))[0].kind, 'done')

    def test_unknown_map_fails(self):
        self.assertEqual(run(replace(SPAWN, map_id=55))[0].kind, 'fail')

    def test_verification_waits(self):
        self.assertEqual(run(replace(SPAWN, verification=True))[0].kind, 'wait')


class Walking(unittest.TestCase):
    def test_fresh_spawn_navigates(self):
        # target (0,0) at spawn must NOT count as moving (found on live clients 2026-10-12)
        d, _ = run(SPAWN)
        self.assertEqual((d.kind, d.arg), ('navigate', NAV_TARGET))

    def test_no_renavigate_too_soon(self):
        memo = Memo(last_nav=99.0)
        self.assertEqual(run(SPAWN, memo, now=99.0 + NAV_RETRY / 2)[0].kind, 'wait')

    def test_navigating_waits(self):
        moving = replace(SPAWN, nav_active=True, target_x=900, target_y=600)
        self.assertEqual(run(moving)[0].kind, 'wait')

    def test_stall_cancels(self):
        stuck = replace(SPAWN, x=1000, y=600, nav_active=True, target_x=1500, target_y=600)
        memo = Memo()
        memo.observe(stuck, 0.0)
        d = decide(stuck, memo, STALL_TIMEOUT + 1)
        self.assertEqual(d.kind, 'cancel_nav')

    def test_progress_resets_stall_timer(self):
        memo = Memo()
        a = replace(SPAWN, x=1000, nav_active=True, target_x=1500, target_y=600)
        memo.observe(a, 0.0)
        b = replace(a, x=1100)
        memo.observe(b, STALL_TIMEOUT + 1)
        self.assertEqual(decide(b, memo, STALL_TIMEOUT + 1).kind, 'wait')


class Teleporter(unittest.TestCase):
    def test_near_npc_while_navigating_cancels(self):
        self.assertEqual(run(replace(NEAR_NPC, nav_active=True))[0].kind, 'cancel_nav')

    def test_near_npc_clicks(self):
        d, _ = run(NEAR_NPC)
        self.assertEqual((d.kind, d.arg), ('click', TELEPORTER_NPC))

    def test_click_not_repeated_too_soon(self):
        memo = Memo(last_click=99.0, clicks=1)
        self.assertEqual(run(NEAR_NPC, memo, now=99.0 + CLICK_RETRY / 2)[0].kind, 'wait')

    def test_click_budget(self):
        self.assertEqual(run(NEAR_NPC, Memo(clicks=MAX_CLICKS))[0].kind, 'fail')

    def test_dialog_selects_village(self):
        d, _ = run(replace(NEAR_NPC, dialog=MENU))
        self.assertEqual((d.kind, d.arg), ('select', 1))

    def test_dialog_select_not_repeated_too_soon(self):
        self.assertEqual(run(replace(NEAR_NPC, dialog=MENU), Memo(last_select=99.5))[0].kind, 'wait')

    def test_unknown_menu_fails(self):
        other = Dialog('...', ((1, '乌龙村'), (0, '离开')))
        self.assertEqual(run(replace(NEAR_NPC, dialog=other))[0].kind, 'fail')


class Battle(unittest.TestCase):
    def fight(self, sp):
        return replace(SPAWN, in_battle=True, busy=True, flags=0x8, my_sp=sp)

    def test_first_sight_escapes_even_at_sp0(self):
        # like the official auto-fight: lastSP starts unknown, so SP 0 already triggers
        self.assertEqual(run(self.fight(0))[0].kind, 'escape')

    def test_same_sp_waits(self):
        self.assertEqual(run(self.fight(0), Memo(last_sp=0, last_escape=99.0))[0].kind, 'wait')

    def test_sp_0_to_1_escapes_again(self):
        self.assertEqual(run(self.fight(1), Memo(last_sp=0, last_escape=99.0))[0].kind, 'escape')

    def test_fallback_resend(self):
        memo = Memo(last_sp=1, last_escape=100.0)
        self.assertEqual(run(self.fight(1), memo, now=100.0 + ESCAPE_FALLBACK)[0].kind, 'escape')

    def test_record_escape_remembers_sp(self):
        memo = Memo()
        state = self.fight(1)
        d = decide(state, memo, 5.0)
        memo.record(d, state, 5.0)
        self.assertEqual((memo.last_sp, memo.escapes), (1, 1))

    def test_battle_never_walks_or_clicks(self):
        for sp in (0, 1, 2, 3):
            self.assertIn(run(replace(self.fight(sp), x=NEAR_NPC.x, y=NEAR_NPC.y),
                              Memo(last_sp=sp, last_escape=100.0))[0].kind, ('wait',))


if __name__ == '__main__':
    unittest.main()
