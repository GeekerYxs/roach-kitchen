"""七一矿渣领工资: from 缥缈之岛 go down into 恒温矿洞 and open its 3 藏宝箱 with 酸液.

    python -X utf8 research/qiyi/chest.py 飞天把你射成蜂窝 舔尊 ...

Done by hand on 飞天把你射成蜂窝 2026-10-28 (user's doc 永冻领3宝箱.doc, see FLOW.md step 8), starting at the 圣树:
  map 1300 north:  walk to (3827,1776), 结界机关 17026 (3880,1612) -> 「传送：伊甸岛」(1) -> same map, (760,6700)
  map 1300 south:  结界机关 17019 (840,6580) -> 「传送：神迹之地」(1) -> same map, (1830,3330)
  map 1300 middle: walk to (1528,3060), 秘境之门 17095 (1374,3029) -> 「穿越大门」(1) -> map 3110 (3624,5796)
  map 3110 south-east: walk to (3752,5804), 树洞 14752 (3880,5850) -> 「跳进去」(1) -> map 3210 恒温矿洞 (8760,4595)
  map 3210: walk to (6744,3908) (wild, 飞天 6 battles), then for each 藏宝箱 14719 / 14720 / 14721:
     click -> 「使用酸液破坏结界」(2) -> 「使用酸液破坏结界」(1) -> either 「再试一次」(1) (failed, 酸液 -1, back to the
     previous page) or 「（酸液起作用了！）」(1) -> 「打开箱子」(1) -> dialog closes, rewards in the bag.
     Clicked again: 「（这是个空箱子）」 with only 离开 = that chest is done.
  last, walk to (6344,4708) (the user's doc: where the next part, 打山科, starts).
飞天: 酸液 (item 100128) 25 -> 19 for the 3 chests (3 + 1 + 2 tries); got 低纯度冰钢岩 100070 +28,
风化的古兽化石 100075 +16, 赐福石1阶 100080 +8, 多维位面徽记 100134 +3.
Done = all three chests said 空箱子 and the character stands at the end point.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import go                                   # noqa: E402
import ganlu                                # noqa: E402
from go import Action, Leg, _near           # noqa: E402
from provisioner import world               # noqa: E402

ISLAND = 1300                               # 缥缈之岛
CAVE = 3210                                 # 恒温矿洞
NORTH_Y = 2700                              # 冰封湖 / 圣树 / 结界机关 17026 are north of this
SOUTH_Y = 5000                              # boat landing (4136,6044) and 伊甸岛 landing (760,6700) are south of this
ISLAND_LEGS = {                             # same map, so each part of the island gets its own row
    'north': Leg((3827, 1776), 17026, '传送：伊甸岛', ISLAND),          # 结界机关 (3880,1612)
    'south': Leg((760, 6700), 17019, '传送：神迹之地', ISLAND),         # 结界机关 (840,6580)
    'middle': Leg((1528, 3060), 17095, '穿越大门', 3110),               # 秘境之门 (1374,3029)
}
HOLE = Leg((3752, 5804), 14752, '跳进去', CAVE)                         # 树洞 (3880,5850)
HOLE_AREA = (3000, 5000)                    # 3110 x,y at least this = the 秘境之门 landing side, else walk via 红猪大叔
STAND = (6744, 3908)
CHESTS = (14719, 14720, 14721)              # 藏宝箱 (6664,4084) (6568,3964) (6856,3956)
END = (6344, 4708)
ACID = 100128                               # 酸液 (宝箱怪的酸液)
EMPTY = '这是个空箱子'
STEPS = ('使用酸液破坏结界', '再试一次', '（酸液起作用了！）', '打开箱子')


def island_leg(w):
    if w.y < NORTH_Y:
        return ISLAND_LEGS['north']
    return ISLAND_LEGS['south'] if w.y >= SOUTH_Y else ISLAND_LEGS['middle']


def decide(w, done=(), acid=None):
    """done = chest ids that said 空箱子; acid = 酸液 in the bag (None = unknown)."""
    if w is None or w.in_battle or w.verification or w.busy:
        return go.decide(w, -1)
    if w.map_id == ISLAND:
        return go.decide(w, -1, {ISLAND: island_leg(w)})
    if w.map_id == 3110 and w.x >= HOLE_AREA[0] and w.y >= HOLE_AREA[1]:
        return go.decide(w, CAVE, {3110: HOLE})
    if w.map_id != CAVE:
        return go.decide(w, ISLAND, ganlu.ROUTE)   # anywhere else on the way (外城 ... 永冻群山 红猪大叔)
    if w.dialog:
        if EMPTY in w.dialog.text:
            return Action('pick', (0,), '空箱子，关掉')
        for want in STEPS:
            for opt, label in w.dialog.options:
                if label == want:
                    return Action('pick', (opt,), f'选 {want}')
        return Action('fail', why=f'没见过的对话: {w.dialog.text!r} {w.dialog.options}')
    if w.nav_active:
        return go.decide(w, -1)                # wait / cancel a stuck walk
    chest = next((c for c in CHESTS if c not in done), None)
    if chest is None:
        if _near(w, END, 30):
            return Action('done', why='3 个宝箱都空了')
        return Action('nav', (CAVE, *END), '去 打山科 的位置')
    if acid == 0:
        return Action('fail', why='没有酸液了')
    if not _near(w, STAND, go.NEAR):
        return Action('nav', (CAVE, *STAND), '去 宝箱')
    return Action('click', (chest,), f'点 藏宝箱 {chest}')


def make_step():
    seen = {'done': set(), 'clicked': None, 'start': None}

    def step(w, mem):
        bag = world.read_bag(mem)
        acid = None if bag is None else world.item_count(bag, ACID)
        if seen['start'] is None:
            seen['start'] = acid
        if w and w.dialog and EMPTY in w.dialog.text and seen['clicked'] in CHESTS:
            seen['done'].add(seen['clicked'])
        a = decide(w, seen['done'], acid)
        if a.kind == 'click':
            seen['clicked'] = a.args[0]
        if a.kind == 'done':
            a = Action('done', why=f'{a.why}，酸液 {seen["start"]} -> {acid}')
        return a
    return step


if __name__ == '__main__':
    if not sys.argv[1:]:
        sys.exit(print(__doc__))
    go.TIMEOUT = 1500                       # 圣树 -> 17026 and the cave walk are both wild ground
    sys.exit(go.run_all(tuple(sys.argv[1:]), make_step))
