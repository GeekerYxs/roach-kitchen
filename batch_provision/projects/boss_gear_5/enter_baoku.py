"""5-man boss-gear line, 金刚猴 step 3: the team walks from 龙上利 in 迷惑森林1区 into 秘密宝窟 (map 850) (user 2026-11-06).

    python -X utf8 enter_baoku.py

Entrance NPC 10170 at (211,210) in map 150 (ResLib NPCDirection; mole.py clicked it live 2026-11-03 from (212,211)).
mapgrid: ~1050 px of path from 龙上利.
"""
from _bootstrap import LEADER, ROLES

import maze_train as m
import monkey as mk
import trial_run as t


def in_baoku(cs):
    lead = cs[0]
    return all((s := c.world()) and s.map_id == mk.BAOKU for c in cs) and mk.team_full(cs)


def main():
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    if in_baoku(cs):
        t.say('五人已经在秘密宝窟，跳过')
        return
    if lead.world().map_id != mk.FOREST_1:
        raise t.Stop(f'{LEADER} 不在迷惑森林1区（map {lead.world().map_id}），先跑 go_forest1.py')
    m.CASTERS = (LEADER,)
    m.STAGES = (dict(name='进入秘密宝窟', goal=(mk.BAOKU, None), maze=None, until=None, patrol_b=None,
                     legs={mk.FOREST_1: ('click', mk.GATE_NPC, mk.GATE_XY)}),)
    m.main()
    try:
        t.wait(lambda: in_baoku(cs), 15, '五人进秘密宝窟')
    except t.Stop:
        raise t.Stop('没有五人一起进秘密宝窟: ' + str({c.name: c.world().map_id for c in cs}) + f'，队伍 {lead.team()}')
    s = lead.world()
    t.say(f'五人进了秘密宝窟（map {mk.BAOKU}），队长在 ({s.x:.0f},{s.y:.0f})')


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
