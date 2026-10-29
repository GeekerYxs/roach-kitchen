"""七一矿渣领工资: walk to 缥缈之岛 冰封湖 and pick today's 圣树甘露 once.

    python -X utf8 research/qiyi/ganlu.py 飞天把你射成蜂窝 舔尊 ...

Done by hand on 飞天把你射成蜂窝 2026-10-28 (see FLOW.md):
  map 20 -> 25 -> 3100 -> 3110 永冻群山 (go.py ROUTE), then
  map 3110: walk to (440,3516), 红猪大叔 14601 (568,3476) -> 「飞往缥缈之岛」(2) -> map 1300 (4136,6044)
  map 1300 south: walk to (812,6560) (wild, random battles), 结界机关 17019 (840,6580) -> 「传送：冰封湖」(2)
            -> same map, (3890,1700)
  map 1300 north: walk to (1016,2148) (wild), 圣树 -> 「摘取圣树甘露」(1) -> 圣树甘露 (item 100501) +6 on 飞天.
  Again: 「（圣树今天凝结的甘露已经采摘过了，请明日再来）」, no options.
The server answers a click on any of the tree ids 17028..17031 with that growth stage's page; only the stage this
character's tree is at (飞天: 17029 茁壮) offers 摘取. So the script clicks them in turn and skips ids without 摘取.
Done = 圣树甘露 went up, or the tree said 已经采摘过 (and the dialog is closed).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import go                                   # noqa: E402
from go import Action, Leg, _near           # noqa: E402
from provisioner import world               # noqa: E402

MAP = 1300                                  # 缥缈之岛
ROUTE = {**go.ROUTE, 3110: Leg((440, 3516), 14601, '飞往缥缈之岛', MAP)}            # 红猪大叔 (568,3476)
GATE = {MAP: Leg((812, 6560), 17019, '传送：冰封湖', MAP)}                         # 结界机关 (840,6580)
NORTH_Y = 3000                              # 冰封湖 landing (3890,1700) and the tree are north of this; boat landing south
STAND = (1016, 2148)
TREES = (17029, 17030, 17031, 17028)        # 茁壮 / 成熟 / 参天 / 稚嫩: one of them is this character's stage
PICK = '摘取圣树甘露'
PICKED = '已经采摘过了'
GANLU = 100501                              # 圣树甘露


def decide(w, finished, bad=()):
    """finished = 甘露 went up or the tree said 已经采摘过; bad = tree ids whose page had no 摘取."""
    if w is None or w.map_id != MAP:
        return go.decide(w, MAP, ROUTE)
    if w.in_battle or w.verification or w.busy:
        return Action('wait', why='战斗/答题/忙')
    if w.y >= NORTH_Y:
        return go.decide(w, -1, GATE)          # 结界机关 -> 冰封湖 (same map, so the goal is never "reached")
    if w.dialog:
        if not finished and PICKED not in w.dialog.text:
            for opt, label in w.dialog.options:
                if label == PICK:
                    return Action('pick', (opt,), f'选 {PICK}')
        return Action('pick', (0,), '关对话')
    if finished:
        return Action('done', why='今天的圣树甘露摘过了')
    if w.nav_active:
        return go.decide(w, -1)                # wait / cancel a stuck walk
    if not _near(w, STAND, go.NEAR):
        return Action('nav', (MAP, *STAND), '去 圣树')
    tree = next((t for t in TREES if t not in bad), None)
    if tree is None:
        return Action('fail', why=f'圣树 {TREES} 都没有「{PICK}」')
    return Action('click', (tree,), f'点 圣树 {tree}')


def ganlu(mem):
    bag = world.read_bag(mem)
    return None if bag is None else world.item_count(bag, GANLU)


def make_step():
    seen = {'finished': False, 'start': None, 'clicked': None, 'bad': set()}

    def step(w, mem):
        now = ganlu(mem)
        if seen['start'] is None:
            seen['start'] = now
        elif now is not None and seen['start'] is not None and now > seen['start']:
            seen['finished'] = True
        if w and w.dialog:
            if PICKED in w.dialog.text:
                seen['finished'] = True
            elif seen['clicked'] in TREES and not any(label == PICK for _, label in w.dialog.options):
                seen['bad'].add(seen['clicked'])       # another growth stage's page: try the next id
        a = decide(w, seen['finished'], seen['bad'])
        seen['clicked'] = a.args[0] if a.kind == 'click' else (None if a.kind == 'pick' else seen['clicked'])
        if a.kind == 'done':
            a = Action('done', why=f'{a.why}，圣树甘露 {seen["start"]} -> {now}')
        return a
    return step


if __name__ == '__main__':
    if not sys.argv[1:]:
        sys.exit(print(__doc__))
    sys.exit(go.run_all(tuple(sys.argv[1:]), make_step))
