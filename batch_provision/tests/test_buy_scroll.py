"""buy_scroll.py: the masters' pet mp drinks top-up rule (no game)."""
import sys
import unittest
import unittest.mock
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'shitu'))

import buy_scroll as B  # noqa: E402
from provisioner.world import BagSlot  # noqa: E402


def bag(*items):
    return [BagSlot(i, item, q) for i, (item, q) in enumerate(items)]


class Juice(unittest.TestCase):
    def needed(self, slots):
        with unittest.mock.patch.object(B.w, 'read_bag', lambda mem: slots):
            return B.juice_needed(SimpleNamespace(mem=None))

    def test_empty_buys_twenty_stacks(self):
        self.assertEqual(self.needed(bag((8403, 99), (9801, 60))), 20 * 99)   # 便当 / 回城卷 are not mp drinks

    def test_both_drinks_count(self):
        self.assertEqual(self.needed(bag((8456, 30), (63954, 30))), 0)        # 60 >= 50
        self.assertEqual(self.needed(bag((8456, 20), (63954, 29))), 20 * 99)  # 49 < 50

    def test_ids_are_the_client_auto_use_pet_mp_items(self):
        self.assertEqual(set(B.PET_MP_ITEMS), {63954, 8456})                  # AutoUseItemID type 4
        self.assertEqual((B.JUICE, B.JUICE_SHELF), (63954, 1))                # 铁公鸡 shelf 0 萝卜糕 1 胡萝卜汁 2 回城卷


if __name__ == '__main__':
    unittest.main()
