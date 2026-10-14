"""Unit tests for the wipe tool (delete every role of an account range): pure decisions, DB records, report."""
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from factory import db
from factory.delete import ACTION
from factory.phase import DELETED
from factory.wipe import (DELETE, DONE, SKIP, AccountResult, account_names, deleting_candidates, next_target,
                          own_role, plan_account, stale_rows, supervisor_alive, window_roles, write_report)


def row(cid, name, phase='coast', deleted_at=None, pending=None):
    return {'char_id': cid, 'name': name, 'phase': phase, 'deleted_at': deleted_at, 'pending_action': pending}


class Names(unittest.TestCase):
    def test_range(self):
        self.assertEqual(account_names('mw', 2, 301, 303), ['mw301', 'mw302', 'mw303'])
        self.assertEqual(account_names('mw', 2, 1, 2), ['mw01', 'mw02'])
        self.assertEqual(len(account_names('mw', 2, 301, 380)), 80)

    def test_bad_range(self):
        with self.assertRaises(ValueError):
            account_names('mw', 2, 380, 301)
        with self.assertRaises(ValueError):
            account_names('mw', 2, 1, 5000)

    def test_own_role(self):
        self.assertTrue(own_role('mw301r5', 'mw301'))
        self.assertFalse(own_role('mw3011r1', 'mw301'))
        self.assertFalse(own_role('m56cf105r4', 'mw105'))
        self.assertFalse(own_role('伏地魔1', 'mw301'))


class Plan(unittest.TestCase):
    roster = [(1, 12, 'mw301r1'), (2, 2, 'mw301r2'), (3, 11, 'mw301r3'), (4, 5, 'mw301r4')]

    def test_actions(self):
        rows = {2: row(2, 'mw301r2', DELETED, deleted_at=1.0), 3: row(3, 'mw301r3', pending=ACTION),
                4: row(4, 'other')}
        plan = plan_account(self.roster, rows, station_ids=set())
        self.assertEqual([p['action'] for p in plan], [DELETE, DONE, SKIP, SKIP])
        self.assertEqual([p['slot'] for p in plan], [1, 2, 3, 4])

    def test_station_never_deleted(self):
        plan = plan_account([(9, 70, '伏地魔1')], {}, station_ids={9})
        self.assertEqual(plan[0]['action'], SKIP)

    def test_unknown_role_is_deleted(self):
        self.assertEqual(plan_account([(7, 1, 'x')], {}, set())[0]['action'], DELETE)

    def test_next_target(self):
        plan = plan_account(self.roster, {}, set())
        self.assertEqual(next_target(plan, set())['char_id'], 1)
        self.assertEqual(next_target(plan, {1, 2})['char_id'], 3)
        self.assertIsNone(next_target(plan, {1, 2, 3, 4}))

    def test_stale(self):
        rows = [row(1, 'a'), row(5, 'gone'), row(6, 'old', DELETED, 1.0)]
        self.assertEqual([r['char_id'] for r in stale_rows(rows, {1})], [5])


class Guards(unittest.TestCase):
    def test_supervisor_alive(self):
        now = 1000.0
        beats = [('coast1', 'farming', 950.0), ('well1', 'offline', 990.0), ('recv', 'idle', 100.0)]
        self.assertEqual(supervisor_alive(beats, now, 120), ['coast1'])

    def test_window_roles(self):
        titles = {11: ['什么什么大冒险2(①逍遥村)-mw301r2_Sep 24 2026'], 12: ['什么什么大冒险2(x)-伏地魔1_Sep'],
                  13: ['什么什么大冒险2(x)-mw01r1_Sep'], 14: ['选角']}
        self.assertEqual(window_roles(titles, {'mw301', 'mw302'}), [(11, 'mw301r2', 'mw301')])


class Candidates(unittest.TestCase):
    def test_field_found(self):
        def entry(flag, noise):
            e = bytearray(0x6C)
            e[0] = noise                 # id: not a candidate (before NAME_END)
            e[0x30] = flag
            e[0x40] = noise
            return bytes(e)
        deleted = [entry(1, 3), entry(1, 4)]
        alive = [entry(0, 3), entry(0, 5)]
        self.assertEqual(deleting_candidates(deleted, alive), [(0x30, 1)])
        self.assertEqual(deleting_candidates(deleted, []), [])


class DbRecords(unittest.TestCase):
    def test_mark_gone_keeps_first_delete_time(self):
        conn = db.connect(':memory:')
        db.register_alt(conn, 1, 'mw301', 1, 'mw301r1', 10.0)
        db.register_alt(conn, 2, 'mw301', 2, 'mw301r2', 10.0)
        db.mark_deleted(conn, 2, 50.0, 1)
        db.mark_gone(conn, 1, 100.0)
        db.mark_gone(conn, 2, 200.0)
        self.assertEqual((db.alt(conn, 1)['phase'], db.alt(conn, 1)['deleted_at']), (DELETED, 100.0))
        self.assertEqual(db.alt(conn, 2)['deleted_at'], 50.0)


class Report(unittest.TestCase):
    def test_report_files(self):
        now = time.time()
        res = [AccountResult('mw301', roles=[
                   {'slot': 1, 'char_id': 1, 'level': 12, 'name': 'mw301r1', 'action': DELETE, 'why': '',
                    'result': '已删除', 'detail': '150ms', 'deleted_at': now},
                   {'slot': 2, 'char_id': 2, 'level': 2, 'name': 'm56cf', 'action': DELETE, 'why': '',
                    'result': '失败', 'detail': 'RuntimeError: x'}], logins=2, seconds=20),
               AccountResult('mw302', logins=1, seconds=8),
               AccountResult('mw303', error='登录失败', logins=1)]
        ws = SimpleNamespace(release_hours=3.2)
        with tempfile.TemporaryDirectory() as d:
            md = write_report(Path(d) / 'wipe_20261014_120000', res, ws, 'mw301..mw303', False, 60, [(0x30, 1)])
            text = md.read_text('utf-8')
            self.assertIn('| 已删除 | 1 |', text)
            self.assertIn('mw302', text.split('## 空账号')[1])
            self.assertIn('m56cf', text.split('## 不是')[1])
            self.assertIn('+0x30=01', text)
            self.assertTrue((Path(d) / 'wipe_roles_20261014_120000.csv').is_file())
            self.assertTrue((Path(d) / 'wipe_20261014_120000.json').is_file())


if __name__ == '__main__':
    unittest.main()
