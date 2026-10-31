"""attach_tap.fresh_dll: the injected copy follows bin/provision_native.dll (2026-10-31: research/shitu/bin kept the
10-26 DLL under the fixed name, 亿万1 got it after the 10-29 game update and arm was refused)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'shitu'))

import attach_tap  # noqa: E402


class FreshDll(unittest.TestCase):
    def test_follows_source(self):
        with tempfile.TemporaryDirectory() as d:
            src, bin_dir = Path(d) / 'provision_native.dll', Path(d) / 'shitu' / 'bin'
            src.write_bytes(b'old')
            old = attach_tap.fresh_dll(src, bin_dir)
            self.assertEqual(old.read_bytes(), b'old')
            self.assertEqual(attach_tap.fresh_dll(src, bin_dir), old)          # same content: same copy
            src.write_bytes(b'new')
            new = attach_tap.fresh_dll(src, bin_dir)
            self.assertNotEqual(new, old)
            self.assertEqual(new.read_bytes(), b'new')
            self.assertEqual(old.read_bytes(), b'old')                          # a loaded old copy is left alone
            self.assertEqual(new.parent, bin_dir)                               # tap files: <dll dir>/../runtime


if __name__ == '__main__':
    unittest.main()
