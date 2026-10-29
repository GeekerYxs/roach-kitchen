"""七一矿渣领工资: walk to 星灵神域 (go.py ROUTE) and use today's wishes at 祈愿神像 for 秩序之源碎片.

    python -X utf8 research/qiyi/wish.py 飞天把你射成蜂窝 舔尊 ...

Done by hand on 飞天把你射成蜂窝 2026-10-28 (see FLOW.md):
  map 3120: walk to (1310,2421), 祈愿神像 14630 (1310,2381) -> 「许愿」(1) -> rules page
  (2/4/8 wishes a day by 星灵神域 reputation) -> 「许愿秩序之源碎片」(1) -> page 「需要消耗3000点神识 … 可祈福8/8次」
  -> 「开始许愿」(1) again and again on the same page: each one 3000 神识, 秩序源力碎片 (item 100039) +1..+26 at random,
  counter 8/8 -> 0/8. One more: 「（今天你许的愿望已经够多了，请明日再来）」 + 「好的」.
Done = the counter showed 0/N or the statue said 已经够多了 (and the dialog is closed).
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import go                                   # noqa: E402
from go import Action, _near                # noqa: E402
from provisioner import world               # noqa: E402

MAP = 3120
NPC = 14630                                 # 祈愿神像
STAND = (1310, 2421)
PICKS = ('许愿', '许愿秩序之源碎片', '开始许愿')
COUNTER = re.compile(r'可祈福(\d+)/(\d+)次')
ENOUGH = '已经够多了'
SHARD = 100039                              # 秩序源力碎片


def left(w):
    """Wishes left today as the open dialog shows them, or None."""
    m = COUNTER.search(w.dialog.text) if w and w.dialog else None
    return int(m.group(1)) if m else None


def decide(w, finished):
    """finished = the counter reached 0 or the statue said 已经够多了."""
    if w is None or w.map_id != MAP:
        return go.decide(w, MAP)
    if w.in_battle or w.verification or w.busy:
        return Action('wait', why='战斗/答题/忙')
    if w.dialog:
        if not finished and ENOUGH not in w.dialog.text and left(w) != 0:
            for opt, label in w.dialog.options:
                if label in PICKS:
                    return Action('pick', (opt,), f'选 {label}' + (f'（还剩 {left(w)} 次）' if left(w) else ''))
        return Action('pick', (0,), '关对话')
    if finished:
        return Action('done', why='今天的许愿用完了')
    if w.nav_active:
        return go.decide(w, -1)                # wait / cancel a stuck walk (here the flag stayed on after arrival)
    if not _near(w, STAND, go.NEAR):
        return Action('nav', (MAP, *STAND), '去 祈愿神像')
    return Action('click', (NPC,), '点 祈愿神像')


def shards(mem):
    bag = world.read_bag(mem)
    return None if bag is None else world.item_count(bag, SHARD)


def make_step():
    seen = {'finished': False, 'start': None}

    def step(w, mem):
        if seen['start'] is None:
            seen['start'] = shards(mem)
        if w and w.dialog and (ENOUGH in w.dialog.text or left(w) == 0):
            seen['finished'] = True
        a = decide(w, seen['finished'])
        if a.kind == 'done':
            now = shards(mem)
            a = Action('done', why=f'{a.why}，秩序源力碎片 {seen["start"]} -> {now}')
        return a
    return step


if __name__ == '__main__':
    if not sys.argv[1:]:
        sys.exit(print(__doc__))
    sys.exit(go.run_all(tuple(sys.argv[1:]), make_step))
