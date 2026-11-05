"""Rescue an apprentice stranded in 1100 without a return scroll after a failed parallel home operation.

    python -X utf8 rescue_scrollless_apprentice.py 小号名
"""
import _bootstrap  # noqa: F401
import math
import sys

import maze_train as m
import pp_chain
import trial_run as t
from common import APPRENTICES
from lunhui15 import LEADER
from provisioner import world as w
import supply_go
from factory.phase import SCROLL_ITEM

STRANDED = sys.argv[1] if len(sys.argv) > 1 else None
DESERT_3, RUIN_EAST = 172, 1100


def main():
    if STRANDED not in APPRENTICES:
        raise t.Stop(f'请指定要救援的小号名（team.toml 里的 {list(APPRENTICES)}），收到：{STRANDED}')
    lead = t.Client(LEADER)
    lost = t.Client(STRANDED)
    if lost.world().map_id == 1:
        return
    if lead.world().map_id != 1:
        raise t.Stop(f'救援要求队长在村里，当前 map={lead.world().map_id}')

    pp_chain.main('苦无沙漠3区', ['平静海岸2区', '龙之都', '恶人山'])
    m.STAGES = (dict(name='救援无回城卷队员', goal=(RUIN_EAST, None), maze=None, until=None,
                     patrol_b=None, legs={DESERT_3: ('click', 10180, (642, 1180))}),)
    m.main()
    if lead.world().map_id != RUIN_EAST or lost.world().map_id != RUIN_EAST:
        raise t.Stop(f'队长/队员不在同一救援地图：{lead.world().map_id}/{lost.world().map_id}')

    target = lost.world()
    if math.dist((lead.world().x, lead.world().y), (target.x, target.y)) > supply_go.TRADE_NEAR:
        lead.game.navigate(RUIN_EAST, round(target.x) + 25, round(target.y))
        t.wait(lambda: (s := lead.world()) and math.dist((s.x, s.y),
                (lost.world().x, lost.world().y)) <= supply_go.TRADE_NEAR and not s.moving,
                180, '队长走到无卷队员旁边')
    slot = max((s for s in w.read_bag(lead.mem) or () if s.item_id == SCROLL_ITEM),
               key=lambda s: s.quantity, default=None)
    if not slot:
        raise t.Stop('队长背包没有可交易的回城卷')
    before = supply_go.scrolls(lost)
    amount = min(5, slot.quantity)
    supply_go.trade_until(lead, lost, (lead.game.trade_offer_item, (slot.slot, amount)),
                          lambda: supply_go.scrolls(lost) >= before + amount,
                          f'{STRANDED} 获得回城卷')
    lost_slot = next(s.slot for s in w.read_bag(lost.mem) if s.item_id == SCROLL_ITEM)
    lost.game.use_item(lost_slot)
    t.wait(lambda: lost.world().map_id in (1, 8), 15, f'{STRANDED} 使用回城卷回村')
    t.say(f'[{STRANDED}] 救援后已回村；队长与队伍成员随后各自回城')

    from line.ops import home_village
    home_village()


if __name__ == '__main__':
    try:
        main()
    except t.Stop as exc:
        lead = t.Client(LEADER)
        if lead.world().nav_active:
            lead.game.cancel_navigation()
        t.say(f'停止：{exc}')
        raise SystemExit(1)
