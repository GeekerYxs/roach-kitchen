"""通天塔二区 (map 281): patrol (600,500) <-> (1200,400) (user, round 3 12:4x; first pair (562,249) <-> (1207,162) stalled) until stopped; an apprentice dying in a
battle stops the run after that battle (maze_train fallen check), as does a member leaving the team.

    python -X utf8 research/shitu/tower2_patrol.py [target level]      (user 12:3x: 40; none = until stopped)

maze_train's loop: SHITU_MASTERS leader casts 扫射 + 烈焰爆发, talent -> 体质, apprentices send nothing.
"""
import sys

import maze_train as m

m.STAGES = (
    dict(name='通天塔二区巡逻', maze=281, until=int(sys.argv[1]) if len(sys.argv) > 1 else None, patrol_a=(600, 500), patrol_b=(1200, 400), legs={}),
)

if __name__ == '__main__':
    try:
        m.main()
    except m.t.Stop as e:
        m.t.say(f'停止: {e}')
        raise SystemExit(1)
