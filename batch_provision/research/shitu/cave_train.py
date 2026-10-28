"""遗忘洞穴 (map 750, upper part) leveling until every apprentice reaches LEVEL (user's route 2026-10-28: 25–30).

    python -X utf8 research/shitu/cave_train.py LEVEL

maze_train's loop (SHITU_MASTERS leader casts, talent -> 体质). From 龙之都外城 (20) as go_cave.py: 20 -> 141 ->
entrance NPC 10166 -> 750 landing (1590,3369); patrol landing <-> 遗忘之花 4183 (1946,2430) (both reached by the
path-finder when gathering, round 1/3); in the 二层 (after gathering 暗花) two lower flowers instead. Stops in 750.
"""
import sys

import maze_train as m

UPPER = ((1590, 3369), (1946, 2430))
LOWER = ((2835, 6146), (3686, 6682))   # 二层 (y > 4000; the two layers are not connected on foot): two 暗·遗忘之花
                                      # the leader reached while gathering (round 4 00:25)
st = m.t.Client(m.LEADER).world()
a, b = LOWER if st.map_id == 750 and st.y > 4000 else UPPER
m.STAGES = (
    dict(name='遗忘洞穴', maze=750, until=int(sys.argv[1]), patrol_a=a, patrol_b=b,
         legs={20: ('walk', 141, (3410, 252)), 141: ('click', 10166, (3410, 252))}),
)

if __name__ == '__main__':
    try:
        m.main()
    except m.t.Stop as e:
        m.t.say(f'停止: {e}')
        raise SystemExit(1)
