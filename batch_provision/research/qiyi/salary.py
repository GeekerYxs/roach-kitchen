"""七一矿渣领工资: walk to 永冻群山 (go.py ROUTE) and take the daily pay from each NPC in CLAIMS, in order.

    python -X utf8 research/qiyi/salary.py 飞天把你射成蜂窝 舔尊 ...

Each claim was first done by hand on 飞天把你射成蜂窝 2026-10-28 (see FLOW.md), all pay 龙之都金龙币 (item 100106):
  算得快 14603 (664,4132): 「领取开拓团薪金」 -> 「领取今天的薪水」 -> +40 (20/30/40 by 开拓团 reputation)
        same day again: 「你今天已经领过薪水了…」 + 「好的」
  达哥罗斯 14604 (220,4477): 「每日津贴：勘探先锋防寒补助」 -> 「立刻领取」 -> +20 (6..20 by 开拓军 reputation)
        same day again: 「你已经拿过今天的津贴…」 + 查看津贴奖励 / 返回
A claim is done when the coins went up since it started, or the server said it was already taken today.
Option 0 (离开) closes any of these dialogs.
"""
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import go                                   # noqa: E402
from go import Action, _near                # noqa: E402
from provisioner import world               # noqa: E402

MAP = 3110
COIN = 100106                               # 龙之都金龙币


@dataclass(frozen=True)
class Claim:
    name: str
    npc: int
    stand: tuple
    picks: tuple            # dialog labels to pick, whichever shows (menu entry, then the confirm page)
    already: str            # text the NPC shows when today's pay was taken


CLAIMS = (
    Claim('算得快 开拓团薪金', 14603, (664, 4172), ('领取开拓团薪金', '领取今天的薪水'), '已经领过'),
    Claim('达哥罗斯 防寒补助', 14604, (220, 4517), ('每日津贴：勘探先锋防寒补助', '立刻领取'), '已经拿过今天的津贴'),
)


def decide(w, claim, gained, already):
    """One action for one claim. gained = coins added since it started; already = the server said it was taken."""
    if w is None or w.map_id != MAP:
        return go.decide(w, MAP)
    if w.in_battle or w.verification or w.busy:
        return Action('wait', why='战斗/答题/忙')
    if w.dialog:
        if not (gained or already) and claim.already not in w.dialog.text:
            for opt, label in w.dialog.options:
                if label in claim.picks:
                    return Action('pick', (opt,), f'选 {label}')
        return Action('pick', (0,), '关对话')
    if gained:
        return Action('done', why=f'{claim.name} 金龙币 +{gained}')
    if already:
        return Action('done', why=f'{claim.name} 今天已经领过')
    if w.nav_active:
        return go.decide(w, -1)                # wait / cancel a stuck walk, same rule as the route
    if not _near(w, claim.stand, go.NEAR):
        return Action('nav', (MAP, *claim.stand), f'去 {claim.name}')
    return Action('click', (claim.npc,), f'点 {claim.name}')


def coins(mem):
    bag = world.read_bag(mem)
    return None if bag is None else world.item_count(bag, COIN)


def make_step(claims=CLAIMS):
    """Runs the claims one after another; 'done' only after the last one."""
    seen = {'i': 0, 'start': None, 'already': False, 'done': []}

    def step(w, mem):
        while True:
            claim = claims[seen['i']]
            now = coins(mem)
            if seen['start'] is None:
                seen['start'] = now
            if w and w.dialog and claim.already in w.dialog.text:
                seen['already'] = True
            a = decide(w, claim, max((now or 0) - (seen['start'] or 0), 0), seen['already'])
            if a.kind != 'done':
                return a
            seen['done'].append(a.why)
            if seen['i'] == len(claims) - 1:
                return Action('done', why='；'.join(seen['done']))
            seen.update(i=seen['i'] + 1, start=None, already=False)
    return step


if __name__ == '__main__':
    if not sys.argv[1:]:
        sys.exit(print(__doc__))
    sys.exit(go.run_all(tuple(sys.argv[1:]), make_step))
