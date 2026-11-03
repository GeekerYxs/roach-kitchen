"""revive.decide (user 2026-11-02): a downed apprentice gets the master's revive item at once, the pet holds back."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'shitu'))

import revive as r  # noqa: E402
from provisioner.world import Fighter  # noqa: E402

ME, PET = Fighter(12, 5, False), Fighter(17, 3, False)


class Decide(unittest.TestCase):
    def test_nobody_down_leaves_the_caster_alone(self):
        self.assertEqual(r.decide(ME, PET, 4, 2, [], {}), r.Plan())

    def test_new_round_revives_the_first_downed_and_the_pet_defends(self):
        p = r.decide(ME, PET, 4, 2, [('元素使02', 11), ('元素使03', 13)], {})
        self.assertEqual(p, r.Plan(use=('元素使02', 11), pet_defend=True, block=True))

    def test_master_already_acted_this_round_blocks_without_sending(self):
        self.assertEqual(r.decide(ME, PET, 5, 2, [('元素使02', 11)], {}), r.Plan(block=True))

    def test_pet_that_already_acted_is_left_alone(self):
        p = r.decide(ME, PET, 4, 3, [('元素使02', 11)], {})
        self.assertEqual(p, r.Plan(use=('元素使02', 11), pet_defend=False, block=True))

    def test_gives_up_after_max_tries(self):
        down = [('元素使02', 11)]
        self.assertEqual(r.decide(ME, PET, 4, 2, down, {'元素使02': r.MAX_TRIES}), r.Plan())
        p = r.decide(ME, PET, 4, 2, down + [('元素使04', 14)], {'元素使02': r.MAX_TRIES})
        self.assertEqual(p.use, ('元素使04', 14))

    def test_item_already_out_this_round_blocks_without_resending(self):
        self.assertEqual(r.decide(ME, PET, 4, 2, [('元素使04', 19)], {'元素使04': 1}, {'元素使04'}), r.Plan(block=True))

    def test_dead_master_does_nothing(self):
        self.assertEqual(r.decide(Fighter(12, 5, True), PET, 4, 2, [('元素使02', 11)], {}), r.Plan())


if __name__ == '__main__':
    unittest.main()
