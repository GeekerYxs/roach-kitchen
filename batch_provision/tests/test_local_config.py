"""local.toml overlay: per-machine game path, alt range and passwords (no game needed)."""
import tempfile
import unittest
from pathlib import Path

from provisioner import config
from provisioner.config import merge_local

GAME = Path(tempfile.gettempdir()) / 'fake_WaatClient.exe'
LOCAL = {'game': {'exe': str(GAME)},
         'accounts': {'prefix': 'mw', 'start': 301, 'count': 60, 'digits': 2, 'password': 'p1'},
         'passwords': {'xq01': 'big'}}


class Merge(unittest.TestCase):
    def test_game_is_always_applied(self):
        out = merge_local({'game': {'exe': 'old', 'server_index': 0}}, LOCAL)
        self.assertEqual(out['game'], {'exe': str(GAME), 'server_index': 0})
        self.assertEqual(merge_local({}, LOCAL)['game'], {'exe': str(GAME)})

    def test_missing_or_empty_accounts_take_the_machine_range(self):
        self.assertEqual(merge_local({}, LOCAL)['accounts'], LOCAL['accounts'])
        self.assertEqual(merge_local({'accounts': {}}, LOCAL)['accounts'], LOCAL['accounts'])

    def test_tool_keys_win_and_the_rest_comes_from_local(self):
        acc = merge_local({'accounts': {'count': 8}}, LOCAL)['accounts']
        self.assertEqual((acc['start'], acc['count'], acc['password']), (301, 8, 'p1'))

    def test_list_items_get_passwords(self):
        out = merge_local({'accounts': {'list': [{'account': 'xq01'}, {'account': 'mw9'},
                                                 {'account': 'a', 'password': 'own'}]}}, LOCAL)
        self.assertEqual([x['password'] for x in out['accounts']['list']], ['big', 'p1', 'own'])

    def test_station_passwords_from_passwords_section(self):
        out = merge_local({'station': [{'account': 'xq01'}, {'account': 'nobody'}]}, LOCAL)
        self.assertEqual([x['password'] for x in out['station']], ['big', ''])

    def test_local_stations_replace_the_shared_list(self):
        local = {**LOCAL, 'station': [{'id': 'receiver1', 'account': 'xq01'}]}
        out = merge_local({'station': [{'id': 'receiver1', 'account': 'hz01'}, {'id': 'well1', 'account': 'q'}]},
                          local)
        self.assertEqual(out['station'], [{'id': 'receiver1', 'account': 'xq01', 'password': 'big'}])
        self.assertNotIn('station', merge_local({'batch': {}}, local))

    def test_other_sections_only_override_existing_ones(self):
        local = {**LOCAL, 'supervisor': {'max_windows': 12}}
        self.assertEqual(merge_local({'supervisor': {'max_windows': 20, 'fresh': True}}, local)['supervisor'],
                         {'max_windows': 12, 'fresh': True})
        self.assertNotIn('supervisor', merge_local({'batch': {}}, local))

    def test_input_is_not_modified(self):
        data = {'accounts': {'count': 8}, 'game': {'server_index': 0}}
        merge_local(data, LOCAL)
        self.assertEqual(data, {'accounts': {'count': 8}, 'game': {'server_index': 0}})


class ReadFiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        GAME.write_bytes(b'')

    def load(self, tool, local=None):
        with tempfile.TemporaryDirectory() as d:
            if local is not None:
                (Path(d) / 'local.toml').write_text(local, 'utf-8')
            p = Path(d) / 'pipeline.toml'
            p.write_text(tool, 'utf-8')
            return config.load_pipeline(p)

    def test_local_next_to_the_tool_file_is_used(self):
        s = self.load('[game]\nserver_index = 0\n[batch]\n[accounts]\n',
                      f"[game]\nexe = '{GAME}'\n[accounts]\nprefix = 'mw'\nstart = 301\ncount = 60\n"
                      "digits = 2\npassword = 'p1'\n")
        self.assertEqual((len(s.accounts), s.accounts[0].name, s.accounts[-1].name), (60, 'mw301', 'mw360'))
        self.assertEqual(s.game_exe, GAME)

    def test_without_local_a_clear_error(self):
        with self.assertRaisesRegex(ValueError, 'local.toml'):
            self.load('[game]\nserver_index = 0\n[batch]\n[accounts]\n')


if __name__ == '__main__':
    unittest.main()
