"""make_apprentices.slot_problem (user 2026-11-05): batch N's role slot is an upper bound, not an exact slot. mw04's
batch 2 was skipped (亿万J8 refused), so batch 3 met 1 role where the exact check wanted 2 and the team parked."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'shitu'))

from make_apprentices import slot_problem  # noqa: E402


class SlotProblem(unittest.TestCase):
    def test_normal_batches(self):
        self.assertIsNone(slot_problem([], '亿万1', 1))
        self.assertIsNone(slot_problem(['亿万1'], '亿万17', 2))
        self.assertIsNone(slot_problem(['亿万1', '亿万17'], '亿万17', 2))           # relog of batch 2's role

    def test_earlier_batch_skipped(self):
        self.assertIsNone(slot_problem(['亿万J4'], '亿万JX12', 3))                    # create: 1 role for batch 3
        self.assertIsNone(slot_problem(['亿万J4', '亿万JX12'], '亿万JX12', 3))       # enter / relog: slot 2 <= 3
        self.assertIsNone(slot_problem(['亿万J4', '亿万JX12'], '亿万J16', 4))        # batch 4 creates in slot 3

    def test_more_roles_than_batches_refused(self):
        self.assertIn('多于', slot_problem(['a', 'b', 'c'], '亿万12', 3))
        self.assertIn('靠后', slot_problem(['a', 'b', '亿万12'], '亿万12', 2))

    def test_no_batch_no_check(self):
        self.assertIsNone(slot_problem(['a', 'b', 'c'], 'x', 0))


if __name__ == '__main__':
    unittest.main()
