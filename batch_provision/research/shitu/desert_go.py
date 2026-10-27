"""Team per SHITU_MASTERS: 龙之都外城 20 -> 无尽平原2区 141 -> 苦无沙漠1区 170 to a spot (default 营长孙大胜 2202
(1890,567), task 183 step 1), leader casts (maze_train goal stage).

    python -X utf8 research/shitu/desert_go.py [X Y]

AutoPath.csv: 20 -> 141 across the link 10192 (396,2976); 141 -> 170 across 10035 (794,3092); 恶人山 50 -> 170 across
10065 (72,2040) (user: PP鸡 to 恶人山 instead of walking from 龙之都).
"""
import sys

import maze_train as m

SPOT = tuple(map(int, sys.argv[1:3])) if len(sys.argv) > 2 else (1890, 567)
m.STAGES = (
    dict(name='苦无沙漠1区', goal=(170, SPOT), maze=None, until=None, patrol_b=None,
         legs={20: ('walk', 141, (794, 3092)),
               141: ('walk', 170, SPOT),
               50: ('walk', 170, SPOT)}),         # 恶人山 (PP鸡 from 龙之都, user 17:2x) -> exit 10065 (72,2040) -> 170
)

if __name__ == '__main__':
    try:
        m.main()
    except m.t.Stop as e:
        m.t.say(f'停止: {e}')
        raise SystemExit(1)
