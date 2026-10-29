"""Unit tests for the exp monitor logic (no game needed)."""
import tempfile
import unittest
from pathlib import Path

from expwatch import core
from provisioner import world

TABLE = core.load_table(Path(__file__).resolve().parent.parent / 'expwatch' / 'explib.csv')


def S(t, b, level=46, exp=0, map_id=1100):
    return core.Sample(t, b, level, exp, map_id)


class Table(unittest.TestCase):
    def test_values_from_client_table(self):
        self.assertEqual(TABLE[45], 712606)
        self.assertEqual(TABLE[49], 1227567)
        self.assertEqual(core.range_need(TABLE, 45, 50), 712606 + 816708 + 935768 + 1071912 + 1227567)

    def test_gained_same_level_and_level_up(self):
        self.assertEqual(core.gained(TABLE, 46, 100, 46, 3671), 3571)
        self.assertEqual(core.gained(TABLE, 46, TABLE[46] - 1000, 47, 2571), 3571)
        self.assertEqual(core.gained(TABLE, 46, TABLE[46] - 10, 48, 5), 10 + TABLE[47] + 5)
        self.assertIsNone(core.gained(TABLE, 47, 0, 46, 0))
        self.assertIsNone(core.gained(TABLE, 46, 500, 46, 400))

    def test_remaining(self):
        self.assertEqual(core.remaining(TABLE, 46, 16708, 47), 800000)
        self.assertEqual(core.remaining(TABLE, 46, 0, 48), TABLE[46] + TABLE[47])
        self.assertEqual(core.remaining(TABLE, 50, 0, 50), 0)


class Tracking(unittest.TestCase):
    def feed(self, samples):
        tr = core.Tracker('cap07', TABLE)
        out = []
        for s in samples:
            out += tr.feed(s)
        return out

    def test_battle_closed_at_next_start(self):
        out = self.feed([S(0, False, exp=100), S(1, True, exp=100), S(20, True, exp=100), S(21, False, exp=3671),
                         S(30, False, exp=3671), S(31, True, exp=3671)])
        self.assertEqual(len(out), 1)
        b = out[0]
        self.assertEqual((b.start, b.fight, b.cycle, b.gain, b.level), (1, 20, 30, 3571, 46))

    def test_battle_running_at_start_is_skipped(self):
        out = self.feed([S(0, True, exp=0), S(5, False, exp=3571), S(10, True, exp=3571), S(20, False, exp=7142),
                         S(25, True, exp=7142)])
        self.assertEqual([(b.start, b.gain) for b in out], [(10, 3571)])

    def test_pause_closes_without_cycle(self):
        out = self.feed([S(0, False), S(1, True), S(10, False, exp=3000), S(10 + core.IDLE_CLOSE, False, exp=3000)])
        self.assertEqual(len(out), 1)
        self.assertIsNone(out[0].cycle)
        self.assertEqual(out[0].gain, 3000)

    def test_enemy_levels_from_the_fullest_sample(self):
        out = self.feed([S(0, False), core.Sample(1, True, 46, 0, 700, 4, (21, 21, 22, 22)),
                         core.Sample(5, True, 46, 0, 700, 2, (21, 22)), S(9, False, exp=984), S(15, True, exp=984)])
        self.assertEqual((out[0].enemies, out[0].enemy_levels), (4, (21, 21, 22, 22)))

    def test_enemy_levels_filled_when_first_sample_had_none(self):
        out = self.feed([S(0, False), core.Sample(1, True, 46, 0, 700, 4, ()),
                         core.Sample(2, True, 46, 0, 700, 4, (21, 22, 22, 22)), S(9, False, exp=9), S(15, True, exp=9)])
        self.assertEqual(out[0].enemy_levels, (21, 22, 22, 22))

    def test_enemy_text(self):
        self.assertEqual(core.enemy_text((21, 21, 22)), ' 怪3只21~22级')
        self.assertEqual(core.enemy_text((51,)), ' 怪1只51级')
        self.assertEqual(core.enemy_text(()), '')

    def test_level_up_inside_battle(self):
        out = self.feed([S(0, False, exp=TABLE[46] - 100), S(1, True, exp=TABLE[46] - 100),
                         S(9, False, level=47, exp=3471), S(15, True, level=47, exp=3471)])
        self.assertEqual((out[0].gain, out[0].level, out[0].level_after), (3571, 46, 47))
        self.assertEqual(core.level_ups(out), {'cap07': {47: 9}})


class FighterLevels(unittest.TestCase):
    def test_rows_keyed_by_pos_not_order(self):
        def r(pos, lv):
            b = bytearray(world.GRADE_ROW)
            b[world.GRADE_POS:world.GRADE_POS + 4] = pos.to_bytes(4, 'little', signed=True)
            b[world.GRADE_LEVEL:world.GRADE_LEVEL + 4] = lv.to_bytes(4, 'little')
            return bytes(b)
        # Live 2026-10-29 八阵图: rows out of position order, the 70 leader first, empty rows pos -1.
        block = r(17, 70) + r(2, 21) + r(0, 22) + r(-1, 0) + r(5, 0)
        self.assertEqual(world.grades_by_pos(block), {17: 70, 2: 21, 0: 22})


def B(role, start, level, gain, cycle=30.0, level_after=None):
    return core.Battle(role, start, 20.0, cycle, level, 0, level_after or level, 0, gain, 1100)


class Rates(unittest.TestCase):
    def test_rate_ignores_paused(self):
        r = core.rate([B('a', 0, 46, 3600, cycle=36), B('a', 1, 46, 3600, cycle=None)])
        self.assertEqual((r.battles, r.avg_gain, r.per_hour), (1, 3600, 360000))
        self.assertIsNone(core.rate([B('a', 0, 46, 1, cycle=None)]))

    def test_estimate_borrows_nearest_level(self):
        rates = core.level_rates([B('a', 0, 46, 100, cycle=1), B('a', 1, 48, 200, cycle=1)])
        h, measured, borrowed = core.estimate_hours(TABLE, rates, 45, 50)
        self.assertEqual(measured, [46, 48])
        self.assertEqual(borrowed, {45: 46, 47: 48, 49: 48})     # 47 is a tie -> the higher level
        want = (TABLE[45] + TABLE[46]) / 360000 + (TABLE[47] + TABLE[48] + TABLE[49]) / 720000
        self.assertAlmostEqual(h, want)
        self.assertIsNone(core.estimate_hours(TABLE, {}, 45, 50))

    def test_measured_hours_from_level_ups(self):
        bs = [B('a', 0, 44, 1, level_after=45), B('a', 7200, 49, 1, level_after=50), B('b', 0, 49, 1, level_after=50)]
        self.assertEqual(core.measured_hours(core.level_ups(bs), 45, 50), {'a': 2.0})

    def test_csv_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'x' / 'battles.csv'
            bs = [B('cap07', 1.5, 46, 3571), B('cap08', 2.0, 46, 3571, cycle=None),
                  core.Battle('cap09', 3.0, 9.0, 15.0, 22, 0, 22, 1582, 1582, 700, 4, (21, 21, 22, 22))]
            core.append_battles(p, bs[:1])
            core.append_battles(p, bs[1:])
            self.assertEqual(core.read_battles(p), bs)

    def test_old_csv_without_level_column_is_rewritten(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'battles.csv'
            p.write_text('role,start,fight,cycle,level,exp_before,level_after,exp_after,gain,map_id,enemies\n'
                         'a,1.0,8.0,12.5,28,0,28,734,734,141,5\n', encoding='utf-8')
            new = core.Battle('b', 2.0, 9.0, 15.0, 22, 0, 22, 1582, 1582, 700, 4, (21, 22))
            core.append_battles(p, [new])
            got = core.read_battles(p)
            self.assertEqual(got[0].enemy_levels, ())
            self.assertEqual(got[0].enemies, 5)
            self.assertEqual(got[1], new)
            self.assertTrue(p.read_text(encoding='utf-8').startswith(','.join(core.FIELDS)))


if __name__ == '__main__':
    unittest.main()
