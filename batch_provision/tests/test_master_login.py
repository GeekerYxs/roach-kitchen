"""master_login.py: account file parsing and the order accounts are tried in (no game, no real passwords)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'shitu'))

import master_login as M  # noqa: E402


class Accounts(unittest.TestCase):
    def test_parse(self):
        text = '﻿acc1密码pw1\n\nacc2 密码 pw2\nnote line\nacc3密码pw3\n'
        self.assertEqual(M.parse_accounts(text), [('acc1', 'pw1'), ('acc2', 'pw2'), ('acc3', 'pw3')])

    def test_cached_account_first(self):
        accs = [('a1', 'x'), ('a2', 'y'), ('a3', 'z')]
        self.assertEqual([a for a, _ in M.order(accs, '伏地魔3', {'伏地魔3': 'a3'})], ['a3', 'a1', 'a2'])
        self.assertEqual([a for a, _ in M.order(accs, '伏地魔3', {})], ['a1', 'a2', 'a3'])

    def test_cache_has_no_passwords(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'c.json'
            M.save_cache({'伏地魔1': 'a1', '_roles': {'a1': ['伏地魔1']}}, p)
            self.assertEqual(M.load_cache(p)['伏地魔1'], 'a1')

    def test_accounts_file_from_config(self):
        with tempfile.TemporaryDirectory() as d:
            acc = Path(d) / 'acc.txt'
            acc.write_text('a密码b\n', encoding='utf-8')
            cfg = Path(d) / 'l.toml'
            cfg.write_text(f'master_accounts = "{acc.as_posix()}"\n', encoding='utf-8')
            self.assertEqual(M.accounts_file(cfg), acc)
            cfg.write_text('teams = []\n', encoding='utf-8')
            self.assertIsNone(M.accounts_file(cfg))


if __name__ == '__main__':
    unittest.main()
