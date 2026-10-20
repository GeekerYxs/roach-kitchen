"""Unit tests for moving stores rows between machines (factory/storexfer.py)."""
import sqlite3
import unittest

from factory import db
from factory.storexfer import COLUMNS, plan_import, write_row


def row(slot=1, status=db.STORE_READY, at=10.0, dishes=None):
    r = dict.fromkeys(COLUMNS)
    r.update(account='box07', slot=slot, name=f'box07仓{slot}', status=status, updated_at=at, dishes=dishes)
    return r


class Plan(unittest.TestCase):
    def test_actions(self):
        existing = [row(1, at=10.0), row(2, at=50.0, dishes=99), row(3, db.STORE_VILLAGE_READY, at=5.0)]
        incoming = [row(1, at=10.0), row(2, at=20.0), row(3, at=30.0), row(4, at=30.0)]
        self.assertEqual([a for _, a in plan_import(existing, incoming)], ['same', 'keep', 'update', 'add'])


class Write(unittest.TestCase):
    def test_round_trip(self):
        conn = sqlite3.connect(':memory:', isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.executescript(db.SCHEMA)
        db._migrate(conn)
        r = row(1, dishes=290)
        write_row(conn, r)
        write_row(conn, r)                 # twice: still one row
        rows = [dict(x) for x in db.stores(conn)]
        self.assertEqual(rows, [r])
        self.assertEqual([a for _, a in plan_import(rows, [r])], ['same'])


if __name__ == '__main__':
    unittest.main()
