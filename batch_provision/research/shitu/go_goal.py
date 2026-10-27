"""Team per SHITU_MASTERS walks from map FROM to (X, Y) on map TO and stops there (maze_train goal stage, leader casts).

    python -X utf8 research/shitu/go_goal.py FROM TO X Y

Round 3 task 181: 龙之都外城 20 -> 无尽平原3区 142 树 (678,1977), etc.
"""
import sys

import maze_train as m

src, dst, x, y = map(int, sys.argv[1:5])
m.STAGES = (
    dict(name=f'地图 {dst} ({x},{y})', goal=(dst, (x, y)), maze=None, until=None, patrol_b=None,
         legs={src: ('walk', dst, (x, y))}),
)

if __name__ == '__main__':
    try:
        m.main()
    except m.t.Stop as e:
        m.t.say(f'停止: {e}')
        raise SystemExit(1)
