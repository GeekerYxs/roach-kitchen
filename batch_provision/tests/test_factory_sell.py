"""Unit tests for the junk run's retry decision (no game needed)."""
import unittest

from factory.sell import SELL_TRIES, after_sale


class AfterSale(unittest.TestCase):
    def test_nothing_left_is_done(self):
        self.assertEqual(after_sale([], 0), 'done')
        self.assertEqual(after_sale([], 5), 'done')

    def test_leftovers_sell_again_before_the_gold(self):
        # live 2026-10-25: 「第三个物品不存在」, nothing sold, the alt traded its gold and was deleted
        self.assertEqual(after_sale(['x'], 0), 'again')
        self.assertEqual(after_sale(['x'], SELL_TRIES - 2), 'again')

    def test_gives_up_after_the_last_try(self):
        self.assertEqual(SELL_TRIES, 3)
        self.assertEqual(after_sale(['x'], SELL_TRIES - 1), 'give_up')


if __name__ == '__main__':
    unittest.main()
