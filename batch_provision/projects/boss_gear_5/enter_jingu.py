"""5-man boss-gear line, 虎力仙 step 3: the team walks from 荒芜之地2区 into 禁锢之地 (map 1200) (user 2026-11-06).

    python -X utf8 enter_jingu.py

Same leg as the fullcrit70 line (jingu_47_70.py): NPC 10184 at (3123,2630) in map 181, first option「传送至 禁锢之地」
(the 次元时空 ones are the crystal farm copies 1201..). Live 2026-11-06 16:56: the team lands at (8898,5985).
"""
from _bootstrap import LEADER, ROLES

import maze_train as m
import tiger as tg
import trial_run as t

GATE_NPC, GATE_XY = 10184, (3123, 2630)


def in_jingu(cs):
    lead = cs[0]
    return all((s := c.world()) and s.map_id == tg.JINGU for c in cs) and \
        set(lead.team()) == {c.char_id for c in cs}


def main():
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    if in_jingu(cs):
        t.say('五人已经在禁锢之地，跳过')
        return
    if lead.world().map_id != tg.DESERT_2:
        raise t.Stop(f'{LEADER} 不在荒芜之地2区（map {lead.world().map_id}），先跑 go_desert2.py')
    m.CASTERS = (LEADER,)
    m.STAGES = (dict(name='进入禁锢之地', goal=(tg.JINGU, None), maze=None, until=None, patrol_b=None,
                     legs={tg.DESERT_2: ('click', GATE_NPC, GATE_XY)}),)
    m.main()
    try:
        t.wait(lambda: in_jingu(cs), 15, '五人进禁锢之地')
    except t.Stop:
        raise t.Stop('没有五人一起进禁锢之地: ' + str({c.name: c.world().map_id for c in cs}) + f'，队伍 {lead.team()}')
    s = lead.world()
    t.say(f'五人进了禁锢之地（map {tg.JINGU}），队长在 ({s.x:.0f},{s.y:.0f})')


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
