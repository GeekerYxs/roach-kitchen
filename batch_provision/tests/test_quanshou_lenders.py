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


class KillsSeenBefore(unittest.TestCase):
    """2026-11-01 w6: the 5th kill happened just before a restart; the rerun must count it from the tap file."""
    def test_seen_reads_old_kill_texts(self):
        import quanshou as q
        from unittest import mock

        class FakeTap:
            def ready(self):
                pass

            def poll(self):
                return [(0, 'S->C', 0x46ff, b'', None), (0, 'C->S', 0x46ff, b'', None)]
        marks = []
        with mock.patch.object(q, 'texts', lambda body: ['#00FF00#已经杀死了5个75Kg级拳手，可以回去找七十九万禁军教头了']),                 mock.patch.object(q, 'done', lambda n, k: False),                 mock.patch.object(q, 'mark', lambda n, k: marks.append((n, k))),                 mock.patch.object(q.t, 'say', lambda m: None):
            self.assertEqual(q.Kills.seen(FakeTap(), 'a'), 5)
        self.assertEqual(marks, [('a', 'kills5')])
