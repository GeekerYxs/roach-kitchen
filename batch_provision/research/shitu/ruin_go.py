"""Task 183 step 4: team per SHITU_MASTERS from 恶人山 (50) into 巨石之城西部遗址 (1000) up to a spot there
(default 黑暗灵柩 NPC 1002 (2796,1836): no NPC named 侦察兵 on map 1000 in NPCDirection.csv; 蝎子王邪爪 1127 is at
(2682,3285)). Leader casts (maze_train goal stage).

    python -X utf8 research/shitu/ruin_go.py [X Y]

Route (AutoPath.csv): 恶人山 50 -> 苦无沙漠1区 170 (east link at 170 (4116,3060)) -> 遗址 entrance NPC 10176 at 170
(3068,192) -> 1000 (back exit 10175 at (5172,5340)).
"""
import sys

import maze_train as m

SPOT = tuple(map(int, sys.argv[1:3])) if len(sys.argv) > 2 else (2796, 1836)
m.STAGES = (
    dict(name='巨石之城西部遗址', goal=(1000, SPOT), maze=None, until=None, patrol_b=None,
         legs={50: ('walk', 170, (3068, 192)),
               170: ('click', 10176, (3068, 192))}),
)

if __name__ == '__main__':
    try:
        m.main()
    except m.t.Stop as e:
        m.t.say(f'停止: {e}')
        raise SystemExit(1)
