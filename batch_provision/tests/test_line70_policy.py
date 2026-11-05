"""1-70 line (projects/fullcrit_mage_leveling_70/line70_policy.py): when the team goes home and what it does there."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'projects' / 'fullcrit_mage_leveling_70'))

import line70_policy as P  # noqa: E402

FIELD = 1150


def lead(**kw):
    counts = {P.SCROLL: 25, P.SODA: 574, P.SWEET: 309, P.BENTO: 195}
    counts.update(kw.pop('counts', {}))
    return P.RoleView('曾经不曾', map_id=kw.pop('map_id', FIELD), free_slots=kw.pop('free_slots', 78),
                      counts=counts, **kw)


def app(n, **kw):
    counts = {P.SCROLL: 48}
    counts.update(kw.pop('counts', {}))
    return P.RoleView(f'元素使0{n}', map_id=kw.pop('map_id', FIELD), free_slots=kw.pop('free_slots', 10),
                      counts=counts, **kw)


APPS = tuple(app(n) for n in range(1, 5))


class FieldTrip(unittest.TestCase):
    def test_all_fine_stays(self):
        self.assertIsNone(P.field_trip(lead(), APPS))

    def test_any_full_bag_with_something_to_sell_sends_everybody_home(self):
        apps = APPS[:2] + (app(3, free_slots=2, sellable_slots=4),) + APPS[3:]
        self.assertIn('背包满', P.field_trip(lead(), apps))

    def test_leader_bag_counts_too(self):
        self.assertIn('背包满', P.field_trip(lead(free_slots=1, sellable_slots=1), APPS))

    def test_full_bag_of_unsellable_items_does_not_loop_home(self):
        apps = (app(1, free_slots=0, sellable_slots=0),) + APPS[1:]
        self.assertIsNone(P.field_trip(lead(), apps))
        self.assertEqual(P.bag_warnings(apps), ['元素使01'])

    def test_dead_apprentice_back_in_village(self):
        apps = (app(1, map_id=1, in_team=False),) + APPS[1:]
        self.assertIn('回了村', P.field_trip(lead(), apps))

    def test_offline_beats_everything(self):
        apps = (app(1, online=False, free_slots=0, sellable_slots=3),) + APPS[1:]
        self.assertIn('掉线', P.field_trip(lead(), apps))

    def test_out_of_team_in_the_field(self):
        apps = (app(2, in_team=False),) + APPS[1:]
        self.assertIn('不在队里', P.field_trip(lead(), apps))

    def test_leader_drinks_and_sweets(self):
        self.assertIn('汽水', P.field_trip(lead(counts={P.SODA: 0}), APPS))
        self.assertIn('汽水', P.field_trip(lead(counts={P.SODA: 99}), APPS))
        self.assertIsNone(P.field_trip(lead(counts={P.SODA: 100}), APPS))
        self.assertIn('甜点', P.field_trip(lead(counts={P.SWEET: 49}), APPS))


class HomeJobs(unittest.TestCase):
    def test_scrolls_below_20_go_to_50_for_everybody(self):
        self.assertEqual(P.home_job(app(1, counts={P.SCROLL: 19}), False).scrolls_to, 50)
        self.assertEqual(P.home_job(app(1, counts={P.SCROLL: 20}), False).scrolls_to, 0)
        self.assertEqual(P.home_job(lead(counts={P.SCROLL: 3}), True).scrolls_to, 50)

    def test_scrolls_counted_over_all_slots(self):
        # counts come summed over every slot (two stacks 15 + 10 = 25 -> nothing to buy)
        self.assertEqual(P.home_job(app(1, counts={P.SCROLL: 25}), False).scrolls_to, 0)

    def test_sell_at_home_when_bag_getting_full(self):
        self.assertTrue(P.home_job(app(1, free_slots=9, sellable_slots=1), False).sell)
        self.assertFalse(P.home_job(app(1, free_slots=9, sellable_slots=0), False).sell)
        self.assertFalse(P.home_job(app(1, free_slots=10, sellable_slots=5), False).sell)

    def test_apprentices_buy_no_leader_supplies(self):
        j = P.home_job(app(1, counts={P.SODA: 0, P.SWEET: 0}), False)
        self.assertEqual((j.soda_to, j.sweets_to, j.bento_to), (0, 0, 0))

    def test_leader_soda_sweets_bento(self):
        j = P.home_job(lead(), True)                       # soda 574 < 599
        self.assertEqual((j.soda_to, j.sweets_to, j.bento_to), (1485, 0, 0))
        j = P.home_job(lead(counts={P.SODA: 600, P.SWEET: 249}), True)
        self.assertEqual((j.soda_to, j.sweets_to), (0, 495))
        j = P.home_job(lead(counts={P.SODA: 10, P.BENTO: 20}), True)
        self.assertEqual(j.bento_to, 198)                  # bento only on a 汉尼拔 trip anyway
        j = P.home_job(lead(counts={P.SODA: 900, P.BENTO: 20}), True)
        self.assertEqual(j.bento_to, 0)

    def test_can_leave(self):
        self.assertEqual(P.can_leave([app(1, counts={P.SCROLL: 2}), app(2)]), ['元素使01'])


class Stages(unittest.TestCase):
    UNTILS = (10, 14, 18, 24, 28, 33, 43, 48, 53, 58, 70)

    def test_first_stage_by_lowest_apprentice(self):
        self.assertEqual(P.first_stage([57, 57, 57, 57], self.UNTILS), 9)       # 陷阱囚牢 (to 58)
        self.assertEqual(P.first_stage([58, 57, 60, 60], self.UNTILS), 9)
        self.assertEqual(P.first_stage([3, 3, 3, 3], self.UNTILS), 0)
        self.assertEqual(P.first_stage([70] * 4, self.UNTILS), 11)

    def test_stop_after_three_fails(self):
        self.assertFalse(P.stop_after(2))
        self.assertTrue(P.stop_after(3))


if __name__ == '__main__':
    unittest.main()
