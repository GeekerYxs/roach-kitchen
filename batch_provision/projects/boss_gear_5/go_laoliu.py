"""5-man boss-gear line, 电锯杀人王 step 1: everybody home, 伏地魔1 forms the team, PP鸡 逍遥村 -> 平静海岸2区 ->
龙之都, walk to 老刘 in 龙之都外城 (user 2026-11-06).

    python -X utf8 go_laoliu.py

The PP鸡 lands at (3954,273); 老刘 576 (3666,1959) is ~1700 px of path south. The walk goes round the walk-in doors of
map 20 (chainsaw.walk, mapgrid.DOORS: 2026-11-06 the client's own path went into 连锁商店 map 31).
Already the full team in 20 -> only the walk; in 连锁商店 (31) -> walk out first; in 24 / 25 / 264 -> home.
"""
from _bootstrap import ROLES

import pp_chain
import trial_run as t

import chainsaw as cz
import go_desert1

STAND_REACH = 200
VIA = ['平静海岸2区']


def out_of_shop(cs):
    lead = cs[0]
    if lead.world().map_id == cz.SHOP:
        t.say('队伍在龙之都连锁商店里，先走出商店')
        cz.cross(lead, cs, cz.SHOP_EXIT, cz.OUTER, '商店出口')


def main():
    from provisioner import quizbot          # AGENTS.md: every line entry makes sure the quiz bot runs
    quizbot.ensure(say=t.say)
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    out_of_shop(cs)
    if not cz.all_in(cs, cz.OUTER):
        go_desert1.home(cs)
        pp_chain.main('龙之都', list(VIA))   # forms the team (leader first in ROLES), then hops
    cz.walk(lead, cz.LAOLIU_XY, '老刘', reach=STAND_REACH)
    try:
        t.wait(lambda: cz.all_in(cs, cz.OUTER), 15, '全队到龙之都外城老刘旁')
    except t.Stop:
        raise t.Stop('没有全队一起到老刘旁: ' + str({c.name: c.world().map_id for c in cs}) + f'，队伍 {lead.team()}')
    s = lead.world()
    t.say(f'{len(cs)} 人在龙之都外城老刘旁边，队长在 ({s.x:.0f},{s.y:.0f})')


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
