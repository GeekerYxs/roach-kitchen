"""5-man boss-gear line, step 3: the team walks from 荒芜之地1区 into 陷阱囚牢 (map 1150) (user 2026-11-06).

    python -X utf8 enter_cage.py

Same leg as the fullcrit70 line (projects/fullcrit_mage_leveling_70/route.py「陷阱囚牢」, run live by
trap_cage_53_58.py): in map 180 the leader leads the team to entrance NPC 10182 (2415,329) and clicks it;
maze_train fights the battles on the way. Already all five in 1150 with the full team -> nothing to do.
"""
from _bootstrap import LEADER, ROLES

import maze_train as m
import trial_run as t

DESERT_1, TRAP_CAGE = 180, 1150
ENTRANCE_NPC, ENTRANCE_XY = 10182, (2415, 329)


def in_cage(cs):
    lead = cs[0]
    return all((s := c.world()) and s.map_id == TRAP_CAGE for c in cs) and \
        set(lead.team()) == {c.char_id for c in cs}


def main():
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    if in_cage(cs):
        t.say('五人已经在陷阱囚牢，跳过')
        return
    if lead.world().map_id != DESERT_1:
        raise t.Stop(f'{LEADER} 不在荒芜之地1区（map {lead.world().map_id}），先跑 go_desert1.py')
    m.CASTERS = (LEADER,)
    m.STAGES = (dict(name='进入陷阱囚牢', goal=(TRAP_CAGE, None), maze=None, until=None, patrol_b=None,
                     legs={DESERT_1: ('click', ENTRANCE_NPC, ENTRANCE_XY)}),)
    m.main()
    # live 2026-11-06 12:49:58: m.main returns the moment the leader lands; two members were still on map 180
    try:
        t.wait(lambda: in_cage(cs), 15, '五人进陷阱囚牢')
    except t.Stop:
        raise t.Stop('没有五人一起进陷阱囚牢: ' +
                     str({c.name: c.world().map_id for c in cs}) + f'，队伍 {lead.team()}')
    s = lead.world()
    t.say(f'五人进了陷阱囚牢（map {TRAP_CAGE}），队长在 ({s.x:.0f},{s.y:.0f})')


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
