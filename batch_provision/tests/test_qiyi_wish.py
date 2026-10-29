"""Unit tests for research/qiyi/wish.py (no game needed), on the 祈愿神像 dialogs 飞天把你射成蜂窝 saw live on
2026-10-28: menu -> rules -> 许愿秩序之源碎片 -> 开始许愿 x8 (counter 8/8 .. 0/8) -> 已经够多了."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'qiyi'))

import wish  # noqa: E402
from provisioner.world import Dialog, WorldState, parse_options  # noqa: E402

MENU = ('#FFFFFF#年轻的神，我将为你服务，只需要贡献一些神识，我就能满足你的愿望。\n\n#ABB5FC#[URL opt=1]许愿[/URL]\n'
        '#ABB5FC#[URL opt=2]离开[/URL]\n')
RULES = ('#FFFFFF#许愿规则如下：\n\n1、每次许愿都将消耗神识，不同的愿望消耗的数量不同；\n'
         '#ABB5FC#[URL opt=1]许愿秩序之源碎片[/URL]\n#ABB5FC#[URL opt=2]许愿星灵原力[/URL]\n')
ENOUGH = '#FFFFFF#（今天你许的愿望已经够多了，请明日再来）\n\n#ABB5FC#[URL opt=1]好的[/URL]\n'


def page(n):
    return (f'#FFFFFF#许愿可以获得一定数量的秩序之源碎片，需要消耗3000点神识。\n你的声望:小有名望 可祈福{n}/8次\n\n'
            '#ABB5FC#[URL opt=1]开始许愿[/URL]\n')


def state(map_id, x, y, text=None, nav=False):
    dialog = Dialog(text, parse_options(text)) if text else None
    return WorldState(1, map_id, x, y, 0, 0, 0, False, False, nav, False, dialog=dialog)


def kind_args(a):
    return a.kind, a.args


class Decide(unittest.TestCase):
    def test_route_and_menus(self):
        self.assertEqual(kind_args(wish.decide(state(3110, 664, 4172), False)), ('nav', (3110, 1112, 620)))
        self.assertEqual(kind_args(wish.decide(state(3120, 1736, 1956), False)), ('nav', (3120, 1310, 2421)))
        self.assertEqual(kind_args(wish.decide(state(3120, 1310, 2421), False)), ('click', (14630,)))
        self.assertEqual(kind_args(wish.decide(state(3120, 1310, 2421, MENU), False)), ('pick', (1,)))
        self.assertEqual(kind_args(wish.decide(state(3120, 1310, 2421, RULES), False)), ('pick', (1,)))

    def test_wishes_until_counter_zero(self):
        for n in range(8, 0, -1):
            self.assertEqual(kind_args(wish.decide(state(3120, 1310, 2421, page(n)), False)), ('pick', (1,)), n)
        self.assertEqual(kind_args(wish.decide(state(3120, 1310, 2421, page(0)), False)), ('pick', (0,)))

    def test_enough_closes_then_done(self):
        self.assertEqual(kind_args(wish.decide(state(3120, 1310, 2421, ENOUGH), False)), ('pick', (0,)))
        self.assertEqual(wish.decide(state(3120, 1310, 2421), True).kind, 'done')
        self.assertEqual(wish.decide(state(3120, 1310, 2421), False).kind, 'click')


class Step(unittest.TestCase):
    def test_step_marks_finished_from_counter_or_text(self):
        for text in (page(0), ENOUGH):
            with mock.patch.object(wish, 'shards', side_effect=[121, 161]):
                step = wish.make_step()
                self.assertEqual(kind_args(step(state(3120, 1310, 2421, text), None)), ('pick', (0,)))
                a = step(state(3120, 1310, 2421), None)
                self.assertEqual(a.kind, 'done')
                self.assertIn('121 -> 161', a.why)

    def test_left(self):
        self.assertEqual(wish.left(state(3120, 1, 1, page(7))), 7)
        self.assertIsNone(wish.left(state(3120, 1, 1, MENU)))


if __name__ == '__main__':
    unittest.main()
