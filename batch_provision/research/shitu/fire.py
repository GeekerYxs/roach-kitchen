"""189: the 火之烈焰 (10722) from 火蜥蜴, for every apprentice (元素使 route).

    python -X utf8 research/shitu/fire.py MASTER APP ...           (the team in 龙之都外城 or 苦无沙漠1区 170)

Live 2026-11-03 01:25-01:31: 火蜥蜴 2203 at 170 (258,471) (desert_go.py): 元素使的考验 -> 呃，你能给我火之烈焰吗？
-> (咦…火焰) -> 好吧，我去找果肉跟你换。 Then 5 仙人掌果肉 (10723, team-wide drops from 小帅哥仙人掌 around 170
(2454,1839)) buy one random thing:「给予5个仙人掌果肉」-> e.g. 木材 or the 火之烈焰. Loop: farm 5 果肉 for those still
without fire, walk back, give; up to ROUNDS times.
"""
import subprocess
import sys

import trial_run as t
from provisioner import world as w

FIRE, FRUIT, ROUNDS = 10722, 10723, 6
NPC, XY, FIELD = 2203, (258, 471), (2454, 1839)
WORDS = '元素使|火之烈焰|火焰|果肉|再见'


def run(script, *args, env=None):
    subprocess.run([sys.executable, '-X', 'utf8', script, *map(str, args)], check=True, env=env)


def main(master, apps):
    import os
    has = lambda n: w.item_count(w.read_bag(t.Client(n).mem), FIRE)     # noqa: E731
    if t.Client(master).world().map_id != 170:
        run('desert_go.py', *XY)
    run('team_npc.py', 170, NPC, *XY, WORDS, 189, master, *apps, '--no-regroup')
    for k in range(ROUNDS):
        lacking = [n for n in apps if not has(n)]
        if not lacking:
            t.say(f'火之烈焰 全员都有（{k} 轮）')
            return
        env = dict(os.environ, SHITU_APPRENTICES=','.join(lacking))
        run('farm.py', '--stay', 170, *FIELD, FRUIT, 5, env=env)
        run('go_goal.py', 170, 170, *XY, env=env)
        run('team_npc.py', 170, NPC, *XY, WORDS, 189, master, *lacking, '--no-regroup')
        t.say(f'第 {k + 1} 轮：' + ' '.join(f'{n} {has(n)}' for n in apps))
    raise t.Stop(f'{ROUNDS} 轮后还没有火之烈焰: {[n for n in apps if not has(n)]}')


if __name__ == '__main__':
    try:
        main(sys.argv[1], sys.argv[2:])
    except (t.Stop, subprocess.CalledProcessError) as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
