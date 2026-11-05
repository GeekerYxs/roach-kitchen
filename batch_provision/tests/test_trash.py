"""trash.py (user 2026-11-05): the apprentices drop 碧玉 / 黄玉 / 紫金红葫芦, 特赦令 and 整人道具 out of battle (every 20
min in the loops, after each opened pack, at every home), and the 勇者 line sells its weapons at home; the master's
胡萝卜汁 is not bought any more."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

HERE = Path(__file__).resolve().parent.parent / 'research' / 'shitu'
sys.path.insert(0, str(HERE))

import trash  # noqa: E402

ITEMS = {
    31801: NS(name='紫金红葫芦', type=0x400, tradable=True), 31802: NS(name='黄玉葫芦', type=0x400, tradable=True),
    31803: NS(name='碧玉葫芦', type=0x400, tradable=True), 32068: NS(name='特赦令', type=0x400, tradable=True),
    50: NS(name='定身丸', type=0x802, tradable=True), 9801: NS(name='回城卷', type=0x400, tradable=True),
    118: NS(name='专打屁屁扳手', type=0x103, tradable=True), 7: NS(name='破布', type=0x1000, tradable=True),
}


class Role:
    def __init__(self, name, bag, battle=False, map_id=1, worn=()):
        self.name, self.mem, self.battle, self.map_id = name, self, battle, map_id
        self.bag = [NS(slot=i, item_id=x, quantity=1) for i, x in enumerate(bag)]
        self.worn, self.sent = list(worn), []
        self.game = NS(send=lambda op, body: self.sent.append((op, body)))

    def world(self):
        return NS(in_battle=self.battle, map_id=self.map_id)


def patched():
    return mock.patch.dict(trash.os.environ, {'SHITU_TRASH': '1'}), mock.patch.multiple(trash, _items=ITEMS), mock.patch.object(trash.w, 'read_bag', lambda m: m.bag), \
        mock.patch.object(trash.t, 'say', lambda s: None), mock.patch.object(trash.time, 'sleep', lambda s: None), \
        mock.patch.object(trash.w, 'read_equipment', lambda m: m.worn)


class Drop(unittest.TestCase):
    def run_drop(self, c):
        ps = patched()
        for p in ps:
            p.start()
        try:
            return trash.drop(c)
        finally:
            for p in ps:
                p.stop()

    def test_drops_only_trash(self):
        c = Role('a', [31801, 31802, 31803, 32068, 50, 9801, 118, 7])
        self.assertEqual(sorted(self.run_drop(c)), sorted(['紫金红葫芦', '黄玉葫芦', '碧玉葫芦', '特赦令', '定身丸']))
        self.assertEqual(len(c.sent), 5)
        self.assertTrue(all(op == 0x48 for op, _ in c.sent))

    def test_not_in_battle(self):
        c = Role('a', [31801], battle=True)
        self.assertEqual(self.run_drop(c), [])
        self.assertEqual(c.sent, [])


class TrasherEvery(unittest.TestCase):
    def test_every_20_minutes_out_of_battle(self):
        a, b = Role('a', []), Role('b', [])
        calls = []
        with mock.patch.object(trash, 'drop', lambda c, check=True: calls.append(c.name)), \
                mock.patch.dict(trash.os.environ, {'SHITU_TRASH': '1'}):
            tr = trash.Trasher([a, b])
            sts = {'a': NS(in_battle=False), 'b': NS(in_battle=True)}
            tr.tick(sts, 0)
            tr.tick(sts, 600)
            sts['b'] = NS(in_battle=False)
            tr.tick(sts, 601)
            tr.tick(sts, 1199)
            tr.tick(sts, 1201)
        self.assertEqual(calls, ['a', 'b', 'a'])
        self.assertEqual(trash.TRASH_EVERY, 1200)


class AtHome(unittest.TestCase):
    def run_home(self, cs, job='战士', trash_on='1'):
        did = []
        with mock.patch.object(trash, 'drop', lambda c, table=None, check=True: did.append(('drop', c.name))), \
                mock.patch.object(trash, 'sell_weapons', lambda c: did.append(('sell', c.name))), \
                mock.patch.dict(trash.os.environ, {'SHITU_JOB': job, 'SHITU_TRASH': trash_on}):
            trash.at_home(cs, masters=('师傅',))
        return sorted(did)

    def test_apprentices_in_the_village(self):
        cs = [Role('师傅', []), Role('a', []), Role('b', [], map_id=280)]
        self.assertEqual(self.run_home(cs), [('drop', 'a'), ('sell', 'a')])

    def test_other_projects_untouched(self):
        """projects/fullcrit_mage_leveling_70 uses r4_util.home / maze_train without SHITU_TRASH."""
        self.assertEqual(self.run_home([Role('a', [])], trash_on='0'), [])
        import line.plan as plan
        self.assertEqual(plan.Batch('a', 1).env()['SHITU_TRASH'], '1')

    def test_yuansu_keeps_its_weapons_rule(self):
        self.assertEqual(self.run_home([Role('a', [])], job='术士'), [('drop', 'a')])


class Wiring(unittest.TestCase):
    def src(self, f):
        return (HERE / f).read_text(encoding='utf-8')

    def test_hooks(self):
        self.assertIn('trash.at_home(cs[1:], masters=MASTERS)', self.src('r4_util.py'))
        self.assertIn('trash.drop(c, items, check=False)', self.src('open_packs.py'))
        for f in ('well10.py', 'lunhui15.py', 'maze_train.py'):
            self.assertIn('trasher.tick(sts, now)', self.src(f), f)

    def test_no_carrot_juice(self):
        r4 = self.src('r4_util.py')
        self.assertNotIn('juice_needed(', r4)
        self.assertNotIn("'胡萝卜汁')", r4)


if __name__ == '__main__':
    unittest.main()
