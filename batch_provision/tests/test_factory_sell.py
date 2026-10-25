"""Unit tests for the junk run's retry decision (no game needed)."""
import tempfile
import unittest
from pathlib import Path

from factory import phase
from factory.config import load_settings
from factory.sell import SELL_TRIES, after_sale, parked
from factory.supply import NURSE
from provisioner.world import WorldState


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



def at(x, y, map_id=81):
    return WorldState(char_id=1, map_id=map_id, x=x, y=y, target_x=x, target_y=y, flags=0, busy=False,
                      in_battle=False, nav_active=False, verification=False, still_for=5.0)


class Pause(unittest.TestCase):
    def test_parked_at_the_nurse(self):
        x, y = NURSE.spot
        self.assertTrue(parked(at(x + 50, y)))
        self.assertFalse(parked(at(1780, 1370)))         # still at the hand-in spot: walk over first
        self.assertFalse(parked(at(x, y, map_id=1)))
        self.assertFalse(parked(None))

    def test_switch_comes_from_this_machines_local_toml(self):
        old = phase.DISH_TRADE, phase.HANDIN_LEVEL
        try:
            with tempfile.TemporaryDirectory() as d:
                cfg = Path(d) / 'factory.toml'
                cfg.write_text('[factory]\nhandin_level = 18\n', 'utf-8')
                self.assertFalse(load_settings(cfg).sell_pause)
                (Path(d) / 'local.toml').write_text('[factory]\nsell_pause = true\n', 'utf-8')
                self.assertTrue(load_settings(cfg).sell_pause)
                self.assertEqual(load_settings(cfg).handin_level, 18)       # the rest still from factory.toml
                (Path(d) / 'local.toml').write_text('[factory]\nsell_pause = 1\n', 'utf-8')
                with self.assertRaises(ValueError):
                    load_settings(cfg)
        finally:
            phase.DISH_TRADE, phase.HANDIN_LEVEL = old


if __name__ == '__main__':
    unittest.main()
