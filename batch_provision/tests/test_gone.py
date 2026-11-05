"""trial_run.Gone (user 2026-11-05): a role that reads no world state for GONE_AFTER s (dropped, at the login screen)
fails the leveling loop at once instead of the line's 15-minute silent-log watchdog; a map change (1-3 s) does not."""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent / 'research' / 'shitu'
sys.path.insert(0, str(HERE))

import trial_run as t  # noqa: E402


class Gone(unittest.TestCase):
    def run_ticks(self, frames, step=1.0, after=30):
        clock = [0.0]
        g = t.Gone(after=after, clock=lambda: clock[0])
        out = []
        for f in frames:
            out.append(g.tick(f))
            clock[0] += step
        return out

    def test_all_read(self):
        self.assertEqual(self.run_ticks([{'a': 1, 'b': 2}] * 5), [False] * 5)

    def test_map_change_is_skipped_not_failed(self):
        frames = [{'a': 1}, {'a': None}, {'a': None}, {'a': None}, {'a': 1}] + [{'a': None}] * 3
        self.assertEqual(self.run_ticks(frames), [False, True, True, True, False, True, True, True])

    def test_dropped_fails_after_the_limit(self):
        with self.assertRaises(t.Stop) as e:
            self.run_ticks([{'a': 1, 'b': None}] * 40)
        self.assertIn("['b']", str(e.exception))

    def test_loops_use_it(self):
        for f in ('well10.py', 'lunhui15.py', 'maze_train.py'):
            src = (HERE / f).read_text(encoding='utf-8')
            self.assertIn('gone = t.Gone()', src, f)
            self.assertIn('if gone.tick(sts):', src, f)
            self.assertNotIn('if any(s is None for s in sts.values()):', src, f)


if __name__ == '__main__':
    unittest.main()
