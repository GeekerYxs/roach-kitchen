"""八阵图 (map 700) leveling until every apprentice is 25 (user's route 2026-10-28: 18–24 八阵图, then 遗忘洞穴 25–30).

    python -X utf8 research/shitu/bazhen25.py [target level, default 25]

maze_train's loop (SHITU_MASTERS leader casts, talent -> 体质) from 平静海岸2区 (81, after pp_chain) on foot
81 -> 82 -> 140 -> 八阵图 entrance NPC 10164; patrol B = maze_train's 八阵图 point. Stops in 700.
"""
import sys

import maze_train as m

m.STAGES = (
    dict(name='八阵图', maze=700, until=int(sys.argv[1]) if len(sys.argv) > 1 else 25, patrol_b=(1200, 1800),
         legs={81: ('walk', 140, (831, 2257)), 82: ('walk', 140, (831, 2257)),
               140: ('click', 10164, (831, 2257))}),
)

if __name__ == '__main__':
    try:
        m.main()
    except m.t.Stop as e:
        m.t.say(f'停止: {e}')
        raise SystemExit(1)
