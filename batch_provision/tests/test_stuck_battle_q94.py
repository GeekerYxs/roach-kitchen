"""Gemini test machine 2026-11-07 (6 teams x 2 batches):
  - line.ops.q94 called take224.talk after 6cfed39 had dropped its import -> NameError in every team's zhuanzhi. Now
    every module is checked for undefined names (pyflakes, when installed).
  - 伏一勇06's client froze in an old battle in 通天塔一区 for 47 min; trial_run.StuckBattle closes it and stops."""
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'research' / 'shitu'))

import trial_run as t  # noqa: E402


def st(in_battle):
    return NS(in_battle=in_battle)


class Stuck(unittest.TestCase):
    def setUp(self):
        self.closed = []
        self.sb = t.StuckBattle({}, 'L', close=lambda cs, names: self.closed.extend(names) or {n: 'ok' for n in names})

    def run_battles(self, n, frozen=('B',), lag_ticks=0):
        """n leader battles; members not frozen leave each battle lag_ticks ticks after the leader."""
        battles = 0
        for _ in range(n):
            self.sb.tick({'L': st(True), 'A': st(True), 'B': st(True)}, battles)
            battles += 1                    # the loop counts the start after reading the states
            self.sb.tick({'L': st(True), 'A': st(True), 'B': st(True)}, battles)
            for _ in range(lag_ticks):
                self.sb.tick({'L': st(False), 'A': st(True), 'B': st('B' in frozen or True)}, battles)
            self.sb.tick({'L': st(False), 'A': st(False), 'B': st('B' in frozen)}, battles)

    def test_frozen_member_closed_after_three_battles(self):
        with self.assertRaises(t.Stop) as e:
            self.run_battles(5)
        self.assertEqual(self.closed, ['B'])
        self.assertIn('旧战斗', str(e.exception))

    def test_two_battles_not_yet(self):
        self.run_battles(2)
        self.assertEqual(self.closed, [])

    def test_members_leaving_late_are_fine(self):
        self.run_battles(20, frozen=(), lag_ticks=5)
        self.assertEqual(self.closed, [])

    def test_never_while_the_leader_fights(self):
        for b in range(10):
            self.sb.tick({'L': st(True), 'B': st(True)}, b)
        self.assertEqual(self.closed, [])

    def test_unread_member_resets(self):
        self.sb.tick({'L': st(True), 'B': st(True)}, 0)
        self.sb.tick({'L': st(False), 'B': None}, 5)
        self.sb.tick({'L': st(False), 'B': st(False)}, 5)
        self.assertEqual(self.closed, [])


class UndefinedNames(unittest.TestCase):
    def test_no_undefined_names(self):
        try:
            import pyflakes  # noqa: F401
        except ImportError:
            self.skipTest('pyflakes not installed')
        out = subprocess.run([sys.executable, '-m', 'pyflakes', str(ROOT)], capture_output=True, text=True,
                             encoding='utf-8', errors='replace').stdout
        bad = [line for line in out.splitlines() if 'undefined name' in line]
        self.assertEqual(bad, [])


if __name__ == '__main__':
    unittest.main()
