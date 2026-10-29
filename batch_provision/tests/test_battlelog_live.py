"""Unit tests for battlelog.live (no game needed): the memory tracker and the merge into battles."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from battlelog import decode, live, store            # noqa: E402
from expwatch import core as expcore                  # noqa: E402

TABLE = expcore.load_table(Path(__file__).resolve().parent.parent / 'expwatch' / 'explib.csv')


def S(t, b, exp=0, gold=100, bag=None, quiz=False, level=22):
    return live.MemSample(t, b, 700, 1000, 1735, level, exp, quiz, gold, bag if bag is not None else {9801: 5})


class Tracker(unittest.TestCase):
    def feed(self, samples):
        tr = live.MemTracker(TABLE)
        out = []
        for s in samples:
            out += tr.feed(s)
        return out

    def test_cycle_gold_bag_quiz_patrol(self):
        out = self.feed([
            S(0, False), S(1, True), S(9, False, exp=1582, bag={9801: 5, 65271: 1}),
            S(10, False, exp=1582, quiz=True), S(14, False, exp=1582, quiz=True), S(15, False, exp=1582),
            S(20, False, exp=1582, gold=60, bag={9801: 4, 65271: 1}),              # sold / used while patrolling
            S(21, True, exp=1582, gold=60, bag={9801: 4, 65271: 1}),
            S(30, False, exp=3164, gold=60, bag={9801: 4, 65271: 2}),
            S(41, True, exp=3164, gold=60, bag={9801: 4, 65271: 2})])
        a, b = out
        self.assertEqual((a.start_time, a.end_time, a.exp_gain, a.patrol_s), (1, 9, 1582, None))
        self.assertEqual((a.gold_before, a.gold_after), (100, 60))
        self.assertEqual(a.bag_delta, {9801: -1, 65271: 1})
        self.assertEqual((a.quiz_count, a.quiz_s), (1, 5.0))
        self.assertEqual((b.patrol_s, b.exp_gain, b.bag_delta, b.quiz_count), (12.0, 1582, {65271: 1}, 0))

    def test_level_up_and_idle_close(self):
        out = self.feed([S(0, False, exp=TABLE[22] - 100), S(1, True, exp=TABLE[22] - 100),
                         S(9, False, exp=50, level=23), S(9 + live.IDLE_CLOSE, False, exp=50, level=23)])
        (b,) = out
        self.assertEqual((b.level, b.level_after, b.exp_gain), (22, 23, 150))

    def test_battle_running_at_start_is_skipped(self):
        self.assertEqual(self.feed([S(0, True), S(5, False, exp=9), S(10, True, exp=9)]), [])

    def test_bag_delta(self):
        self.assertEqual(live.bag_delta({1: 2, 3: 1}, {1: 2, 4: 7}), {3: -1, 4: 7})
        self.assertEqual(live.bag_delta(None, {1: 1}), {})


class Merge(unittest.TestCase):
    def test_memory_row_fills_the_tap_battle_of_the_same_window(self):
        db = store.connect(':memory:')
        live.init(db)
        lu = bytearray(decode.LINEUP_HEAD)
        lu[0:4] = (7).to_bytes(4, 'little')
        (battle,) = decode.assemble([decode.Packet(1000, decode.RECV, decode.OP_LINEUP, bytes(lu))])
        store.save(db, [store.to_row(battle, 'tap_42.jsonl', 42, 500.0),          # start_time 501.0
                        store.to_row(battle, 'tap_43.jsonl', 43, 500.0)])         # another window
        mb = live.MemBattle(502.5, 510, 700, 1, 2, 22, 22, 0, 1582, 1582, 100, 60, {9801: -1}, 1, 5.0, 12.0)
        live.save(db, 'cap01', 42, 7, [mb])
        self.assertEqual(live.merge(db), 1)
        row = db.execute('select role, level, mem_exp_gain, gold_delta, bag_delta, quiz_count, quiz_s from battles'
                         ' where pid = 42').fetchone()
        self.assertEqual(row[:4], ('cap01', 22, 1582, -40))
        self.assertEqual((json.loads(row[4]), row[5], row[6]), ({'9801': -1}, 1, 5.0))
        self.assertEqual(db.execute('select mem_level from battles where pid = 43').fetchone(), (None,))
        self.assertEqual(live.merge(db), 0)                                       # already merged


class Report(unittest.TestCase):
    def test_report_sections_on_a_small_database(self):
        from battlelog import report
        db = store.connect(':memory:')
        cols = ('source', 'start_tick', 'end_tick', 'map_id', 'level', 'monster_levels', 'exp', 'x_exp', 'potential',
                'x_potential', 'pet_exp', 'fight_s', 'patrol_s', 'items', 'monsters')
        rows = []
        for i in range(40):
            for lv, exp, x in ((21, 1582, 1), (21, 3164, 2), (14, 541, 1), (31, 2, 1)):
                rows.append((f's{lv}{x}', i, i + 1, 700, lv, '21 21 22 22', exp, x, 150, 1, 790, 9.0, 6.0,
                             '[[65271, 1, 25]]', '[[1197, 21, 0, 767]]'))
        db.executemany(f'insert into battles ({",".join(cols)}) values ({",".join("?" * len(cols))})', rows)
        text = report.build(db, Path(__file__).resolve().parent.parent / 'factory' / 'data' / 'items.csv',
                            {700: '八阵图'})
        self.assertIn('| 21 | 八阵图 | 38.0 |', text)           # 1582 single exp per 15 s
        self.assertIn('| -8 | 1 | 40 | 34% |', text)            # 14 - 21.5, 541 / 1582
        self.assertIn('| 1 | 2.00 倍 | 1.00 倍 | 1.00 倍 |', text)
        self.assertIn('猛男鼹鼠21级', text)
        self.assertNotIn('| 31 |', text)                         # ~0 exp: not a "best map"


if __name__ == '__main__':
    unittest.main()
