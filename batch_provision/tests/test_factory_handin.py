"""Unit tests for the quest-78 hand-in decision (no game needed)."""
import unittest
from dataclasses import replace

from factory.handin import ACTION, Items, decide
from factory.quest import CONFIRM_WAIT, NPC, SELECT_RETRY, Memo
from provisioner.world import Dialog, Quest, Team, WorldState

AT_NPC = WorldState(char_id=1, map_id=81, x=1780.0, y=1370.0, target_x=1780.0, target_y=1370.0, flags=0,
                    busy=False, in_battle=False, nav_active=False, verification=False, still_for=1.0)
LANDED = replace(AT_NPC, x=1152.0, y=932.0, target_x=0.0, target_y=0.0)
SOLO = Team((), (), 0)
ACTIVE, DONE, NONE = Quest(True, False, (2, 1)), Quest(False, True), Quest(False, False)


def page(*labels):
    text = ''.join(f'[URL]{label}[/URL]' for label in labels) + '[URL]离开[/URL]'
    return Dialog(text, tuple((i, label) for i, label in enumerate(labels, 1)) + ((0, '离开'),))


FULL = Items(10, 20, 0)
GOT = Items(0, 0, 1)
ROW = {'pending_action': None}
RALLY = replace(AT_NPC, x=1750.0, y=1300.0)          # where the coast teams disband, ~110 px from 海子

FIRST = page('飞刀王的晚餐(11)[可完成]')
GIVE = page('当然，给你。')
THANKS = page('谢谢！')


class Decide(unittest.TestCase):
    def test_rally_point_is_close_enough_to_click(self):
        d = decide(RALLY, ACTIVE, SOLO, FULL, ROW, Memo(), 0.0)
        self.assertEqual((d.kind, d.arg), ('click', NPC))

    def test_far_navigates(self):
        self.assertEqual(decide(LANDED, ACTIVE, SOLO, FULL, ROW, Memo(), 0.0).kind, 'navigate')

    def test_menu_select_then_give_twice(self):
        self.assertEqual(decide(replace(RALLY, dialog=FIRST), ACTIVE, SOLO, FULL, ROW, Memo(), 0).kind, 'select')
        self.assertEqual(decide(replace(RALLY, dialog=GIVE), ACTIVE, SOLO, FULL, ROW, Memo(), 0).kind, 'give')
        # after the first give the materials may be gone already; the last page is still answered
        memo = Memo(accept_at=1.0, select_at=1.0, select_text=GIVE.text, selects=2)
        d = decide(replace(RALLY, dialog=THANKS), ACTIVE, SOLO, Items(0, 0, 0), ROW, memo, 1.2)
        self.assertEqual((d.kind, d.arg), ('give', 1))

    def test_same_page_waits_then_again(self):
        memo = Memo(select_at=5.0, select_text=FIRST.text, selects=1)
        w = replace(RALLY, dialog=FIRST)
        self.assertEqual(decide(w, ACTIVE, SOLO, FULL, ROW, memo, 5.0 + SELECT_RETRY - 0.1).kind, 'wait')
        self.assertEqual(decide(w, ACTIVE, SOLO, FULL, ROW, memo, 5.0 + SELECT_RETRY).kind, 'select')

    def test_after_give_unknown_page_waits_then_unconfirmed(self):
        w = replace(RALLY, dialog=page('离开'))
        memo = Memo(accept_at=10.0, select_at=10.0, select_text='x', selects=3)
        self.assertEqual(decide(w, ACTIVE, SOLO, GOT, ROW, memo, 10.0 + CONFIRM_WAIT - 0.1).kind, 'wait')
        self.assertEqual(decide(w, ACTIVE, SOLO, GOT, ROW, memo, 10.0 + CONFIRM_WAIT).kind, 'unconfirmed')

    def test_unknown_menu_before_giving_fails(self):
        self.assertEqual(decide(replace(RALLY, dialog=page('买东西')), ACTIVE, SOLO, FULL, ROW, Memo(), 0).kind,
                         'fail')

    def test_done_with_dish_closes_then_verified(self):
        w = replace(RALLY, dialog=THANKS)
        self.assertEqual(decide(w, DONE, SOLO, GOT, ROW, Memo(accept_at=1.0), 1.5).kind, 'close')
        self.assertEqual(decide(RALLY, DONE, SOLO, GOT, ROW, Memo(accept_at=1.0, closed_at=1.6), 1.7).kind,
                         'verified')
        self.assertEqual(decide(RALLY, DONE, SOLO, GOT, {'pending_action': ACTION}, Memo(), 0).kind, 'verified')

    def test_done_waits_for_dish_then_fails(self):
        memo = Memo(accept_at=1.0, closed_at=1.1)
        empty = Items(0, 0, 0)
        self.assertEqual(decide(RALLY, DONE, SOLO, empty, ROW, memo, 1.0 + CONFIRM_WAIT - 0.1).kind, 'wait')
        self.assertEqual(decide(RALLY, DONE, SOLO, empty, ROW, memo, 1.0 + CONFIRM_WAIT).kind, 'fail')

    def test_already_done_sends_nothing(self):
        self.assertEqual(decide(RALLY, DONE, SOLO, GOT, ROW, Memo(), 0).kind, 'done')
        self.assertEqual(decide(RALLY, DONE, SOLO, Items(0, 0, 0), ROW, Memo(), 0).kind, 'done')

    def test_preconditions_fail(self):
        self.assertEqual(decide(RALLY, NONE, SOLO, FULL, ROW, Memo(), 0).kind, 'fail')
        self.assertEqual(decide(RALLY, ACTIVE, SOLO, Items(10, 19, 0), ROW, Memo(), 0).kind, 'fail')
        self.assertEqual(decide(replace(RALLY, map_id=1), ACTIVE, SOLO, FULL, ROW, Memo(), 0).kind, 'fail')
        self.assertEqual(decide(RALLY, ACTIVE, Team((9, 1), (70, 12), 9), FULL, ROW, Memo(), 0).kind, 'fail')

    def test_loading_and_battle(self):
        self.assertEqual(decide(RALLY, ACTIVE, SOLO, None, ROW, Memo(), 0).kind, 'wait')
        self.assertEqual(decide(replace(RALLY, in_battle=True, my_sp=0), ACTIVE, SOLO, FULL, ROW, Memo(), 0).kind,
                         'escape')


if __name__ == '__main__':
    unittest.main()
