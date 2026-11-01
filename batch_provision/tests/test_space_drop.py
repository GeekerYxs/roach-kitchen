"""r4_util.drop_order (user 2026-11-01): 蝎子王 gave no 蝎爪 to a full bag; when no 0-quality 杂物 is left, a 整人道具
or any other 杂物 goes, never quest items, 回城卷 / drinks, equipment or important items."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'shitu'))

import r4_util  # noqa: E402

ITEMS = {
    1: NS(name='破布', type=0x1000, quality=0, important=False),
    2: NS(name='定身丸', type=0x802, quality=1, important=False),
    3: NS(name='好杂物', type=0x1000, quality=2, important=False),
    4: NS(name='蝎子药', type=0x2000, quality=1, important=False),
    5: NS(name='回城卷', type=0x400, quality=1, important=False),
    6: NS(name='小刀', type=0x103, quality=0, important=False),
    7: NS(name='重要杂物', type=0x1000, quality=0, important=True),
    8: NS(name='变身卡', type=0x803, quality=1, important=False),
}


def bag(*ids):
    return [NS(slot=i, item_id=x, quantity=1) for i, x in enumerate(ids)]


class DropOrder(unittest.TestCase):
    def names(self, b):
        return [ITEMS[s.item_id].name for s in r4_util.drop_order(b, ITEMS)]

    def test_order(self):
        self.assertEqual(self.names(bag(3, 2, 1, 8)), ['破布', '定身丸', '变身卡', '好杂物'])

    def test_prank_when_no_plain_junk(self):
        self.assertEqual(self.names(bag(4, 5, 6, 2)), ['定身丸'])

    def test_any_junk_last(self):
        self.assertEqual(self.names(bag(4, 5, 3)), ['好杂物'])

    def test_never_these(self):
        self.assertEqual(self.names(bag(4, 5, 6, 7, 99)), [])


if __name__ == '__main__':
    unittest.main()
