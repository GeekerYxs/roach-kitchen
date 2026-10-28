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

def run():
    """Round 4 (user 2026-10-28): when the double runs out, break off, everybody home, 散福老人 3 小时 or one 地瓜
    (r4_util.double), back to 通天塔一区 (pp_chain + the 952 door) and patrol on."""
    import os
    import subprocess
    if not os.environ.get('SHITU_STATE', '').startswith('state_r4'):
        return m.main()
    stages = m.STAGES
    import r4_util                     # imports quanshou, which overwrites maze_train.STAGES at import time
    m.STAGES = stages
    from provisioner import world as w
    target = m.STAGES[0]['until']
    while True:
        m.STOP_AT = r4_util.double_due()
        m.main()
        if min(w.read_level(m.t.Client(n).mem) for n in m.APPRENTICES) >= target:
            return
        r4_util.home()
        r4_util.double()
        subprocess.run([sys.executable, '-X', 'utf8', 'pp_chain.py', '通天塔', '平静海岸2区'], check=True)


if __name__ == '__main__':
    try:
        run()
    except m.t.Stop as e:
        m.t.say(f'停止: {e}')
        raise SystemExit(1)
