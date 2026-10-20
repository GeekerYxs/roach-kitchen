"""Unit tests for the 料理仓库号 stage 2c (factory/storeuse.py): list, order, trigger, per-trade decisions, db."""
import sqlite3
import time
import unittest
from dataclasses import replace
from types import SimpleNamespace

from factory import db
from factory.phase import COAST_MAP, DISH_ITEM, VILLAGE_MAP
from factory.receiver import BagRoom
from factory.storeuse import (Memo, biggest_stack, check_list, decide_give, load_unload, next_store, receiver_busy,
                              rest_status, should_unload, store_order, stores_text)
from provisioner.world import BagSlot, WorldState

RECV = WorldState(char_id=1, map_id=COAST_MAP, x=1780.0, y=1370.0, target_x=0.0, target_y=0.0, flags=0, busy=False,
                  in_battle=False, nav_active=False, verification=False, still_for=5.0)
STORE = replace(RECV, char_id=2, x=1785.0, y=1366.0)
NO_TEAM = SimpleNamespace(members=(), leader=0)
LOCAL = {'store_accounts': {'prefix': 'box', 'start': 7, 'count': 10, 'digits': 2, 'password': 'pw'}}


def row(account, slot, status=db.STORE_READY, free=35):
    return {'account': account, 'slot': slot, 'status': status, 'name': f'{account}仓{slot}', 'free_slots': free}


class Settings(unittest.TestCase):
    def test_empty_list_is_off(self):
        self.assertIsNone(load_unload({}, LOCAL))
        self.assertIsNone(load_unload({'receiver': {'stores': []}}, {}))

    def test_list_in_order_with_passwords(self):
        us = load_unload({'receiver': {'stores': ['box08', 'box07'], 'unload_max_stacks': 1}}, LOCAL)
        self.assertEqual([a.name for a in us.accounts], ['box08', 'box07'])
        self.assertEqual(us.accounts[0].password, 'pw')
        self.assertEqual(us.max_stacks, 1)

    def test_bad_lists(self):
        for data, local in (({'receiver': {'stores': ['box07']}}, {}),                  # no [store_accounts]
                            ({'receiver': {'stores': ['box99']}}, LOCAL),               # outside the range
                            ({'receiver': {'stores': ['box07', 'box07']}}, LOCAL),
                            ({'receiver': {'stores': ['box07'], 'unload_tries': 0}}, LOCAL)):
            with self.assertRaises(ValueError):
                load_unload(data, local)


class List(unittest.TestCase):
    ROWS = [row('box07', 1), row('box07', 2, db.STORE_VILLAGE_READY), row('box08', 1, db.STORE_FULL, 0),
            row('box09', 1, db.STORE_VILLAGE_READY)]

    def test_account_without_a_ready_role_refuses(self):
        errors, notes = check_list(self.ROWS, ['box07', 'box09', 'box10'])
        self.assertEqual(len(errors), 2)
        self.assertIn('box09', errors[0])
        self.assertIn('数据库里没有它的角色', errors[1])
        self.assertEqual(notes, ['box07仓2 状态 village_ready，不用'])

    def test_full_account_is_only_a_note(self):
        errors, notes = check_list(self.ROWS, ['box08'])
        self.assertEqual(errors, [])
        self.assertIn('都已装满', notes[0])

    def test_order_and_next(self):
        rows = [row('box08', 2), row('box07', 2), row('box08', 1, db.STORE_FULL, 0), row('box07', 1, db.STORE_FULL, 0)]
        self.assertEqual([(r['account'], r['slot']) for r in store_order(rows, ['box08', 'box07'])],
                         [('box08', 1), ('box08', 2), ('box07', 1), ('box07', 2)])
        self.assertEqual(next_store(rows, ['box08', 'box07'])['name'], 'box08仓2')
        self.assertEqual(next_store(rows, ['box08', 'box07'], {('box08', 2)})['name'], 'box07仓2')
        self.assertIsNone(next_store(rows, ['box07'], {('box07', 2)}))
        self.assertIsNone(next_store(rows, ['box11']))

    def test_status_text(self):
        rows = [row('box07', 1, free=35), row('box07', 2, free=None), row('box08', 1, db.STORE_FULL, 0)]
        self.assertEqual(stores_text(rows, ['box07', 'box08']), '仓库号 可用 2 个 空 35 格（约 3465 个料理）')


class Trigger(unittest.TestCase):
    def test_should_unload(self):
        self.assertTrue(should_unload(BagRoom(3, 40, 300), 3600, 3))
        self.assertTrue(should_unload(BagRoom(0, 40, 0), 3900, 3))
        self.assertFalse(should_unload(BagRoom(4, 40, 400), 3500, 3))
        self.assertFalse(should_unload(BagRoom(1, 40, 99), 0, 3))       # bag full of other things: nothing to hand
        self.assertFalse(should_unload(None, 3600, 3))
        self.assertFalse(should_unload(BagRoom(1, 40, 99), None, 3))

    def test_biggest_stack(self):
        bag = [BagSlot(0, 10001, 50), BagSlot(3, DISH_ITEM, 40), BagSlot(5, DISH_ITEM, 99), BagSlot(9, DISH_ITEM, 99)]
        self.assertEqual(biggest_stack(bag), (5, 99))          # the full stacks first, the lower slot of equals
        self.assertIsNone(biggest_stack([BagSlot(0, 10001, 50)]))
        self.assertIsNone(biggest_stack(None))

    def test_rest_status(self):
        self.assertEqual(rest_status(0), db.STORE_FULL)
        self.assertEqual(rest_status(5), db.STORE_READY)
        self.assertEqual(rest_status(None), db.STORE_READY)

    def test_receiver_busy(self):
        now = time.time()
        self.assertTrue(receiver_busy({'status': 'receiving', 'heartbeat_at': now - 5}, now))
        self.assertFalse(receiver_busy({'status': 'receiving', 'heartbeat_at': now - 120}, now))
        self.assertFalse(receiver_busy({'status': 'idle', 'heartbeat_at': now}, now))
        self.assertFalse(receiver_busy(None, now))


class Give(unittest.TestCase):
    def d(self, store=STORE, team=NO_TEAM, sd=0, free=35, recv=RECV, rd=3600, stack=(5, 99), memo=None, now=100.0):
        return decide_give(store, team, sd, free, recv, rd, stack, memo or Memo(), now)

    def test_trade(self):
        d = self.d()
        self.assertEqual(d.kind, 'trade')
        self.assertEqual(d.arg, (5, 99))

    def test_loading(self):
        for kw in ({'store': None}, {'team': None}, {'sd': None}, {'free': None}, {'rd': None}):
            self.assertEqual(self.d(**kw).kind, 'wait')

    def test_empty_and_full(self):
        self.assertEqual(self.d(rd=0, stack=None).kind, 'empty')
        self.assertEqual(self.d(free=0, sd=3465).kind, 'full')

    def test_fail_off_map_or_in_team(self):
        self.assertEqual(self.d(store=replace(STORE, map_id=VILLAGE_MAP)).kind, 'fail')
        self.assertEqual(self.d(team=SimpleNamespace(members=(9,), leader=9)).kind, 'fail')

    def test_walk_when_far(self):
        far = replace(STORE, x=1500.0)
        d = self.d(store=far)
        self.assertEqual(d.kind, 'navigate')
        self.assertEqual(d.arg, (COAST_MAP, 1780, 1370))
        self.assertEqual(self.d(store=far, memo=Memo(last_nav=99.0)).kind, 'wait')
        self.assertEqual(self.d(store=replace(far, nav_active=True)).kind, 'wait')

    def test_busy_waits(self):
        self.assertEqual(self.d(recv=replace(RECV, busy=True)).kind, 'wait')
        self.assertEqual(self.d(store=replace(STORE, in_battle=True)).kind, 'wait')

    def sent(self):
        return Memo(sent_at=100.0, qty=99, store_before=0, recv_before=3600)

    def test_verified_exact(self):
        self.assertEqual(self.d(sd=99, rd=3501, memo=self.sent(), now=101.0).kind, 'verified')

    def test_wait_then_unconfirmed(self):
        self.assertEqual(self.d(sd=0, rd=3600, memo=self.sent(), now=102.0).kind, 'wait')
        self.assertEqual(self.d(sd=0, rd=3600, memo=self.sent(), now=106.0).kind, 'unconfirmed')

    def test_numbers_not_adding_up_stop(self):
        self.assertEqual(self.d(sd=0, rd=3501, memo=self.sent(), now=106.0).kind, 'fail')     # gone, not arrived
        self.assertEqual(self.d(sd=98, rd=3501, memo=self.sent(), now=106.0).kind, 'fail')
        self.assertEqual(self.d(sd=0, rd=3501, memo=self.sent(), now=101.0).kind, 'wait')     # may still arrive


class Db(unittest.TestCase):
    def test_dishes_column_and_full(self):
        conn = sqlite3.connect(':memory:', isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.executescript(db.SCHEMA)
        db._migrate(conn)
        db.save_store(conn, 'box07', 1, 'box07仓1', db.STORE_READY, 1.0, char_id=5, free_slots=35, gold=810)
        db.save_store(conn, 'box07', 1, 'box07仓1', db.STORE_FULL, 2.0, free_slots=0, dishes=3465)
        r = db.store(conn, 'box07', 1)
        self.assertEqual((r['status'], r['free_slots'], r['dishes'], r['gold'], r['char_id']),
                         (db.STORE_FULL, 0, 3465, 810, 5))
        db.save_store(conn, 'box07', 1, 'box07仓1', db.STORE_FULL, 3.0, error='x')       # keeps the numbers
        self.assertEqual(db.store(conn, 'box07', 1)['dishes'], 3465)


if __name__ == '__main__':
    unittest.main()
