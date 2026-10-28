"""Team (SHITU_MASTERS leader + SHITU_APPRENTICES) to 通天塔一区 (map 280), stopping at a spot there (task 181 step 7:
5 花露 from the 通天花 NPCs 954-959, NPCDirection.csv).

    python -X utf8 research/shitu/tower1_go.py [X Y]          default: 通天花 954 (292,4295), the nearest to the 路口 gate

From map 1 / 81: pp_chain to 通天塔路口 (279), then 通天塔门 952 (935,290)「到通天塔一区」; maze_train's goal stage.
"""
import sys

import maze_train as m
import pp_chain

SPOT = tuple(map(int, sys.argv[1:3])) if len(sys.argv) > 2 else (292, 4295)
m.STAGES = (
    dict(name='通天塔一区', goal=(280, SPOT), maze=None, until=None, patrol_b=None,
         legs={279: ('click', 952, (935, 290), '一区')}),
)

def bottle():
    """Task 181: an apprentice without step 6 never got the 花露瓶 from NPC 304 (2026-10-28 亿万9/12: bag full at the
    crystal step's talk) and gathers nothing; it fetches it now from 逍遥村 (bag cleared to 3 free slots first)."""
    import os
    import talk_chain
    from common import APPRENTICES
    from provisioner import world as w
    if m.t.Client(m.LEADER).world().map_id != 1:
        return
    stages = m.STAGES
    import r4_util              # imports quanshou, which sets maze_train.STAGES
    from quanshou import scroll
    m.STAGES = stages
    for n in APPRENTICES:       # 2026-10-28 team A: a restart left 亿万1/2/4 in the 古迹 (650); everybody starts at home
        c = m.t.Client(n)
        if c.world().map_id != 1:
            c.game.cancel_navigation()
            m.t.wait(lambda: not c.world().in_battle, 120, f'{n} 战斗结束')
            scroll(c)
    if os.environ.get('SHITU_QID', '181') != '181':
        return
    need = [n for n in APPRENTICES if len(w.read_quest(m.t.Client(n).mem, 181).steps) == 5]
    if not need:
        return
    r4_util.space(3)
    for n in need:
        m.t.say(f'[{n}] 181 没有第 6 步（没拿到花露瓶），先回 NPC 304')
        talk_chain.run(n, 8, (894, 459), 304, '战士的试炼')
        c = m.t.Client(n)
        m.t.say(f'[{n}] 181 {w.read_quest(c.mem, 181)}')
        if c.world().map_id != 1:
            scroll(c)


if __name__ == '__main__':
    try:
        bottle()
        if m.t.Client(m.LEADER).world().map_id not in (279, 280):
            pp_chain.main('通天塔', ['平静海岸2区'])
        m.main()
    except m.t.Stop as e:
        m.t.say(f'停止: {e}')
        raise SystemExit(1)
