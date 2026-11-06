"""5-man boss-gear line, 老树叶 step 3: the team walks from 迷惑森林3区 into 失落之地 (map 950) (user 2026-11-06).

    python -X utf8 enter_lost.py

Entrance NPC 10195 at (2178,85) in map 152 (ResLib NPCDirection; SubTask 673 says (2157,99)).
"""
from _bootstrap import LEADER, ROLES

import leaf as lf
import maze_train as m
import trial_run as t


def in_lost(cs):
    lead = cs[0]
    return all((s := c.world()) and s.map_id == lf.LOST for c in cs) and \
        set(lead.team()) == {c.char_id for c in cs}


def main():
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    if in_lost(cs):
        t.say('五人已经在失落之地，跳过')
        return
    if lead.world().map_id != lf.FOREST_3:
        raise t.Stop(f'{LEADER} 不在迷惑森林3区（map {lead.world().map_id}），先跑 go_forest3.py')
    m.CASTERS = (LEADER,)
    m.STAGES = (dict(name='进入失落之地', goal=(lf.LOST, None), maze=None, until=None, patrol_b=None,
                     legs={lf.FOREST_3: ('click', lf.GATE_NPC, lf.GATE_XY)}),)
    m.main()
    try:
        t.wait(lambda: in_lost(cs), 15, '五人进失落之地')
    except t.Stop:
        raise t.Stop('没有五人一起进失落之地: ' + str({c.name: c.world().map_id for c in cs}) + f'，队伍 {lead.team()}')
    s = lead.world()
    t.say(f'五人进了失落之地（map {lf.LOST}），队长在 ({s.x:.0f},{s.y:.0f})')


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
