"""Unit tests for the pure parts of research/shitu (no game needed): sell modes, mail list parsing, the leader's
「walk past the target」 point."""
import struct
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'shitu'))

import double_exp  # noqa: E402
import mail_sell  # noqa: E402
import sell_tradable  # noqa: E402
import teamwalk  # noqa: E402
from factory.items import Item  # noqa: E402


def item(type_, quality, name='x', tradable=True, item_id=1):
    return Item(item_id, type_, quality, 0, tradable, False, name)


class SellModes(unittest.TestCase):
    def test_noorange_keeps_orange_and_consumables(self):
        w = sell_tradable.wanted
        self.assertTrue(w(item(0x1000, 0), 'noorange'))             # 杂物
        self.assertTrue(w(item(0x103, 3), 'noorange'))              # 蓝 weapon
        self.assertTrue(w(item(0x106, 1), 'noorange'))              # 白 armour
        self.assertFalse(w(item(0x106, 4), 'noorange'))             # 橙 kept
        self.assertFalse(w(item(0x400, 1, '萝卜糕'), 'noorange'))   # consumable kept
        self.assertFalse(w(item(0x400, 1, '回城卷', item_id=9801), 'noorange'))

    def test_stones_sells_skill_stones_and_recipes_not_gear(self):
        w = sell_tradable.wanted
        self.assertTrue(w(item(0x821, 4), 'stones'))                # 橙 技能石 too
        self.assertTrue(w(item(0x823, 1, '学识之头罩'), 'stones'))  # 配方 type
        self.assertFalse(w(item(0x106, 1), 'stones'))

    def test_name_mode(self):
        with mock.patch.object(sell_tradable, 'NAMES', ('碧玉葫芦', '酷·太公钓竿')):
            self.assertTrue(sell_tradable.wanted(item(0x400, 1, '碧玉葫芦'), 'name'))
            self.assertTrue(sell_tradable.wanted(item(0x103, 4, '酷·太公钓竿'), 'name'))
            self.assertFalse(sell_tradable.wanted(item(0x400, 1, '黄玉葫芦'), 'name'))


def notify(char, mail, tpl):
    """S->C 0x4411 as recorded 2026-10-27 14:06 on 千万5."""
    return struct.pack('<IiBII8sI', char, -1, 0, mail, 0, bytes(8), tpl) + b'\x01\x00\x00\x00\x00\x00\x01\x00\x00\x00\x13'


class MailList(unittest.TestCase):
    def test_pending_is_notified_minus_taken(self):
        rows = [(0, 'S->C', 0x4411, notify(222162, 0x02CB3DCF, 0x74C6), None),
                (0, 'S->C', 0x4411, notify(222162, 0x02CB3DC7, 0x74C2), None),
                (0, 'S->C', 0x4416, struct.pack('<IIII', 222162, 0x02CB3DCF, 0, 0), None)]
        fake = SimpleNamespace(poll=lambda: rows)
        with mock.patch.object(mail_sell, 'Tap', return_value=fake):
            self.assertEqual(mail_sell.pending(SimpleNamespace(pid=1)), [(0x02CB3DC7, 0x74C2)])


class WalkPast(unittest.TestCase):
    def test_goal_is_over_px_beyond_target_on_the_way_in(self):
        sent = []
        st = SimpleNamespace(x=0, y=0, in_battle=False, moving=False, nav_active=False)
        lead = SimpleNamespace(came_from=(0, 0), world=lambda: st,
                               game=SimpleNamespace(navigate=lambda m, x, y: sent.append((m, x, y)),
                                                    cancel_navigation=lambda: None))
        with mock.patch.object(teamwalk.time, 'sleep'), mock.patch.object(teamwalk, 'MAP', 170):
            st.x, st.y = 100 + teamwalk.OVER, 0                     # already there: the loop ends at once
            teamwalk.past(lead, None, (100, 0))
        self.assertEqual(sent, [(170, 100 + teamwalk.OVER, 0)])
        self.assertEqual(lead.came_from, (100, 0))

    def test_first_target_has_no_direction(self):
        lead = SimpleNamespace(game=SimpleNamespace(navigate=mock.Mock()))
        teamwalk.past(lead, None, (5, 5))
        lead.game.navigate.assert_not_called()


if __name__ == '__main__':
    unittest.main()


class DoubleExpMenu(unittest.TestCase):
    MENU = [(1, '#00BFFF#我要领取#00FF00# 1 小时 #00BFFF#加倍经验'), (2, '#00BFFF#我要领取#00FF00# 2 小时 #00BFFF#加倍经验'),
            (3, '#00BFFF#我要领取#00FF00# 3 小时 #00BFFF#加倍经验'), (4, '离开')]   # 2026-10-27 自由一号

    def test_takes_three_hours(self):
        self.assertEqual(double_exp.choose_hours(self.MENU), (3, 3))

    def test_takes_largest_left(self):
        self.assertEqual(double_exp.choose_hours(self.MENU[:2] + [(3, '离开')]), (2, 2))

    def test_none_when_nothing_to_claim(self):
        self.assertIsNone(double_exp.choose_hours([(1, '离开')]))
