"""5-man boss-gear line, 狗贼贼 step 1: everybody home, 伏地魔1 forms the team, PP鸡 to 苦无沙漠3区 (map 172), walk
across the 172 -> 171 link to 皮克斯 in 苦无沙漠2区 (user 2026-11-06).

    python -X utf8 go_kuwu2.py

PP鸡 route 逍遥村 -> 平静海岸2区 -> 龙之都 -> 恶人山 -> 苦无沙漠3区 is go_desert1.py's without the last hop. mapgrid:
172 landing (1051,350) -> link (444,84) ~800 px, then 171 east edge -> 皮克斯 ~2000 px.
Already five in 171 (or 172) with the full team -> only the walk.
"""
from _bootstrap import LEADER, ROLES

import maze_train as m
import pp_chain
import trial_run as t

import go_desert1
import gouzei as gz
from go_desert2 import full_team

VIA = ['平静海岸2区', '龙之都', '恶人山']


def main():
    from provisioner import quizbot          # AGENTS.md: every line entry makes sure the quiz bot runs
    quizbot.ensure(say=t.say)
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    if not full_team(cs, gz.KUWU_2) and not full_team(cs, gz.DESERT_3):
        go_desert1.home(cs)
        pp_chain.main('苦无沙漠3区', list(VIA))  # forms the team (leader = 伏地魔1), then hops
    m.CASTERS = (LEADER,)
    m.STAGES = (dict(name='走到皮克斯', goal=(gz.KUWU_2, gz.PIKES_STAND), maze=None, until=None, patrol_b=None,
                     legs={gz.DESERT_3: ('walk', gz.KUWU_2, gz.PIKES_STAND),
                           gz.KUWU_2: ('walk', gz.KUWU_2, gz.PIKES_STAND)}),)
    m.main()
    try:
        t.wait(lambda: full_team(cs, gz.KUWU_2), 15, '五人到苦无沙漠2区')
    except t.Stop:
        raise t.Stop('没有五人一起到苦无沙漠2区: ' + str({c.name: c.world().map_id for c in cs}) + f'，队伍 {lead.team()}')
    s = lead.world()
    t.say(f'五人在苦无沙漠2区皮克斯旁边，队长在 ({s.x:.0f},{s.y:.0f})')


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
