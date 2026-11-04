"""勇者 line apprentices own no weapon (user 2026-11-04): every sale sells all weapons (the worn one taken off first),
wear_best puts none on; a master's weapons are never touched; the 元素使 line is left as it was."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

HERE = Path(__file__).resolve().parent.parent / 'research' / 'shitu'
sys.path.insert(0, str(HERE))

import sell_tradable as st  # noqa: E402
from line import route as R  # noqa: E402

ITEMS = {
    118: NS(item_id=118, name='专打屁屁扳手', type=0x103, quality=4, tradable=True, important=False),
    64214: NS(item_id=64214, name='酷·太公钓竿', type=0x103, quality=4, tradable=True, important=False),
    64309: NS(item_id=64309, name='狂暴之球棒', type=0x103, quality=3, tradable=True, important=False),
    5: NS(item_id=5, name='不可交易的棍', type=0x103, quality=1, tradable=False, important=False),
    6: NS(item_id=6, name='蓝头盔', type=0x101, quality=3, tradable=True, important=False),
    7: NS(item_id=7, name='破布', type=0x1000, quality=0, tradable=True, important=False),
    8: NS(item_id=8, name='宠物武器', type=0x113, quality=4, tradable=True, important=False),
}


def sold(name, masters=('师傅',), weapons=True, mode='safe'):
    bag = [NS(slot=i, item_id=x, quantity=1) for i, x in enumerate((118, 64214, 64309, 5, 6, 7, 8))]
    got, unequipped = [], []

    class Shop:
        def __init__(self, *a):
            pass

        def sell(self, shop, slots):
            got.extend(ITEMS[s.item_id].name for s in slots)
            return len(slots)

        def close(self):
            pass
    c = NS(name=name, mem=None, game=None)
    with mock.patch.object(st, 'WEAPONS', weapons), mock.patch.object(st, 'MASTERS', masters), \
            mock.patch.object(st.t, 'Client', lambda n: c), mock.patch.object(st, 'walk', lambda *a: None), \
            mock.patch.object(st, 'unequip_weapon', lambda c, nm: unequipped.append(c.name)), \
            mock.patch.object(st, 'ShopClient', Shop), mock.patch.object(st.log, 'for_account', lambda n: None), \
            mock.patch.object(st.w, 'read_bag', lambda m: bag), mock.patch.object(st.w, 'read_gold', lambda m: 0), \
            mock.patch.object(st.t, 'say', lambda s: None):
        st.one(name, mode, ITEMS, lambda i: ITEMS[i].name)
    return got, unequipped


class Sell(unittest.TestCase):
    def test_apprentice_sells_every_tradable_weapon(self):
        got, off = sold('亿万1')
        self.assertEqual(sorted(x for x in got if ITEMS[next(k for k, v in ITEMS.items() if v.name == x)].type == 0x103),
                         sorted(['专打屁屁扳手', '酷·太公钓竿', '狂暴之球棒']))
        self.assertIn('破布', got)
        self.assertNotIn('蓝头盔', got)             # --safe keeps 蓝 armour as before
        self.assertNotIn('宠物武器', got)           # 0x113 is not a weapon of the role
        self.assertNotIn('不可交易的棍', got)       # the shop refuses it (logged)
        self.assertEqual(off, ['亿万1'])            # the worn weapon comes off first

    def test_master_untouched(self):
        got, off = sold('师傅')
        self.assertFalse(any(x in got for x in ('专打屁屁扳手', '酷·太公钓竿', '狂暴之球棒')))
        self.assertEqual(off, [])

    def test_without_flag_as_before(self):
        got, off = sold('亿万1', weapons=False)
        self.assertFalse(any(x in got for x in ('专打屁屁扳手', '酷·太公钓竿', '狂暴之球棒')))
        self.assertEqual(off, [])


class Routes(unittest.TestCase):
    def flags(self, route):
        return [(s.name, c.args) for s in route for c in s.cmds if c.args[0] in ('sell_tradable.py', 'wear_best.py')]

    def test_yongzhe_lines_carry_the_flags(self):
        for route in (R.ROUTE, R.ROUTE_BPLUS):
            fl = self.flags(route)
            self.assertTrue(fl)
            for name, args in fl:
                want = '--weapons' if args[0] == 'sell_tradable.py' else '--no-weapon'
                self.assertEqual(args.count(want), 1, (name, args))

    def test_yuansu_untouched(self):
        for name, args in self.flags(R.ROUTE_YUANSU):
            self.assertNotIn('--weapons', args, name)
            self.assertNotIn('--no-weapon', args, name)

    def test_route_of_picks_them(self):
        self.assertIs(R.route_of(NS(route='bplus')), R.ROUTE_BPLUS)
        self.assertIs(R.route_of(NS(route='v5')), R.ROUTE)
        self.assertIs(R.route_of(NS(job='术士')), R.ROUTE_YUANSU)


class WearBest(unittest.TestCase):
    def test_flag(self):
        src = (HERE / 'wear_best.py').read_text(encoding='utf-8')
        self.assertIn("no_weapon = '--no-weapon' in sys.argv", src)
        self.assertIn('weapon=plain and not no_weapon', src)


if __name__ == '__main__':
    unittest.main()
