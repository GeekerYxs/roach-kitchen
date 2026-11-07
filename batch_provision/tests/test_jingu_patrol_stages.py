"""禁锢之地 / 记忆之地 (fullcrit70 jingu_47_70, user 2026-11-07): all four at 61 -> (3800,3500) <-> (3300,3500)
until 65, then out to 记忆之地 (3400,850) <-> (3000,1100) until 70."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

PROJECT = Path(__file__).resolve().parent.parent / 'projects' / 'fullcrit_mage_leveling_70'
sys.path.insert(0, str(PROJECT))
os.environ.setdefault('SHITU_LEADER', '曾经不曾')

import jingu_47_70 as J  # noqa: E402
import memory_land as ML  # noqa: E402

MID = ((3800, 3500), (3300, 3500))
MEM = ((3400, 850), (3000, 1100))


class PatrolStages(unittest.TestCase):
    def points(self, low):
        return [(s['maze'], s['until'], s['patrol_a'], s['patrol_b']) for s in J.patrol_stages(None, low)]

    def test_below_61_runs_all_three_in_order(self):
        self.assertEqual(self.points(58), [(1200, 61, J.PATROL_A, J.PATROL_B), (1200, 65, *MID), (1250, 70, *MEM)])

    def test_61_to_64_on_the_new_line(self):
        self.assertEqual(self.points(61)[0], (1200, 65, *MID))
        self.assertEqual(self.points(64)[0], (1200, 65, *MID))

    def test_from_65_in_memory_land(self):
        self.assertEqual(self.points(65), [(1250, 70, *MEM)])
        self.assertEqual(self.points(70), [(1250, 70, *MEM)])   # never an empty tuple

    def test_memory_stage_walks_out_of_1200_through_181_and_182(self):
        legs = J.patrol_stages(None, 65)[0]['legs']
        self.assertEqual(sorted(legs), [181, 182, 1200])
        self.assertEqual(legs[1200], ('walk', 1200, (9024, 5916)))
        self.assertEqual(legs[181], ('walk', 181, (4104, 1368)))
        self.assertEqual(legs[182], ('click', 10186, (228, 1065)))   # live 2026-11-07: standing there does nothing

    def test_every_stage_keeps_the_guard(self):
        guard = mock.Mock()
        for s in J.patrol_stages(guard, 50):
            self.assertIs(s['done_when'], guard)


class LeftMembers(unittest.TestCase):
    def test_crossing_a_link_is_not_leaving(self):
        since = {}
        maps = {'L': 181, 'a': 1200, 'b': 1200}
        self.assertEqual(J.left_members(maps, 181, ML.WAY, since, 0.0), {})
        self.assertEqual(J.left_members(maps, 181, ML.WAY, since, 5.0), {})
        self.assertEqual(J.left_members({'L': 181, 'a': 181, 'b': 181}, 181, ML.WAY, since, 6.0), {})
        self.assertEqual(since, {})

    def test_stuck_behind_for_10_s_counts(self):
        since = {}
        J.left_members({'L': 182, 'a': 181}, 182, ML.WAY, since, 0.0)
        self.assertEqual(J.left_members({'L': 182, 'a': 181}, 182, ML.WAY, since, 10.0), {'a': 181})

    def test_dead_member_in_the_village(self):
        since = {}
        J.left_members({'L': 1200, 'a': 1}, 1200, (1200,), since, 0.0)
        self.assertEqual(J.left_members({'L': 1200, 'a': 1}, 1200, (1200,), since, 10.0), {'a': 1})

    def test_below_65_only_1200_is_allowed(self):
        self.assertEqual(J.allowed_maps(64), (1200,))
        self.assertEqual(J.allowed_maps(65), ML.WAY)
        self.assertEqual(J.resume_maps(64), (1200,))
        self.assertEqual(J.resume_maps(66), (1200, 1250))


if __name__ == '__main__':
    unittest.main()
