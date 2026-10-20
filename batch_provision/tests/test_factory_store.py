"""Unit tests for the 料理仓库号 stage 2a (factory/store.py): names, sell / eat choice, decisions, stores rows."""
import unittest
from dataclasses import replace
from types import SimpleNamespace

from factory import db
from factory.items import Item
from factory.phase import COAST_MAP, VILLAGE_MAP
from factory.store import (StoreSettings, decide, eat_slot, load_store, sell_slots, store_names, todo_roles)
from factory.supply import HP_ITEM, MP_ITEM, PETSHOP
from provisioner.config import Account, Settings, merge_local
from provisioner.protocol import encode_role_name
from provisioner.world import BagSlot, WorldState

SWORD, HAT, SCROLL, DISH = 1001, 1002, 9801, 27002
TABLE = {
    SWORD: Item(SWORD, 0x103, 1, 20, True, False, '新手剑'),
    HAT: Item(HAT, 0x101, 1, 10, True, False, '新手帽'),
    HP_ITEM: Item(HP_ITEM, 0x400, 1, 2, True, False, '萝卜糕'),
    MP_ITEM: Item(MP_ITEM, 0x400, 1, 2, True, False, '胡萝卜汁'),
    SCROLL: Item(SCROLL, 0x400, 1, 40, True, False, '回城卷'),
    DISH: Item(DISH, 0x400, 1, 500, True, False, '美味小强料理'),
}
AT_SHOP = WorldState(char_id=1, map_id=VILLAGE_MAP, x=float(PETSHOP.spot[0]), y=float(PETSHOP.spot[1]),
                     target_x=0.0, target_y=0.0, flags=0, busy=False, in_battle=False, nav_active=False,
                     verification=False)
FAR = replace(AT_SHOP, x=200.0, y=200.0)
NOVICE = (BagSlot(0, SWORD, 1), BagSlot(1, HAT, 1), BagSlot(2, HP_ITEM, 30), BagSlot(3, MP_ITEM, 30),
          BagSlot(4, 30188, 1), BagSlot(5, 30187, 1), BagSlot(6, SCROLL, 5))
CLEAN = (BagSlot(6, SCROLL, 5),)


def settings(suffix):
    return SimpleNamespace(role_names=lambda a: Settings.role_names(SimpleNamespace(role_suffix=suffix,
                                                                                    roles_per_account=4), a))


class Names(unittest.TestCase):
    def test_store_names(self):
        self.assertEqual(store_names(settings('仓'), 'box07'), ['box07仓1', 'box07仓2', 'box07仓3', 'box07仓4'])
        self.assertEqual(store_names(settings('ck'), 'box07')[0], 'box07ck1')

    def test_alt_style_names_refused(self):
        with self.assertRaises(ValueError):
            store_names(settings('r'), 'box07')

    def test_gbk_role_name(self):
        self.assertEqual(encode_role_name('box07仓1'), b'box07' + '仓'.encode('gbk') + b'1')
        self.assertEqual(encode_role_name('mw01r1'), b'mw01r1')
        for bad in ('', 'box07仓仓仓仓仓1', 'box 07', 'box07_1', 'a' * 16):
            with self.assertRaises(ValueError, msg=bad):
                encode_role_name(bad)


class Choice(unittest.TestCase):
    def test_sells_only_gear_and_novice_food(self):
        self.assertEqual([s.slot for s in sell_slots(NOVICE, TABLE)], [0, 1, 2, 3])

    def test_never_sells_dish_scroll_or_unknown(self):
        bag = (BagSlot(0, DISH, 99), BagSlot(1, SCROLL, 5), BagSlot(2, 55555, 1), BagSlot(3, 30186, 1))
        self.assertEqual(sell_slots(bag, TABLE), [])

    def test_eats_meat_then_wine_once_each(self):
        self.assertEqual(eat_slot(NOVICE, set()), ('meat', NOVICE[4]))
        self.assertEqual(eat_slot(NOVICE, {'meat'}), ('wine', NOVICE[5]))
        self.assertIsNone(eat_slot(NOVICE, {'meat', 'wine'}))
        self.assertEqual(eat_slot((BagSlot(9, 30185, 2),), set()), ('wine', BagSlot(9, 30185, 2)))


class Decide(unittest.TestCase):
    def d(self, world=AT_SHOP, bag=NOVICE, cap=40, eaten=frozenset(), free_min=35):
        return decide(world, bag, cap, TABLE, set(eaten), free_min)

    def test_loading_waits(self):
        self.assertEqual(self.d(world=None).kind, 'wait')
        self.assertEqual(self.d(bag=None).kind, 'wait')
        self.assertEqual(self.d(cap=None).kind, 'wait')

    def test_wrong_map_fails(self):
        self.assertEqual(self.d(world=replace(AT_SHOP, map_id=COAST_MAP)).kind, 'fail')

    def test_busy_or_captcha_waits(self):
        self.assertEqual(self.d(world=replace(AT_SHOP, in_battle=True)).kind, 'wait')
        self.assertEqual(self.d(world=replace(AT_SHOP, verification=True)).kind, 'wait')

    def test_eats_first_wherever_it_stands(self):
        d = self.d(world=FAR)
        self.assertEqual((d.kind, d.arg[0]), ('eat', 'meat'))

    def test_walks_to_shop_when_far(self):
        self.assertEqual(self.d(world=FAR, eaten={'meat', 'wine'}).kind, 'walk')
        self.assertEqual(self.d(world=replace(FAR, nav_active=True), eaten={'meat', 'wine'}).kind, 'wait')

    def test_arrived_stops_navigation_then_sells(self):
        self.assertEqual(self.d(world=replace(AT_SHOP, nav_active=True), eaten={'meat', 'wine'}).kind, 'arrived')
        d = self.d(eaten={'meat', 'wine'})
        self.assertEqual((d.kind, [s.slot for s in d.arg]), ('sell', [0, 1, 2, 3]))

    def test_done_after_restart_with_nothing_left(self):
        d = self.d(world=FAR, bag=CLEAN)
        self.assertEqual((d.kind, d.arg), ('done', 39))

    def test_short_when_bag_not_free_enough(self):
        bag = CLEAN + tuple(BagSlot(10 + i, DISH, 99) for i in range(5))
        d = self.d(bag=bag)
        self.assertEqual((d.kind, d.arg), ('short', 34))
        self.assertEqual(self.d(bag=bag, free_min=34).kind, 'done')


class Plan(unittest.TestCase):
    def test_todo_skips_ready_rows_with_the_same_name(self):
        accounts = (Account('box07', 'x'), Account('box08', 'x'))
        names = {'box07': ['box07仓1', 'box07仓2'], 'box08': ['box08仓1', 'box08仓2']}.get
        ready = {('box07', 1): 'box07仓1', ('box08', 2): 'box08ck2'}
        got = [(a.name, slot, n) for a, slot, n in todo_roles(accounts, names, ready)]
        self.assertEqual(got, [('box07', 2, 'box07仓2'), ('box08', 1, 'box08仓1'), ('box08', 2, 'box08仓2')])

    def test_store_settings(self):
        self.assertEqual(load_store({}), StoreSettings())
        self.assertEqual(load_store({'store': {'free_min': 30}}).free_min, 30)


class Rows(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(':memory:')

    def test_save_and_keep_numbers_on_failure(self):
        db.save_store(self.conn, 'box07', 1, 'box07仓1', db.STORE_VILLAGE_READY, 1.0, char_id=77, free_slots=35,
                      capacity=40, map_id=1, x=1338, y=1155)
        db.save_store(self.conn, 'box07', 1, 'box07仓1', db.STORE_FAILED, 2.0, error='boom')
        row = db.store(self.conn, 'box07', 1)
        self.assertEqual((row['status'], row['char_id'], row['free_slots'], row['error']),
                         (db.STORE_FAILED, 77, 35, 'boom'))
        self.assertEqual(len(db.stores(self.conn, 'box07')), 1)
        self.assertEqual(db.stores(self.conn, 'box08'), [])


class LocalAccounts(unittest.TestCase):
    LOCAL = {'accounts': {'prefix': 'mw', 'start': 301, 'count': 5, 'password': 'alt'},
             'store_accounts': {'prefix': 'box', 'start': 7, 'count': 10, 'digits': 2, 'password': 'box'}}

    def test_from_store_accounts(self):
        out = merge_local({'accounts': {'from': 'store_accounts'}}, self.LOCAL)
        self.assertEqual(out['accounts'], self.LOCAL['store_accounts'])

    def test_default_is_alt_range(self):
        self.assertEqual(merge_local({}, self.LOCAL)['accounts'], self.LOCAL['accounts'])

    def test_missing_section_is_an_error(self):
        with self.assertRaises(ValueError):
            merge_local({'accounts': {'from': 'store_accounts'}}, {'accounts': {}})


if __name__ == '__main__':
    unittest.main()
