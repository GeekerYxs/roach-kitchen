"""stations.toml loading and the factory.db column migration (no game needed)."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from factory import db
from provisioner.config import load_stations

GAME = Path(tempfile.gettempdir()) / 'fake_WaatClient.exe'

HEAD = f"""
[game]
exe = '{GAME}'
[batch]
"""


def station(**kw):
    base = {'id': 'dispatcher1', 'role': 'dispatcher', 'account': 'xq01', 'password': 'pw', 'slot': 1}
    base.update(kw)
    return '[[station]]\n' + ''.join(f'{k} = {v!r}\n'.replace("'", '"') if not isinstance(v, bool)
                                     else f'{k} = {str(v).lower()}\n' for k, v in base.items())


class Stations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        GAME.write_bytes(b'')

    def load(self, text):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 's.toml'
            p.write_text(HEAD + text, 'utf-8')
            return load_stations(p)

    def test_loads_enabled_station_with_slot_and_name(self):
        settings, stations = self.load(station(name='小强杀手一号', slot=2) + station(id='w', role='well',
                                                                                  account='b1', enabled=False))
        self.assertEqual(len(stations), 1)
        s = stations[0]
        self.assertEqual((s.station_id, s.role, s.account.name, s.account.slot, s.name),
                         ('dispatcher1', 'dispatcher', 'xq01', 2, '小强杀手一号'))
        self.assertEqual(settings.slot_of(s.account), 2)
        self.assertNotIn('pw', repr(s))

    def test_missing_password_is_an_error(self):
        with self.assertRaisesRegex(ValueError, '密码'):
            self.load(station(password=''))

    def test_bad_role(self):
        with self.assertRaisesRegex(ValueError, 'role'):
            self.load(station(role='boss'))

    def test_duplicate_ids(self):
        with self.assertRaisesRegex(ValueError, '重复'):
            self.load(station() + station(account='xq02'))


class Migration(unittest.TestCase):
    def test_old_file_gains_new_columns_and_keeps_rows(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'f.db'
            old = sqlite3.connect(path)
            old.executescript('CREATE TABLE stations (station_id TEXT PRIMARY KEY, role TEXT NOT NULL, '
                              'char_id INTEGER NOT NULL, status TEXT NOT NULL DEFAULT "", heartbeat_at REAL NOT NULL);'
                              "INSERT INTO stations VALUES ('s1', 'well', 9, '', 1.0);")
            old.close()
            conn = db.connect(path)
            db.register_station(conn, 's1', 'well', 9, 'b1', '大号', 123, 2.0)
            row = db.station(conn, 's1')
            self.assertEqual((row['account'], row['name'], row['pid'], row['status']), ('b1', '大号', 123, 'online'))
            self.assertEqual(db.station_roles(conn), {9: 'well'})
            conn.close()


if __name__ == '__main__':
    unittest.main()
