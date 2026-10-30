"""exp_trial.py (exp-map trial report): monster level, per-map/level summary, minutes per level, best map (no game)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'shitu'))

import exp_trial as E  # noqa: E402


def battle(role, start, level, m, gain, cycle, mons=(), after=None):
    return dict(role=role, start=start, level=level, level_after=after or level, map=m, gain=gain, fight=8.0,
                cycle=cycle, enemies=len(mons), enemy_levels=tuple(mons))


class ExpTrial(unittest.TestCase):
    def test_l_eff_rounds_half_up(self):
        self.assertEqual(E.l_eff((33, 33, 34, 34)), 34)          # 33.5 -> 34
        self.assertEqual(E.l_eff((33, 33, 33, 34)), 33)
        self.assertIsNone(E.l_eff(()))

    def test_by_map_level_skips_level_up_battles(self):
        rs = [battle('a', 0, 28, 280, 4600, 18.0, (33, 33, 34, 34, 35)),
              battle('a', 20, 28, 280, 4800, 20.0, (33, 34, 34, 35, 35)),
              battle('a', 40, 28, 280, 9999, 19.0, (33,), after=29)]
        s = E.by_map_level(rs)[(280, 28)]
        self.assertEqual(s['n'], 2)
        self.assertEqual(s['gain'], 4700)
        self.assertAlmostEqual(s['per_min'], 4700 / 19 * 60)
        self.assertEqual((s['mon_lo'], s['mon_hi'], s['enemies']), (33, 35, 5))
        self.assertEqual(s['l_eff'], 34)

    def test_level_minutes(self):
        rs = [battle('a', 0, 10, 555, 1, 1), battle('a', 600, 11, 555, 1, 1), battle('a', 1500, 12, 555, 1, 1),
              battle('b', 60, 10, 555, 1, 1), battle('b', 780, 11, 555, 1, 1)]
        m = E.level_minutes(rs)
        self.assertAlmostEqual(m[10], (10 + 12) / 2)
        self.assertAlmostEqual(m[11], 15)
        self.assertNotIn(12, m)

    def test_best_maps_needs_enough_battles_and_a_training_map(self):
        t = {'oa': {(750, 27): dict(per_min=10000, n=20), (280, 27): dict(per_min=14000, n=5),
                    (141, 27): dict(per_min=99999, n=50)},
             'ob': {(280, 27): dict(per_min=13000, n=30)}}
        self.assertEqual(E.best_maps(t), {27: ('ob', 280, 13000)})

    def test_rows_from_battlelog_db(self):
        import sqlite3
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'b.sqlite'
            db = sqlite3.connect(path)
            db.execute('create table battles (role, start_time, fight_s, map_id, level, level_after, exp, '
                       'monster_count, monster_levels)')
            db.executemany('insert into battles values (?,?,?,?,?,?,?,?,?)', [
                ('a', 100.0, 8.0, 280, 28, None, 4600, 5, '33 33 34 34 35'),
                ('a', 112.0, 8.0, 280, 28, None, 4700, 5, '33 33 33 34 34'),
                ('a', 500.0, 8.0, 280, 29, None, 4800, 5, '33 33 33 33 33'),   # 388 s later: a trip, no cycle
                ('a', 50.0, 8.0, 280, None, None, 1, 5, ''),                   # level not read: skipped
                ('b', 100.0, 8.0, 750, 25, 25, 2400, 4, '26 27 28 28')])
            db.commit()
            db.close()
            rs = E.rows_db({'a', 'b'}, 0, path)
        a = [r for r in rs if r['role'] == 'a']
        self.assertEqual([r['cycle'] for r in a], [12.0, None, None])
        self.assertEqual([r['level_after'] for r in a], [28, 29, 29])        # from the next battle
        self.assertEqual(a[0]['enemy_levels'], (33, 33, 34, 34, 35))
        self.assertEqual(len([r for r in rs if r['role'] == 'b']), 1)


if __name__ == '__main__':
    unittest.main()
