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

if __name__ == '__main__':
    try:
        if m.t.Client(m.LEADER).world().map_id not in (279, 280):
            pp_chain.main('通天塔', ['平静海岸2区'])
        m.main()
    except m.t.Stop as e:
        m.t.say(f'停止: {e}')
        raise SystemExit(1)
