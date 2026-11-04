"""well10.Unarm (user 2026-11-04): from level 2 the 专打屁屁扳手 comes off (bare hands = shorter 蓄力), out of battle."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'shitu'))

import well10  # noqa: E402


class C:
    def __init__(self, server_ok=True, bag=(0, 1), cap=40):
        self.name, self.mem, self.ok = 'a', self, server_ok
        self.worn = [NS(slot=2, item_id=well10.WRENCH, quantity=1)]
        self.bag, self.cap, self.sent = [NS(slot=i, item_id=1) for i in bag], cap, []
        self.game = NS(unequip=self.unequip)

    def unequip(self, eq, slot):
        self.sent.append((eq, slot))
        if self.ok:
            self.worn = []


def run(c, frames):
    """frames: (level, in_battle, now) per tick."""
    u = well10.Unarm(c)
    with mock.patch.object(well10.w, 'read_equipment', lambda m: m.worn), \
            mock.patch.object(well10.w, 'read_bag', lambda m: m.bag), \
            mock.patch.object(well10.w, 'read_bag_capacity', lambda m: m.cap), \
            mock.patch.object(well10.t, 'say', lambda s: None):
        for level, battle, now in frames:
            u.tick(NS(in_battle=battle), level, now)
    return u


class Unarm(unittest.TestCase):
    def test_level_1_keeps_it(self):
        c = C()
        run(c, [(1, False, 0), (1, False, 10)])
        self.assertEqual(c.sent, [])

    def test_level_2_out_of_battle_takes_it_off_once(self):
        c = C()
        u = run(c, [(2, True, 0), (2, False, 1), (2, False, 2), (3, False, 20)])
        self.assertEqual(c.sent, [(2, 2)])          # weapon slot 2 -> first free bag slot 2
        self.assertTrue(u.done)

    def test_retry_then_give_up(self):
        c = C(server_ok=False)
        u = run(c, [(2, False, 0), (2, False, 1), (2, False, 6), (2, False, 12), (2, False, 18), (2, False, 30)])
        self.assertEqual(len(c.sent), well10.Unarm.TRIES)
        self.assertTrue(u.done)

    def test_no_wrench_nothing_to_do(self):
        c = C()
        c.worn = [NS(slot=2, item_id=64214, quantity=1)]        # 钓竿: not ours to take off
        u = run(c, [(5, False, 0)])
        self.assertEqual(c.sent, [])
        self.assertTrue(u.done)

    def test_full_bag(self):
        c = C(bag=range(40))
        u = run(c, [(2, False, 0)])
        self.assertEqual(c.sent, [])
        self.assertTrue(u.done)

    def test_main_ticks_it(self):
        src = (Path(well10.__file__)).read_text(encoding='utf-8')
        self.assertIn('unarms = {n: Unarm(cs[n]) for n in APPRENTICES}', src)
        self.assertIn('u.tick(sts[n], levels[n], now)', src)


if __name__ == '__main__':
    unittest.main()
