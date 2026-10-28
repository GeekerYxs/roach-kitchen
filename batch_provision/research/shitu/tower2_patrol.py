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

def run():
    """Round 4 (user 2026-10-28): when the 地瓜 double runs out, break off, everybody home, 散福老人 3 小时
    (r4_util.double), back to 281 (tower2_go) and patrol on. Round 5: once the 3 小时 is used up, a 加钙地瓜 is eaten
    right where they stand (r4_util.yam_due) and the patrol goes on, no trip home."""
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
        m.STOP_AT = r4_util.stop_at(r4_util.double_due(), r4_util.yam_due())
        m.main()
        if not target or min(w.read_level(m.t.Client(n).mem) for n in m.APPRENTICES) >= target:
            return
        if not r4_util.double_due() or r4_util.double_due() > m.time.time() + 60:
            r4_util.double()           # only yams are due: eat in place and patrol on
            continue
        r4_util.home()
        r4_util.double()
        subprocess.run([sys.executable, '-X', 'utf8', 'tower2_go.py'], check=True)


if __name__ == '__main__':
    try:
        run()
    except m.t.Stop as e:
        m.t.say(f'停止: {e}')
        raise SystemExit(1)
