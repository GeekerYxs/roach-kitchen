"""5-man boss-gear line, 狗贼贼 step 3: the team walks from 皮克斯 in 苦无沙漠2区 into 巨石之城南部遗址 (map 1050)
(user 2026-11-06).

    python -X utf8 enter_ruins.py

Entrance NPC 10178 at (675,2635) in map 171 (ResLib NPCDirection); mapgrid: ~2400 px of path from 皮克斯.
"""
from _bootstrap import LEADER, ROLES

import maze_train as m
import gouzei as gz
import trial_run as t


def in_ruins(cs):
    return all((s := c.world()) and s.map_id == gz.RUINS for c in cs) and gz.team_full(cs)


def main():
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    if in_ruins(cs):
        t.say('五人已经在巨石之城南部遗址，跳过')
        return
    if lead.world().map_id != gz.KUWU_2:
        raise t.Stop(f'{LEADER} 不在苦无沙漠2区（map {lead.world().map_id}），先跑 go_kuwu2.py')
    m.CASTERS = (LEADER,)
    m.STAGES = (dict(name='进入巨石之城南部遗址', goal=(gz.RUINS, None), maze=None, until=None, patrol_b=None,
                     legs={gz.KUWU_2: ('click', gz.GATE_NPC, gz.GATE_XY)}),)
    m.main()
    try:
        t.wait(lambda: in_ruins(cs), 15, '五人进巨石之城南部遗址')
    except t.Stop:
        raise t.Stop('没有五人一起进遗址: ' + str({c.name: c.world().map_id for c in cs}) + f'，队伍 {lead.team()}')
    s = lead.world()
    t.say(f'五人进了巨石之城南部遗址（map {gz.RUINS}），队长在 ({s.x:.0f},{s.y:.0f})')


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
