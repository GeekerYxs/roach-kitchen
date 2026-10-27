"""通天塔一区 (map 280) leveling: patrol the landing point (414,4893) <-> (106,4467) (user, 2026-10-27) until every
apprentice is 28. maze_train's loop: 伏地魔1 leader, 扫射 + 烈焰爆发, talent -> 体质; stops in 280.

    python -X utf8 research/shitu/tower28.py [target level, default 28]
"""
import sys

import maze_train as m

m.STAGES = (
    dict(name='通天塔一区', maze=280, until=int(sys.argv[1]) if len(sys.argv) > 1 else 28,
         patrol_a=(414, 4893), patrol_b=(106, 4467),
         legs={279: ('click', 952, (935, 290))}),    # 通天塔门: first option = 到通天塔一区 (round 1, 02:18)
)

if __name__ == '__main__':
    try:
        m.main()
    except m.t.Stop as e:
        m.t.say(f'停止: {e}')
        raise SystemExit(1)
