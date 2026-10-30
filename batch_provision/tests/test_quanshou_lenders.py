"""quanshou.lenders: who lends 回城卷 to whom (no game)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'shitu'))

import quanshou as Q  # noqa: E402


class Lenders(unittest.TestCase):
    def test_both_directions(self):
        masters, apps = ('曾经不曾',), ('Opus55A5', 'Opus55A6')
        self.assertEqual(Q.lenders('曾经不曾', masters, apps), ['Opus55A5', 'Opus55A6'])   # 2026-10-28
        self.assertEqual(Q.lenders('Opus55A6', masters, apps), ['曾经不曾'])                # 2026-10-30
        self.assertEqual(Q.lenders('stranger', masters, apps), [])


if __name__ == '__main__':
    unittest.main()
