"""禁锢之地 (fullcrit70 jingu_47_70.patrol_stages, user 2026-11-07): all four at 61 -> (3800,3500) <-> (3300,3500)
until 65, then the usual line to 70."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

PROJECT = Path(__file__).resolve().parent.parent / 'projects' / 'fullcrit_mage_leveling_70'
sys.path.insert(0, str(PROJECT))
os.environ.setdefault('SHITU_LEADER', '曾经不曾')

import jingu_47_70 as J  # noqa: E402


class PatrolStages(unittest.TestCase):
    def points(self, low):
        return [(s['until'], s['patrol_a'], s['patrol_b']) for s in J.patrol_stages(None, low)]

    def test_below_61_runs_all_three_in_order(self):
        self.assertEqual(self.points(58), [(61, J.PATROL_A, J.PATROL_B), (65, (3800, 3500), (3300, 3500)),
                                           (70, J.PATROL_A, J.PATROL_B)])

    def test_from_61_starts_on_the_new_line(self):
        self.assertEqual(self.points(61)[0], (65, (3800, 3500), (3300, 3500)))
        self.assertEqual(self.points(64)[0], (65, (3800, 3500), (3300, 3500)))

    def test_from_65_back_to_the_usual_line(self):
        self.assertEqual(self.points(65), [(70, J.PATROL_A, J.PATROL_B)])
        self.assertEqual(self.points(70), [(70, J.PATROL_A, J.PATROL_B)])   # never an empty tuple

    def test_every_stage_keeps_the_guard_and_the_map(self):
        guard = mock.Mock()
        for s in J.patrol_stages(guard, 50):
            self.assertIs(s['done_when'], guard)
            self.assertEqual(s['maze'], 1200)


if __name__ == '__main__':
    unittest.main()
