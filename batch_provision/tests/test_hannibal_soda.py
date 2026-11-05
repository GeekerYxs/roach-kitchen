import unittest
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1] / 'projects' / 'fullcrit_mage_leveling_70'
sys.path.insert(0, str(PROJECT))

from hannibal_soda import (
    HANNIBAL, MAP_ID, SHELF_SLOT, SODA_ID, TARGET, TRIGGER, purchase_batches,
)


class HannibalSodaTests(unittest.TestCase):
    def test_live_verified_hannibal_catalog(self):
        self.assertEqual((HANNIBAL, MAP_ID, SODA_ID, SHELF_SLOT), (2508, 180, 8456, 5))

    def test_restocks_with_at_most_99_per_request(self):
        self.assertEqual(purchase_batches(0), [99] * 15)
        self.assertEqual(purchase_batches(285), [99] * 12 + [12])
        self.assertEqual(purchase_batches(1400), [85])
        self.assertEqual(purchase_batches(TARGET), [])

    def test_trigger_is_below_599(self):
        self.assertEqual(TRIGGER, 599)
        self.assertEqual(TARGET, 1485)


if __name__ == '__main__':
    unittest.main()
