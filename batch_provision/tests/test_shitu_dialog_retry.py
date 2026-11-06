"""Test machine 2026-11-06 (fdm2 魔徒B05 / fdm5 魔徒E05): three stalls of a batch's last steps.
  - take224.talk: the next page not there 0.4 s after a pick -> d None -> AttributeError; now it waits for it.
  - ops.fairy 183: a retry after 完成转职礼 opened on「接受奖励」and the fixed word list wanted「继续」; now pages are
    matched by any word, like 189.
  - chushi: a rerun started again at an apprentice already 出师; now state.json skips it."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'shitu'))

import take224  # noqa: E402


def page(text, *labels):
    return NS(text=text, options=[(0, '离开')] + [(i + 1, l) for i, l in enumerate(labels)])


class Dialogs:
    """c.dialog() is None for `gap` reads after each pick, then the next page."""
    def __init__(self, pages, gap=0, on_pick=None):
        self.pages, self.gap, self.left, self.picks, self.on_pick = list(pages), gap, 0, [], on_pick
        self.name, self.mem = 'x', None
        self.game = NS(click_npc=lambda npc: None, select_dialog=self.select)

    def select(self, opt):
        self.picks.append(opt)
        self.pages.pop(0)
        self.left = self.gap
        if self.on_pick:
            self.on_pick(self)

    def dialog(self):
        if self.left:
            self.left -= 1
            return None
        return self.pages[0] if self.pages else None


class Talk(unittest.TestCase):
    def test_waits_for_a_late_page(self):
        c = Dialogs([page('a', '师徒任务'), page('b', '出师任务'), page('c', '我已经完成考验了'), page('d', '球棒')], gap=2)
        with mock.patch.object(take224.time, 'sleep', lambda s: None):
            d = take224.talk(c, 341, ['师徒任务', '出师任务', '我已经完成考验了'])
        self.assertEqual(c.picks, [1, 1, 1])
        self.assertEqual(d.text, 'd')

    def test_last_pick_may_close(self):
        c = Dialogs([page('a', '接受奖励')], gap=0)
        with mock.patch.object(take224.time, 'sleep', lambda s: None):
            self.assertIsNone(take224.talk(c, 1, ['接受奖励']))


class Fairy(unittest.TestCase):
    def run_fairy(self, pages):
        from line import ops
        quest = NS(active=True, done=False)

        def picked(c):
            if not c.pages:
                quest.active, quest.done = False, True
        c = Dialogs(pages, on_pick=picked)
        c.world = lambda: NS(map_id=270)
        fake_zz = NS(gate=lambda *a: None, walk=lambda *a: None)
        with mock.patch.dict(sys.modules, {'zhuanzhi_finish': fake_zz}), \
                mock.patch.object(ops, 'APPRENTICES', ['x']), \
                mock.patch.object(ops.t, 'Client', lambda n: c), \
                mock.patch.object(ops.t, 'each', lambda names, fn: [fn(n) for n in names]), \
                mock.patch.object(ops.t, 'say', lambda m: None), \
                mock.patch.object(ops.w, 'read_quest', lambda mem, q: quest), \
                mock.patch.object(ops.time, 'sleep', lambda s: None), \
                mock.patch.dict(ops.os.environ, {'SHITU_QID': '183'}):
            ops.fairy()
        return c, quest

    def test_183_from_the_start(self):
        c, q = self.run_fairy([page('1', '勇者的考验'), page('2', '继续'), page('3', '继续'), page('4', '完成转职礼'),
                               page('5', '接受奖励')])
        self.assertTrue(q.done)
        self.assertEqual(len(c.picks), 5)

    def test_183_retry_opens_on_reward(self):
        c, q = self.run_fairy([page('哦，差点忘记，还有点东西要给你~', '接受奖励')])
        self.assertTrue(q.done)
        self.assertEqual(c.picks, [1])


class Chushi(unittest.TestCase):
    def test_skips_one_already_out(self):
        import chushi
        with mock.patch.object(chushi, 'done', lambda n, s: s == 'chushi'), \
                mock.patch.object(chushi.t, 'say', lambda m: None), \
                mock.patch.object(chushi.t, 'Client', side_effect=AssertionError('touched the game')):
            chushi.one('师傅', '魔徒E05')


if __name__ == '__main__':
    unittest.main()
