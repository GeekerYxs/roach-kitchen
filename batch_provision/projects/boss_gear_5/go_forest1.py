"""5-man boss-gear line, 金刚猴 step 1: everybody home, 伏地魔1 forms the team, PP鸡 to 圣人谷 (map 40), walk west into
迷惑森林1区 (map 150) and on to 龙上利 (user 2026-11-06).

    python -X utf8 go_forest1.py

150 has no PP鸡 (ResLib NPCDirection); its neighbours are 圣人谷 40 (exit at the east edge, (4128,840)) and 无尽平原3区
142. Route 逍遥村 -> 平静海岸2区 -> 龙之都外城 -> 圣人谷 as in go_forest3.py, then walk. mapgrid: from the 40-side
landing to 龙上利 is ~7100 px of path (the forest is a maze).
Already five in 150 with the full team -> only the walk to 龙上利.
"""
from _bootstrap import LEADER, ROLES

import maze_train as m
import pp_chain
import trial_run as t

import go_desert1
from go_desert2 import full_team

SAINT, FOREST_1 = 40, 150
VIA = ['平静海岸2区', '龙之都']
STAND = (1504, 264)          # mapgrid: the path-nearest roomy cell within 250 px of 龙上利 (1746,206)


def main():
    from provisioner import quizbot          # AGENTS.md: every line entry makes sure the quiz bot runs
    quizbot.ensure(say=t.say)
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    if not full_team(cs, FOREST_1) and not full_team(cs, SAINT):
        go_desert1.home(cs)
        pp_chain.main('圣人谷', list(VIA))     # forms the team (leader = 伏地魔1), then hops
    m.CASTERS = (LEADER,)
    m.STAGES = (dict(name='走到龙上利', goal=(FOREST_1, STAND), maze=None, until=None, patrol_b=None,
                     legs={SAINT: ('walk', FOREST_1, STAND), FOREST_1: ('walk', FOREST_1, STAND)}),)
    m.main()
    try:
        t.wait(lambda: full_team(cs, FOREST_1), 15, '五人到迷惑森林1区')
    except t.Stop:
        raise t.Stop('没有五人一起到迷惑森林1区: ' + str({c.name: c.world().map_id for c in cs}) + f'，队伍 {lead.team()}')
    s = lead.world()
    t.say(f'五人在迷惑森林1区龙上利旁边，队长在 ({s.x:.0f},{s.y:.0f})')


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
