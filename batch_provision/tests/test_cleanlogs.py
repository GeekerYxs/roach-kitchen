"""Unit tests for the log cleaner: age filter, deleting, empty-folder pruning (temp folders only)."""
import tempfile
import time
import unittest
from pathlib import Path

from provisioner.cleanlogs import prune_dirs, remove, scan, select


class Select(unittest.TestCase):
    def test_keep_hours(self):
        now = 10000.0
        files = [('old', now - 7200, 1), ('new', now - 60, 1)]
        self.assertEqual([f[0] for f in select(files, now, 3600)], ['old'])
        self.assertEqual(len(select(files, now, 0)), 2)


class Remove(unittest.TestCase):
    def test_remove_and_prune(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'sub').mkdir()
            (root / 'a.log').write_text('x' * 10)
            (root / 'sub' / 'b.json').write_text('y')
            files = scan(root)
            done, freed, skipped = remove(files)
            prune_dirs(root)
            self.assertEqual((done, freed, skipped), (2, 11, []))
            self.assertEqual(list(root.iterdir()), [])
            self.assertTrue(root.is_dir())

    def test_missing_file_is_skipped(self):
        p = Path(tempfile.gettempdir()) / f'nope_{time.time_ns()}.log'
        self.assertEqual(remove([(p, 0, 5)]), (0, 0, [p]))


if __name__ == '__main__':
    unittest.main()
