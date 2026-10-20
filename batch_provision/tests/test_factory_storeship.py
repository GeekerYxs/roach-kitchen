"""Unit tests for the 料理仓库号 stage 2b (factory/storeship.py): settings, order, guards, ferry, spawn / post."""
import sqlite3
import threading
import time
import unittest
from dataclasses import replace
from types import SimpleNamespace

from factory import db
from factory.phase import COAST_MAP, VILLAGE_MAP
from factory.storeship import (Ferry, Rider, ShipSettings, StoreGoldJob, StoreTransport, decide_park, decide_spawn,
                               load_ship, ship_order, should_sail, supervisor_busy)
from factory.wellteam import SPAWN
from provisioner.world import WorldState

POST = (1780, 1370)
AT_SPAWN = WorldState(char_id=1, map_id=VILLAGE_MAP, x=float(SPAWN[0]), y=float(SPAWN[1]), target_x=0.0,
                      target_y=0.0, flags=0, busy=False, in_battle=False, nav_active=False, verification=False,
                      still_for=5.0)
AT_POST = replace(AT_SPAWN, map_id=COAST_MAP, x=1785.0, y=1366.0)
NAMES = {'box07': ['box07仓1', 'box07仓2', 'box07仓3', 'box07仓4'],
         'box08': ['box08仓1', 'box08仓2', 'box08仓3', 'box08仓4']}


def row(account, slot, status=db.STORE_VILLAGE_READY, name=None):
    return {'account': account, 'slot': slot, 'status': status, 'name': name or f'{account}仓{slot}'}


class Settings(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(load_ship({}), ShipSettings())
        self.assertEqual(load_ship({'ship': {'gold': 2000, 'gather': 5}}).gold, 2000)

    def test_gold_must_pay_the_teleport(self):
        with self.assertRaises(ValueError):
            load_ship({'ship': {'gold': 100}})


class Order(unittest.TestCase):
    def test_slot_major_and_only_village_ready(self):
        rows = [row('box07', 1), row('box07', 2), row('box08', 1), row('box08', 2, db.STORE_READY),
                row('box07', 3, db.STORE_FAILED)]
        self.assertEqual(ship_order(rows, NAMES),
                         [('box07', 1, 'box07仓1'), ('box08', 1, 'box08仓1'), ('box07', 2, 'box07仓2')])

    def test_unconfigured_account_or_other_name_skipped(self):
        rows = [row('box09', 1), row('box07', 1, name='别的名字'), row('box07', 9)]
        self.assertEqual(ship_order(rows, NAMES), [])


class Guard(unittest.TestCase):
    def test_supervisor_busy(self):
        now = 10_000.0
        self.assertTrue(supervisor_busy('waiting', now - 5, now))
        self.assertFalse(supervisor_busy('waiting', now - 120, now))       # stopped a while ago
        self.assertTrue(supervisor_busy('transporting', now - 200, now))
        self.assertFalse(supervisor_busy('online', now, now))              # just logged in by 一键登录工位
        self.assertFalse(supervisor_busy('idle', now, now))
        self.assertFalse(supervisor_busy('store_ship', now, now))          # an earlier run of this tool
        self.assertFalse(supervisor_busy(None, None, now))


class Sail(unittest.TestCase):
    def test_full_boat_leaves(self):
        self.assertTrue(should_sail(4, 4, 0.0, 20, 3))

    def test_nobody_else_coming_leaves(self):
        self.assertTrue(should_sail(1, 4, 0.0, 20, 0))

    def test_waits_for_riders_still_logging_in(self):
        self.assertFalse(should_sail(1, 4, 5.0, 20, 2))
        self.assertTrue(should_sail(1, 4, 20.0, 20, 2))

    def test_empty_boat_never_leaves(self):
        self.assertFalse(should_sail(0, 4, 99.0, 20, 0))


class Spawn(unittest.TestCase):
    def test_near(self):
        self.assertEqual(decide_spawn(AT_SPAWN, -1e9, 0.0).kind, 'near')
        self.assertEqual(decide_spawn(replace(AT_SPAWN, x=SPAWN[0] + 100.0), -1e9, 0.0).kind, 'near')

    def test_far_walks_then_waits(self):
        far = replace(AT_SPAWN, x=500.0, y=500.0)
        d = decide_spawn(far, -1e9, 10.0)
        self.assertEqual((d.kind, d.arg), ('walk', (VILLAGE_MAP, *SPAWN)))
        self.assertEqual(decide_spawn(far, 9.0, 10.0).kind, 'wait')
        self.assertEqual(decide_spawn(replace(far, nav_active=True), -1e9, 10.0).kind, 'wait')

    def test_other_map_fails(self):
        self.assertEqual(decide_spawn(AT_POST, -1e9, 0.0).kind, 'fail')
        self.assertEqual(decide_spawn(None, -1e9, 0.0).kind, 'wait')


class Park(unittest.TestCase):
    def test_parked_after_standing(self):
        self.assertEqual(decide_park(AT_POST, POST, 40, 2.0).kind, 'parked')
        self.assertEqual(decide_park(replace(AT_POST, still_for=0.5), POST, 40, 2.0).kind, 'wait')

    def test_off_post(self):
        self.assertEqual(decide_park(replace(AT_POST, x=1152.0, y=932.0), POST, 40, 2.0).kind, 'off')
        self.assertEqual(decide_park(AT_SPAWN, POST, 40, 2.0).kind, 'off')
        self.assertEqual(decide_park(None, POST, 40, 2.0).kind, 'wait')


class Hooks(unittest.TestCase):
    """Store roles never touch the alts table: three unconfirmed tries end the job, nothing is written."""

    def test_gold_job_counts_its_own_tries(self):
        job = StoreGoldJob.__new__(StoreGoldJob)
        job.tries = 0
        job.register()
        self.assertFalse(job.quarantined())
        self.assertEqual([job.failed('x') for _ in range(db.MAX_RETRIES)], [False] * (db.MAX_RETRIES - 1) + [True])

    def test_transport_hooks_write_nothing(self):
        conn = sqlite3.connect(':memory:')
        run = StoreTransport.__new__(StoreTransport)
        run.conn, run.tries = conn, {}
        m = SimpleNamespace(c=SimpleNamespace(char_id=7))
        self.assertEqual(run.claim([7, 8]), [7, 8])
        run.renew([7]), run.release([7]), run.note_invite(m), run.note_invite_unsent(m, 'e'), run.note_joined(m)
        self.assertEqual([run.failed(m, 'x') for _ in range(db.MAX_RETRIES)],
                         [False] * (db.MAX_RETRIES - 1) + [True])
        self.assertEqual(conn.execute("SELECT count(*) FROM sqlite_master").fetchone()[0], 0)


def ferry(gather=20.0):
    fs = SimpleNamespace(transport_team_size=4, gold_amount=500, gold_topup_below=380, db_path=':memory:')
    f = Ferry.__new__(Ferry)
    f.s, f.ship, f.log = fs, ShipSettings(gather=gather, timeout=5.0), None
    f.cond, f.queue, f.coming, f.closed, f.broken, f.trips = threading.Condition(), [], set(), False, None, 0
    return f


def rider(cid):
    return Rider(SimpleNamespace(char_id=cid, name=f'r{cid}'), 'box07', 1, None)


class FerryQueue(unittest.TestCase):
    def test_batch_of_four_distinct_riders(self):
        f = ferry()
        f.queue = [rider(i) for i in range(6)]
        self.assertEqual([r.c.char_id for r in f._next_batch()], [0, 1, 2, 3])
        self.assertEqual([r.c.char_id for r in f._next_batch()], [4, 5])     # nobody else coming

    def test_closed_and_empty_ends(self):
        f = ferry()
        f.closed = True
        self.assertIsNone(f._next_batch())

    def test_waits_while_someone_logs_in(self):
        f = ferry(gather=60.0)
        f.coming = {('box08', 1)}
        f.queue = [rider(1)]
        got = []
        t = threading.Thread(target=lambda: got.append(f._next_batch()))
        t.start()
        time.sleep(0.3)
        self.assertEqual(got, [])                 # still waiting for box08仓1
        f.gone(('box08', 1))                      # its login failed
        t.join(2)
        self.assertEqual([r.c.char_id for r in got[0]], [1])

    def test_broken_ferry_releases_everyone(self):
        f = ferry()
        a, b = rider(1), rider(2)
        f.queue = [b]
        f._break('调度员掉线', [a])
        self.assertTrue(a.done.is_set() and b.done.is_set())
        self.assertIn('调度员掉线', a.error)
        self.assertIn('调度员掉线', f.board(('box07', 3), rider(3)))


class StoreRows(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(':memory:')

    def test_ready_row_keeps_bag_numbers_and_adds_gold(self):
        db.save_store(self.conn, 'box07', 1, 'box07仓1', db.STORE_VILLAGE_READY, 1.0, char_id=216305, free_slots=35,
                      capacity=40, map_id=VILLAGE_MAP, x=1266, y=1174)
        db.save_store(self.conn, 'box07', 1, 'box07仓1', db.STORE_READY, 2.0, map_id=COAST_MAP, x=1781, y=1369,
                      gold=810)
        r = db.store(self.conn, 'box07', 1)
        self.assertEqual((r['status'], r['free_slots'], r['map_id'], r['x'], r['y'], r['gold']),
                         (db.STORE_READY, 35, COAST_MAP, 1781, 1369, 810))


if __name__ == '__main__':
    unittest.main()
