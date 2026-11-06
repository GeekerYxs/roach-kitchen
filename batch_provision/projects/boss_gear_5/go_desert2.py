"""5-man boss-gear line, 虎力仙 step 1: the team gets to 银狐王勇 in 荒芜之地2区 (map 181) (user 2026-11-06).

    python -X utf8 go_desert2.py

Already in 181 with the full team -> walk to 王勇 only. In 180 -> walk across, the leg the fullcrit70 line ran live
(route.py「禁锢之地」: walk to (4120,2600) in 180). Anywhere else -> go_desert1 (home + PP鸡 to 180) first.
银狐王勇 = NPC 2603 at (750,1665) (ResLib NPCDirection); research/jingu/turnin.py stands at (750,1705).
"""
from _bootstrap import LEADER, ROLES

import maze_train as m
import trial_run as t

import go_desert1

DESERT_1, DESERT_2 = 180, 181
TO_DESERT_2 = (4120, 2600)
WANGYONG, WANGYONG_XY = 2603, (750, 1665)
STAND = (750, 1705)


def full_team(cs, map_id):
    lead = cs[0]
    return all((s := c.world()) and s.map_id == map_id for c in cs) and \
        set(lead.team()) == {c.char_id for c in cs}


def main():
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    if not full_team(cs, DESERT_2) and not full_team(cs, DESERT_1):
        go_desert1.main()
    m.CASTERS = (LEADER,)
    m.STAGES = (dict(name='走到银狐王勇', goal=(DESERT_2, STAND), maze=None, until=None, patrol_b=None,
                     legs={DESERT_1: ('walk', DESERT_2, STAND)}),)
    m.main()
    try:
        t.wait(lambda: full_team(cs, DESERT_2), 15, '五人到荒芜之地2区')
    except t.Stop:
        raise t.Stop('没有五人一起到荒芜之地2区: ' + str({c.name: c.world().map_id for c in cs}) + f'，队伍 {lead.team()}')
    s = lead.world()
    t.say(f'五人在荒芜之地2区银狐王勇旁边，队长在 ({s.x:.0f},{s.y:.0f})')


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
