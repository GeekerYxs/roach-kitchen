"""Unit tests for research/qiyi/ganlu.py (no game needed), on the dialogs 飞天把你射成蜂窝 saw live on 2026-10-28:
红猪大叔 -> 飞往缥缈之岛, 结界机关 -> 传送：冰封湖, 圣树 pages for each growth stage, 摘取 -> 已经采摘过了."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'qiyi'))

import ganlu  # noqa: E402
from provisioner.world import Dialog, WorldState, parse_options  # noqa: E402

PIG = ('#FFFFFF#我这一生去过很多地方，但飞越这么密集的群山还是头一遭，真是长见识了，即使是丛林的大树也没这么密集。\n'
       '#ABB5FC#[URL opt=1]返回龙之都[/URL]\n#ABB5FC#[URL opt=2]飞往缥缈之岛[/URL]\n#ABB5FC#[URL opt=3]离开[/URL]\n')
GATE = ('#FFFFFF#（#949494#精妙的机关已经开始运作。#ffffff#）\n#ABB5FC#[URL opt=1]传送：神迹之地[/URL]\n'
        '#ABB5FC#[URL opt=2]传送：冰封湖[/URL]\n#ABB5FC#[URL opt=3]离开[/URL]\n')
TREE_OK = ('#FFFFFF#（#949494#圣树已经长到一人高，树干粗壮，枝繁叶茂。#ffffff#）\n已经解锁以下功能：\n'
           '1、每日可孕育圣树甘露：#ffff00#4~6#ffffff#\n当前成长阶段:#2AC9FE#茁壮#ffffff#\n'
           '#d8a9fe#今日还可强效培育：#ffffff#3/3\n\n#ABB5FC#[URL opt=1]摘取圣树甘露[/URL]\n'
           '#ABB5FC#[URL opt=2]圣树进阶[/URL]\n#ABB5FC#[URL opt=3]离开[/URL]\n')
TREE_OTHER = ('#FFFFFF#（#949494#粗壮的枝干曼盖天际，站在树下似乎整个天空都被它遮住了#ffffff#）\n已经解锁以下功能：\n'
              '1、每日可孕育圣树甘露：#ffff00#12~24#ffffff#\n当前成长阶段:#FFBC05#参天#ffffff#\n'
              '#ABB5FC#[URL opt=1]离开[/URL]\n')
PICKED = '#FFFFFF#（#dd0000#圣树今天凝结的甘露已经采摘过了，请明日再来#ffffff#）\n\n'


def state(map_id, x, y, text=None, nav=False):
    dialog = Dialog(text, parse_options(text)) if text else None
    return WorldState(1, map_id, x, y, 0, 0, 0, False, False, nav, False, dialog=dialog)


def kind_args(a):
    return a.kind, a.args


class Decide(unittest.TestCase):
    def test_route_to_island(self):
        self.assertEqual(kind_args(ganlu.decide(state(20, 3863, 2027), False)), ('nav', (20, 663, 166)))
        self.assertEqual(kind_args(ganlu.decide(state(3110, 456, 3532), False)), ('click', (14601,)))
        self.assertEqual(kind_args(ganlu.decide(state(3110, 440, 3516, PIG), False)), ('pick', (2,)))

    def test_gate_then_tree(self):
        self.assertEqual(kind_args(ganlu.decide(state(1300, 4136, 6044), False)), ('nav', (1300, 812, 6560)))
        self.assertEqual(kind_args(ganlu.decide(state(1300, 812, 6560), False)), ('click', (17019,)))
        self.assertEqual(kind_args(ganlu.decide(state(1300, 812, 6560, GATE), False)), ('pick', (2,)))
        self.assertEqual(kind_args(ganlu.decide(state(1300, 3890, 1700), False)), ('nav', (1300, 1016, 2148)))
        self.assertEqual(kind_args(ganlu.decide(state(1300, 1016, 2148), False)), ('click', (17029,)))
        self.assertEqual(kind_args(ganlu.decide(state(1300, 1016, 2148, TREE_OK), False)), ('pick', (1,)))

    def test_skips_other_stages(self):
        self.assertEqual(kind_args(ganlu.decide(state(1300, 1016, 2148, TREE_OTHER), False)), ('pick', (0,)))
        self.assertEqual(kind_args(ganlu.decide(state(1300, 1016, 2148), False, {17029})), ('click', (17030,)))
        self.assertEqual(ganlu.decide(state(1300, 1016, 2148), False, set(ganlu.TREES)).kind, 'fail')

    def test_picked_closes_then_done(self):
        self.assertEqual(kind_args(ganlu.decide(state(1300, 1016, 2148, PICKED), False)), ('pick', (0,)))
        self.assertEqual(kind_args(ganlu.decide(state(1300, 1016, 2148, TREE_OK), True)), ('pick', (0,)))
        self.assertEqual(ganlu.decide(state(1300, 1016, 2148), True).kind, 'done')


class Step(unittest.TestCase):
    def test_wrong_stage_marked_bad(self):
        with mock.patch.object(ganlu, 'ganlu', return_value=6):
            step = ganlu.make_step()
            self.assertEqual(kind_args(step(state(1300, 1016, 2148), None)), ('click', (17029,)))
            self.assertEqual(kind_args(step(state(1300, 1016, 2148, TREE_OTHER), None)), ('pick', (0,)))
            self.assertEqual(kind_args(step(state(1300, 1016, 2148), None)), ('click', (17030,)))

    def test_done_on_count_up_or_picked_text(self):
        with mock.patch.object(ganlu, 'ganlu', side_effect=[6, 12, 12]):
            step = ganlu.make_step()
            self.assertEqual(kind_args(step(state(1300, 1016, 2148, TREE_OK), None)), ('pick', (1,)))
            self.assertEqual(kind_args(step(state(1300, 1016, 2148, TREE_OK), None)), ('pick', (0,)))
            a = step(state(1300, 1016, 2148), None)
            self.assertEqual(a.kind, 'done')
            self.assertIn('6 -> 12', a.why)
        with mock.patch.object(ganlu, 'ganlu', return_value=12):
            step = ganlu.make_step()
            self.assertEqual(kind_args(step(state(1300, 1016, 2148, PICKED), None)), ('pick', (0,)))
            self.assertEqual(step(state(1300, 1016, 2148), None).kind, 'done')


if __name__ == '__main__':
    unittest.main()
