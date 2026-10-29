"""Unit tests for research/qiyi/chest.py (no game needed), on the dialogs 飞天把你射成蜂窝 saw live on 2026-10-28:
结界机关 17026 -> 伊甸岛, 结界机关 17019 -> 神迹之地, 秘境之门, 树洞, and the 藏宝箱 酸液 pages."""
import sys
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'qiyi'))

import chest  # noqa: E402
from provisioner.world import Dialog, WorldState, parse_options  # noqa: E402

NORTH_GATE = ('#FFFFFF#（#949494#精妙的机关已经开始运作。#ffffff#）\n#ABB5FC#[URL opt=1]传送：伊甸岛[/URL]\n'
              '#ABB5FC#[URL opt=2]离开[/URL]\n')
SOUTH_GATE = ('#FFFFFF#（#949494#精妙的机关已经开始运作。#ffffff#）\n#ABB5FC#[URL opt=1]传送：神迹之地[/URL]\n'
              '#ABB5FC#[URL opt=2]传送：冰封湖[/URL]\n#ABB5FC#[URL opt=3]离开[/URL]\n')
DOOR = '#FFFFFF#（#949494#秘境大门。#ffffff#）\n#ABB5FC#[URL opt=1]穿越大门[/URL]\n#ABB5FC#[URL opt=2]离开[/URL]\n'
HOLE = ('#FFFFFF#（#949494#这个洞深不可测，你敢跳吗？#ffffff#）\n#ABB5FC#[URL opt=1]跳进去[/URL]\n'
        '#ABB5FC#[URL opt=2]离开[/URL]\n')
LOCKED = ('#FFFFFF#（#949494#它被魔法结界保护着，靠蛮力是绝对打不开的。#ffffff#）\n'
          '#ABB5FC#[URL opt=1]使用瓦鲁虫族秘匙打开箱子[/URL]\n#ABB5FC#[URL opt=2]使用酸液破坏结界[/URL]\n'
          '#ABB5FC#[URL opt=3]离开[/URL]\n')
ACID = ('#FFFFFF#（#949494#使用#ffff00#宝箱怪的酸液#949494#，有可能破坏结界，但是你没有完全的把握。#ffffff#）\n\n'
        '#ABB5FC#[URL opt=1]使用酸液破坏结界[/URL]\n')
FAILED = ('#FFFFFF#（#949494#你将酸液泼洒在箱子上，保护它的魔法结界散发的光芒略微黯淡了下去，但片刻之后，又恢复了原状。'
          '#ffffff#）\n\n#ABB5FC#[URL opt=1]再试一次[/URL]\n#ABB5FC#[URL opt=2]算了，走人吧[/URL]\n')
WORKED = ('#FFFFFF#（#949494#你将酸液泼洒在箱子上，保护它的魔法结界散发的光芒略微黯淡了下去，最后逐渐消失不见。'
          '#ffffff#）\n\n#ABB5FC#[URL opt=1]（酸液起作用了！）[/URL]\n')
OPEN = ('#FFFFFF#（#949494#它的魔法结界已被破坏，现在可以随便打开了。#ffffff#）\n'
        '#ABB5FC#[URL opt=1]打开箱子[/URL]\n')
EMPTY = '#FFFFFF#（这是个空箱子）\n#ABB5FC#[URL opt=1]离开[/URL]\n'


def state(map_id, x, y, text=None, nav=False):
    dialog = Dialog(text, parse_options(text)) if text else None
    return WorldState(1, map_id, x, y, 0, 0, 0, False, False, nav, False, dialog=dialog)


def kind_args(a):
    return a.kind, a.args


class Decide(unittest.TestCase):
    def test_island_three_parts(self):
        self.assertEqual(kind_args(chest.decide(state(1300, 1016, 2148))), ('nav', (1300, 3827, 1776)))
        self.assertEqual(kind_args(chest.decide(state(1300, 3827, 1776))), ('click', (17026,)))
        self.assertEqual(kind_args(chest.decide(state(1300, 3827, 1776, NORTH_GATE))), ('pick', (1,)))
        self.assertEqual(kind_args(chest.decide(state(1300, 760, 6700))), ('click', (17019,)))
        self.assertEqual(kind_args(chest.decide(state(1300, 760, 6700, SOUTH_GATE))), ('pick', (1,)))
        self.assertEqual(kind_args(chest.decide(state(1300, 4136, 6044))), ('nav', (1300, 760, 6700)))  # boat
        self.assertEqual(kind_args(chest.decide(state(1300, 1830, 3330))), ('nav', (1300, 1528, 3060)))
        self.assertEqual(kind_args(chest.decide(state(1300, 1528, 3060))), ('click', (17095,)))
        self.assertEqual(kind_args(chest.decide(state(1300, 1528, 3060, DOOR))), ('pick', (1,)))

    def test_hole_into_cave(self):
        self.assertEqual(kind_args(chest.decide(state(3110, 3624, 5796))), ('nav', (3110, 3752, 5804)))
        self.assertEqual(kind_args(chest.decide(state(3110, 3752, 5804))), ('click', (14752,)))
        self.assertEqual(kind_args(chest.decide(state(3110, 3752, 5804, HOLE))), ('pick', (1,)))
        self.assertEqual(kind_args(chest.decide(state(3210, 8760, 4595))), ('nav', (3210, 6744, 3908)))

    def test_from_elsewhere_goes_to_island(self):
        self.assertEqual(kind_args(chest.decide(state(20, 3863, 2027))), ('nav', (20, 663, 166)))
        self.assertEqual(kind_args(chest.decide(state(3110, 456, 3532))), ('click', (14601,)))   # 红猪大叔

    def test_chest_pages(self):
        here = (3210, 6744, 3908)
        self.assertEqual(kind_args(chest.decide(state(*here), acid=25)), ('click', (14719,)))
        self.assertEqual(kind_args(chest.decide(state(*here, LOCKED))), ('pick', (2,)))          # 酸液, not 秘匙
        for page in (ACID, FAILED, WORKED, OPEN):
            self.assertEqual(kind_args(chest.decide(state(*here, page))), ('pick', (1,)), page)
        self.assertEqual(kind_args(chest.decide(state(*here, EMPTY))), ('pick', (0,)))
        self.assertEqual(kind_args(chest.decide(state(*here), {14719})), ('click', (14720,)))
        self.assertEqual(chest.decide(state(*here, '#FFFFFF#什么\n')).kind, 'fail')

    def test_no_acid_fails(self):
        self.assertEqual(chest.decide(state(3210, 6744, 3908), acid=0).kind, 'fail')

    def test_all_empty_walk_to_end_then_done(self):
        self.assertEqual(kind_args(chest.decide(state(3210, 6744, 3908), set(chest.CHESTS))),
                         ('nav', (3210, 6344, 4708)))
        self.assertEqual(chest.decide(state(3210, 6344, 4708), set(chest.CHESTS)).kind, 'done')

    def test_step_marks_clicked_chest_empty(self):
        step = chest.make_step()
        mem = None
        with unittest.mock.patch.object(chest.world, 'read_bag', return_value=None):
            self.assertEqual(kind_args(step(state(3210, 6744, 3908), mem)), ('click', (14719,)))
            self.assertEqual(kind_args(step(state(3210, 6744, 3908, EMPTY), mem)), ('pick', (0,)))
            self.assertEqual(kind_args(step(state(3210, 6744, 3908), mem)), ('click', (14720,)))


if __name__ == '__main__':
    unittest.main()
