"""tidy rules (user 2026-11-02, 元素使 team): sell the 扳手 and the 新手装, rank armour by level then quality."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'shitu'))

import sell_tradable as s  # noqa: E402
import wear_best as wb  # noqa: E402


def item(item_id, type_, quality, name='x'):
    return NS(item_id=item_id, type=type_, quality=quality, name=name)


class Sell(unittest.TestCase):
    def test_tidy_sells_wrench_novice_gear_and_junk_keeps_scrolls_and_blue(self):
        self.assertTrue(s.wanted(item(118, 0x103, 4, '专打屁屁扳手'), 'tidy'))
        self.assertTrue(s.wanted(item(21500, 0x106, 2, '强力的新手T恤'), 'tidy'))
        self.assertTrue(s.wanted(item(60030, s.ZAWU, 0, '蜻蜓标本'), 'tidy'))
        self.assertFalse(s.wanted(item(9801, 0x400, 1, '回城卷'), 'tidy'))
        self.assertFalse(s.wanted(item(64309, 0x103, 3, '狂暴之球棒'), 'tidy'))

    def test_safe_still_keeps_the_wrench(self):
        self.assertFalse(s.wanted(item(118, 0x103, 4, '专打屁屁扳手'), 'safe'))


class Rank(unittest.TestCase):
    def test_higher_level_piece_wins_then_quality(self):
        req = {1: 5, 2: 15, 3: 15}
        self.assertTrue(wb.better(item(2, 0x101, 1), req, item(1, 0x101, 3), 2, 1))
        self.assertFalse(wb.better(item(1, 0x101, 3), req, item(2, 0x101, 1), 1, 2))
        self.assertTrue(wb.better(item(3, 0x101, 3), req, item(2, 0x101, 2), 3, 2))
        self.assertTrue(wb.better(item(1, 0x101, 1), req, None, 1, None))


if __name__ == '__main__':
    unittest.main()
