"""Team (SHITU_MASTERS leader + SHITU_APPRENTICES) to 通天塔二区 (map 281) and stop on arrival (user, round 3 12:2x).

    python -X utf8 research/shitu/tower2_go.py

From anywhere pp_chain can start (map 1 / 81): PP鸡 -> 通天塔路口 (279), then 通天塔门 952 (935,290) option
「到通天塔二区」 (menu seen 11:08: 1 到通天塔一区 / 2 到通天塔二区 / 离开). maze_train's loop with a goal stage.
"""
import sys

import maze_train as m
import pp_chain

m.STAGES = (
    dict(name='通天塔二区', goal=(281, None), maze=None, until=None, patrol_b=None,
         legs={279: ('click', 952, (935, 290), '二区')}),
)

if __name__ == '__main__':
    try:
        if m.t.Client(m.LEADER).world().map_id not in (279, 281):
            pp_chain.main('通天塔', ['平静海岸2区'])
        m.main()
    except m.t.Stop as e:
        m.t.say(f'停止: {e}')
        raise SystemExit(1)
