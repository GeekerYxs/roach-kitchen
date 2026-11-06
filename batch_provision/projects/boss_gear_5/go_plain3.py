"""5-man boss-gear line, 葵花 step 1: the team gets to 苦力强 at the camp of 无尽平原3区 (map 142) (user 2026-11-06).

    python -X utf8 go_plain3.py

142 has no PP鸡 (pp_chain). ResLib maplink: 龙之都外城 20 -> 142 at (5184,48)-(5304,168), landing by the 142 -> 20 rect
(3048,2976); 迷惑森林1区 150 -> 142 at its west edge (24,960), landing by (4068,708). Full team already in 142 or 150 ->
only the walk; else home, PP鸡 to 龙之都外城, walk across. 苦力强 = NPC 1607 at (1890,225) (NPCDirection).
"""
from _bootstrap import LEADER, ROLES

import maze_train as m
import pp_chain
import trial_run as t

import go_desert1
from go_desert2 import full_team

DRAGON, PLAIN_3, FOREST_1 = 20, 142, 150
STAND = (2064, 400)          # mapgrid: path-nearest cell within 250 px of 苦力强 from the 150 side (1648,280 from 20)


def main():
    from provisioner import quizbot          # AGENTS.md: every line entry makes sure the quiz bot runs
    quizbot.ensure(say=t.say)
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    if not any(full_team(cs, x) for x in (PLAIN_3, FOREST_1, DRAGON)):
        go_desert1.home(cs)
        pp_chain.main('龙之都', ['平静海岸2区'])     # forms the team (leader = 伏地魔1), then hops
    m.CASTERS = (LEADER,)
    leg = ('walk', PLAIN_3, STAND)
    m.STAGES = (dict(name='走到苦力强', goal=(PLAIN_3, STAND), maze=None, until=None, patrol_b=None,
                     legs={DRAGON: leg, FOREST_1: leg, PLAIN_3: leg}),)
    m.main()
    try:
        t.wait(lambda: full_team(cs, PLAIN_3), 15, '五人到无尽平原3区')
    except t.Stop:
        raise t.Stop('没有五人一起到无尽平原3区: ' + str({c.name: c.world().map_id for c in cs}) + f'，队伍 {lead.team()}')
    s = lead.world()
    t.say(f'五人在无尽平原3区苦力强旁边，队长在 ({s.x:.0f},{s.y:.0f})')


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
