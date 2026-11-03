"""Team per SHITU_MASTERS walks from map FROM to (X, Y) on map TO and stops there (maze_train goal stage, leader casts).

    python -X utf8 research/shitu/go_goal.py FROM TO X Y [VIA_MAP ...]

Round 3 task 181: 龙之都外城 20 -> 无尽平原3区 142 树 (678,1977), etc.
"""
import sys

import maze_train as m

# extra args = maps the path-finder crosses on the way (2026-11-03: 苦无沙漠1区 170 -> 141 -> 142 -> 迷惑森林1区 150
# stopped on「在意外的地图 141」): every one of them walks on to the goal as well
src, dst, x, y, *via = map(int, sys.argv[1:])
m.STAGES = (
    dict(name=f'地图 {dst} ({x},{y})', goal=(dst, (x, y)), maze=None, until=None, patrol_b=None,
         legs={k: ('walk', dst, (x, y)) for k in (src, *via)}),
)

if __name__ == '__main__':
    try:
        m.main()
    except m.t.Stop as e:
        m.t.say(f'停止: {e}')
        raise SystemExit(1)
