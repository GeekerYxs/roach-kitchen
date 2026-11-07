"""Restart in the middle of an item hand-in (no game).

2026-11-07 r4ys25 (元素使, 奥德赛25-28): 10 级转术士, 奥德赛25 handed its 3 books to 留一手 (books 0, task 25 at
(0,0,2,0,1)), 奥德赛27 dropped, the step reran: shuidi.py waited for 奥德赛25's books for ever. And after the relog the
step bytes of the same quests read (0,2,1) / (0,46,1) / (0,221,1) / (125,0,2,3,1): exact tuple tests failed too.
Every case here is "one apprentice already handed in, the others not yet".
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'shitu'))

import progress  # noqa: E402
from provisioner import world  # noqa: E402
from provisioner.world import Quest  # noqa: E402

BOOK = 10549

# the live reads of the r4ys25 log (13:21-13:39), by apprentice
HANDED = Quest(True, False, (0, 2, 2, 0, 1))         # 奥德赛25 after its hand-in, relogged
HANDED_ODD = Quest(True, False, (125, 0, 2, 3, 1))   # 奥德赛25 one relog earlier
AT_BOOKS = Quest(True, False, (0, 46, 1))            # 奥德赛27 still holding its books, relogged
AT_BOOKS_2 = Quest(True, False, (0, 2, 1))
DONE = Quest(False, True, ())


class World:
    """Fake world for a few apprentices: quests {name: {qid: Quest}}, bags {name: {item: n}}."""
    def __init__(self, quests, bags=None):
        self.quests, self.bags = quests, bags or {}

    def patches(self):
        return [mock.patch.object(world, 'read_quest', lambda mem, qid: self.quests[mem].get(qid, Quest(False, False))),
                mock.patch.object(world, 'read_bag', lambda mem: mem),
                mock.patch.object(world, 'item_count', lambda bag, item: self.bags.get(bag, {}).get(item, 0)),
                mock.patch.object(world, 'read_bag_capacity', lambda mem: 40)]

    def __enter__(self):
        self._p = self.patches()
        for p in self._p:
            p.start()
        return self

    def __exit__(self, *a):
        for p in self._p:
            p.stop()


def client(name):
    return NS(name=name, mem=name)


class StepCount(unittest.TestCase):
    def test_relog_garbage_still_reads_as_the_right_step(self):
        for q in (AT_BOOKS, AT_BOOKS_2, Quest(True, False, (0, 221, 1)), Quest(True, False, (0, 0, 1))):
            self.assertTrue(progress.at(q, progress.CLASS_ITEMS), q)
            self.assertFalse(progress.past(q, progress.CLASS_ITEMS + 1), q)
        for q in (HANDED, HANDED_ODD, Quest(True, False, (0, 0, 2, 0, 1))):
            self.assertTrue(progress.at(q, progress.CLASS_FAIRY), q)
            self.assertTrue(progress.past(q, progress.CLASS_ITEMS + 1), q)
        self.assertTrue(progress.past(DONE, 99))
        self.assertFalse(progress.at(DONE, 3))
        self.assertFalse(progress.past(None, 1))            # session unreadable: not past
        self.assertFalse(progress.past(Quest(False, False, ()), 1))
        self.assertEqual(progress.parse('187:8'), (187, 8))


class Books(unittest.TestCase):
    """shuidi.Books, the stage's done_when."""
    def setUp(self):
        import shuidi
        self.shuidi = shuidi
        self.say = mock.patch.object(shuidi.t, 'say', lambda m: None)
        self.say.start()

    def tearDown(self):
        self.say.stop()

    def test_one_handed_in_three_with_books_is_done(self):
        q = {'a25': {25: HANDED}, 'a26': {25: AT_BOOKS_2}, 'a27': {25: AT_BOOKS}, 'a28': {25: AT_BOOKS_2}}
        bags = {'a26': {BOOK: 3}, 'a27': {BOOK: 3}, 'a28': {BOOK: 3}}           # a25: 0 books, handed in
        with World(q, bags):
            self.assertTrue(self.shuidi.Books([client(n) for n in q])())

    def test_one_still_short_keeps_farming(self):
        q = {'a25': {25: HANDED}, 'a26': {25: AT_BOOKS_2}}
        with World(q, {'a26': {BOOK: 2}}):
            self.assertFalse(self.shuidi.Books([client(n) for n in q])())

    def test_fresh_start_needs_books_from_everyone(self):
        q = {'a25': {25: Quest(True, False, (0, 0, 1))}, 'a26': {25: Quest(True, False, (0, 0, 1))}}
        with World(q, {'a25': {BOOK: 3}}):
            self.assertFalse(self.shuidi.Books([client(n) for n in q])())


class HandIn(unittest.TestCase):
    """zhuanzhi_take.handin: only who has not handed in talks; garbage step bytes do not matter."""
    def setUp(self):
        import zhuanzhi_take as z
        self.z = z
        self.talks = []
        self.p = [mock.patch.object(z.t, 'say', lambda m: None),
                  mock.patch.object(z, 'go', lambda c: None),
                  mock.patch.object(z, 'mark', lambda *a, **k: None),
                  mock.patch.object(z.time, 'sleep', lambda s: None),
                  mock.patch.object(z, 'talk', self.talk)]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()

    def talk(self, c, npc, words):
        self.talks.append(c.name)
        self.world.quests[c.name][self.z.QUEST] = HANDED           # the NPC takes them

    def run_all(self, quests, bags=None, books=None):
        qid = self.z.QUEST
        self.world = World({n: {qid: q} for n, q in quests.items()}, bags)
        with self.world, mock.patch.object(self.z, 'BOOKS', books):
            for n in quests:
                self.z.handin(client(n))

    def test_handed_one_is_skipped_the_others_hand_in(self):
        self.run_all({'a25': HANDED, 'a26': AT_BOOKS_2, 'a27': AT_BOOKS, 'a28': HANDED_ODD})
        self.assertEqual(self.talks, ['a26', 'a27'])

    def test_mage_without_books_stops_the_step_for_a_rerun(self):
        with self.assertRaisesRegex(self.z.t.Stop, '不到 3 本'):
            self.run_all({'a26': AT_BOOKS}, {'a26': {BOOK: 1}}, books=(BOOK, 3))
        self.assertEqual(self.talks, [])

    def test_mage_with_books_hands_in(self):
        self.run_all({'a25': HANDED, 'a26': AT_BOOKS}, {'a26': {BOOK: 3}}, books=(BOOK, 3))
        self.assertEqual(self.talks, ['a26'])


class Finish(unittest.TestCase):
    """zhuanzhi_finish.finish: the 神仙姐姐 precondition by the step count."""
    def test_relogged_fairy_step_goes_on_and_items_step_stops(self):
        import zhuanzhi_finish as f

        class Went(Exception):
            pass

        def gate(*a):
            raise Went()
        c = NS(name='a27', mem='a27', world=lambda: NS(map_id=1, x=0, y=0))
        with mock.patch.object(f, 'gate', gate):
            for q in (HANDED, HANDED_ODD):
                with World({'a27': {f.QUEST: q}}), self.assertRaises(Went):
                    f.finish(c)
            with World({'a27': {f.QUEST: AT_BOOKS}}), self.assertRaisesRegex(f.t.Stop, '神仙姐姐'):
                f.finish(c)


class Kills5Condition(unittest.TestCase):
    def test_relogged_apprentice_at_the_boxers_still_needs_them(self):
        from line import ops
        quests = {'a': {24: AT_BOOKS}, 'b': {24: HANDED}}
        with World(quests), mock.patch.object(ops, 'APPRENTICES', ('a', 'b')), \
                mock.patch.object(ops.t, 'Client', client), mock.patch('bai_shi.done', lambda n, k: False):
            self.assertTrue(ops.cond('kills5'))
        quests['a'][24] = HANDED
        with World(quests), mock.patch.object(ops, 'APPRENTICES', ('a', 'b')), \
                mock.patch.object(ops.t, 'Client', client), mock.patch('bai_shi.done', lambda n, k: False):
            self.assertFalse(ops.cond('kills5'))


class FakeTap:
    def __init__(self, *a, **k):
        pass

    def ready(self):
        pass

    def poll(self):
        return []


class KillCounters(unittest.TestCase):
    """quanshou.Kills (24 / quan100's 181) and yaodao.Kills (187): a handed-in apprentice counts as full."""
    def test_quanshou_and_quan100(self):
        import quanshou
        import quan100
        apps = [NS(name='a', mem='a', pid=1), NS(name='b', mem='b', pid=2)]
        with World({'a': {24: HANDED, 181: Quest(True, False, (2, 2, 1))}, 'b': {24: AT_BOOKS, 181: Quest(True, False, (1,))}}), \
                mock.patch.object(quanshou, 'Tap', FakeTap), mock.patch.object(quanshou, 'done', lambda n, k: False), \
                mock.patch.object(quanshou.t, 'say', lambda m: None):
            k = quanshou.Kills(apps)
            self.assertEqual(k.count, {'a': 5, 'b': 0})
            self.assertFalse(k())
            k = quan100.Kills(apps)
            self.assertEqual(k.count, {'a': 40, 'b': 0})
            self.assertFalse(k())

    def test_yaodao(self):
        import yaodao
        apps = [NS(name='a', mem='a', pid=1), NS(name='b', mem='b', pid=2), NS(name='c', mem='c', pid=3)]
        quests = {'a': {187: Quest(True, False, (2, 2, 2, 2, 2, 1))},       # handed in at 虫洞法师
                  'b': {187: Quest(True, False, (2, 2, 2, 2, 1))},          # kills marked before a relog
                  'c': {187: Quest(True, False, (2, 2, 2, 2, 1))}}
        with World(quests), mock.patch.object(yaodao, 'Tap', FakeTap), \
                mock.patch.object(yaodao, 'done', lambda n, k: n == 'b' and k == 'yaodao5'), \
                mock.patch.object(yaodao, 'mark', lambda *a, **k: None), mock.patch.object(yaodao.t, 'say', lambda m: None):
            k = yaodao.Kills(apps)
            self.assertEqual(k.count, {'a': 5, 'b': 5, 'c': 0})
            self.assertFalse(k())
            quests['c'][187] = DONE
            self.assertTrue(yaodao.Kills(apps)())

    def test_yaodao_counts_only_the_kill_report(self):
        """2026-11-07 r4ys29: the order's text named「5只色妖道」and was taken for 5 kills."""
        import yaodao
        self.assertIsNone(yaodao.kill_count('我早告诉过你真正的毕业考试没那么容易混，5只色妖道并不是用豆腐做成的！'))
        self.assertIsNone(yaodao.kill_count('接受了任务：术士的试炼 去通天塔杀死5只色妖道'))
        self.assertEqual(yaodao.kill_count('你已经杀死了3个色妖道，需要5个'), 3)
        self.assertEqual(yaodao.kill_count('你已经杀死了5个色妖道，可以回去找虫洞法师了'), 5)

    def test_yaodao_reads_the_kills_already_in_the_tap_file(self):
        import yaodao

        class OldTap(FakeTap):
            def __init__(self, pid, from_end):
                self.from_end = from_end

            def poll(self):
                return [] if self.from_end else [(0, 'S->C', 0x46ff, b'', None)]
        marks = []
        with World({'c': {187: Quest(True, False, (2, 2, 2, 2, 1))}}), mock.patch.object(yaodao, 'Tap', OldTap), \
                mock.patch.object(yaodao, 'texts', lambda body: ['#FF0000#你已经杀死了5个色妖道，需要5个']), \
                mock.patch.object(yaodao, 'done', lambda n, k: False), \
                mock.patch.object(yaodao, 'mark', lambda n, k: marks.append((n, k))), \
                mock.patch.object(yaodao.t, 'say', lambda m: None):
            self.assertTrue(yaodao.Kills([NS(name='c', mem='c', pid=3)])())
        self.assertEqual(marks, [('c', 'yaodao5')])


class Farms(unittest.TestCase):
    """farm.Count (--past) and stones.Stones: one handed in, the others still farming / done."""
    def test_farm_count_with_past(self):
        import farm
        apps = [client('a'), client('b')]
        quests = {'a': {187: Quest(True, False, (2,) * 7 + (1,))}, 'b': {187: Quest(True, False, (2,) * 6 + (1,))}}
        with World(quests, {'b': {10716: 10}}), mock.patch.object(farm, 'load_items', dict), \
                mock.patch.object(farm.t, 'say', lambda m: None):
            self.assertTrue(farm.Count(apps, 10716, 10, '画像', past=(187, 8))())
            self.assertFalse(farm.Count(apps, 10716, 10, '画像')())        # without --past: a's 画像 are gone
        with World(quests, {'b': {10716: 9}}), mock.patch.object(farm, 'load_items', dict), \
                mock.patch.object(farm.t, 'say', lambda m: None):
            self.assertFalse(farm.Count(apps, 10716, 10, '画像', past=(187, 8))())

    def test_stones(self):
        import stones
        apps = [client('a'), client('b')]
        quests = {'a': {187: Quest(True, False, (2, 2, 1))}, 'b': {187: Quest(True, False, (2, 1))}}
        with mock.patch.object(stones.t, 'say', lambda m: None):
            with World(quests, {'b': {stones.PERFECT: 10}}):
                self.assertTrue(stones.Stones(apps)())
            with World(quests, {'b': {stones.PERFECT: 9, stones.FLAWED: 5}}):
                self.assertFalse(stones.Stones(apps)())


class Gates(unittest.TestCase):
    """U have ITEM N ALT...: a rerun after one apprentice traded / handed the item on."""
    def test_have_alternatives(self):
        import r4_util
        quests = {'a': {189: Quest(True, False, (2,) * 8 + (1,))}, 'b': {189: Quest(True, False, (2,) * 7 + (1,))}}
        with mock.patch.object(r4_util, 'APPRENTICES', ('a', 'b')), mock.patch.object(r4_util.t, 'Client', client), \
                mock.patch.object(r4_util.t, 'say', lambda m: None):
            with World(quests, {'b': {10732: 1}}):
                r4_util.have(10732, 1, '189:9')                       # a handed in, b holds it
                with self.assertRaises(r4_util.t.Stop):
                    r4_util.have(10732, 1)
            with World(quests, {'a': {10719: 1}, 'b': {10730: 1}}):
                r4_util.have(10730, 1, '10719')                        # a already got the 风之气息 for it
            with World(quests, {'a': {}, 'b': {10730: 1}}), self.assertRaises(r4_util.t.Stop):
                r4_util.have(10730, 1, '10719')

    def test_route_uses_them(self):
        from line import route as R
        steps = {s.name: s for s in R.YUANSU_LATE}
        cmds = lambda name: [c.args for c in steps[name].cmds]      # noqa: E731
        self.assertIn(('U', 'have', '10732', '1', '189:9'), cmds('y_fifth'))
        self.assertIn(('U', 'have', '10730', '1', '10719'), cmds('y_wind2'))
        farm = next(a for a in cmds('y_huaxiang') if a[0] == 'farm.py')
        self.assertEqual(farm[1:3], ('--past', '187:8'))
        self.assertEqual(cmds('y_huaxiang')[-1], ('U', 'need', '187', '8'))     # the same N as the gate


class OneByOne(unittest.TestCase):
    def test_fifth_skips_who_handed_in(self):
        import fifth
        with World({'a': {189: Quest(True, False, (2,) * 8 + (1,))}}), mock.patch.object(fifth.t, 'Client', client), \
                mock.patch.object(fifth, 'take_lead', lambda c: self.fail('took the lead')), \
                mock.patch.object(fifth.t, 'say', lambda m: None):
            fifth.one('a')

    def test_bird_leaves_out_who_finished_187(self):
        import bird
        fought = []
        with World({'a': {187: DONE}, 'b': {187: DONE}}), mock.patch.object(bird.t, 'Client', client), \
                mock.patch.object(bird, 'run', lambda *a: self.fail(f'ran {a}')), \
                mock.patch.object(bird.boss_fight, 'fight', lambda *a: fought.append(a)), \
                mock.patch.object(bird.t, 'say', lambda m: None):
            bird.main('master', ['a', 'b'])
        self.assertEqual(fought, [])


if __name__ == '__main__':
    unittest.main()
