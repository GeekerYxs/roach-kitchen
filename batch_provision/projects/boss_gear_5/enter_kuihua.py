"""5-man boss-gear line, 葵花 step 3: the team walks from 苦力强 in 无尽平原3区 into 葵花魔穴 (map 800) (user 2026-11-06).

    python -X utf8 enter_kuihua.py

Entrance NPC 10168 at (3165,2244) in map 142 (ResLib NPCDirection, type 3 = click). mapgrid: ~2600 px from 苦力强.
"""
from _bootstrap import LEADER, ROLES

import kuihua as kh
import maze_train as m
import trial_run as t


def in_cave(cs):
    return all((s := c.world()) and s.map_id == kh.CAVE for c in cs) and kh.team_full(cs)


def main():
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    if in_cave(cs):
        t.say('五人已经在葵花魔穴，跳过')
        return
    if lead.world().map_id != kh.PLAIN_3:
        raise t.Stop(f'{LEADER} 不在无尽平原3区（map {lead.world().map_id}），先跑 go_plain3.py')
    m.CASTERS = (LEADER,)
    m.STAGES = (dict(name='进入葵花魔穴', goal=(kh.CAVE, None), maze=None, until=None, patrol_b=None,
                     legs={kh.PLAIN_3: ('click', kh.GATE_NPC, kh.GATE_XY)}),)
    m.main()
    try:
        t.wait(lambda: in_cave(cs), 15, '五人进葵花魔穴')
    except t.Stop:
        raise t.Stop('没有五人一起进葵花魔穴: ' + str({c.name: c.world().map_id for c in cs}) + f'，队伍 {lead.team()}')
    s = lead.world()
    t.say(f'五人进了葵花魔穴（map {kh.CAVE}），队长在 ({s.x:.0f},{s.y:.0f})')


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
