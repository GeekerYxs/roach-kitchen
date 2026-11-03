"""187 step 7: the 女神奖杯 from 死鸟人 in 葵花魔穴 (800), for every apprentice (元素使 route).

    python -X utf8 research/shitu/bird.py MASTER APP ...          (the team stands in 龙之都外城, 187 at step 7)

Live 2026-11-03 01:02-01:14: 奥里雷西亚「我可以帮你传送到死鸟人的地盘」sends one role at a time (a team leader gets
「只允许单人传送,请先解散队伍」), so every apprentice talks to her alone (team_npc, words 术士的试炼|现在就走) and lands at
800 (7750,1400), 67 px from 死鸟人. The master walks: 142 entrance NPC 10168 (3165,2244, a click sends it in, no
dialog) -> 800 (642,2853) -> 死鸟人 (master_go.py, ~2.5 min). Then the first apprentice leads the team, 「术士的试炼
［进行中］」->「来吧，你个死鸟人！」, one battle (~20 s) gives every member a 女神奖杯 (10718).
"""
import subprocess
import sys

import boss_fight
import trial_run as t
from provisioner import world as w

TROPHY, BIRD, BIRD_XY = 10718, 1131, (7734, 1380)


def run(script, *args):
    subprocess.run([sys.executable, '-X', 'utf8', script, *map(str, args)], check=True)


def main(master, apps):
    left = [n for n in apps if t.Client(n).world().map_id != 800]
    if left:
        run('team_npc.py', 20, 633, 3064, 1964, '术士的试炼|现在就走', 187, master, *left, '--no-regroup')
    if t.Client(master).world().map_id != 800:
        run('master_go.py', master, 142, 3165, 2290, 10168, '*', 800, *BIRD_XY)
    lacking = [n for n in apps if not w.item_count(w.read_bag(t.Client(n).mem), TROPHY)]
    if lacking and not boss_fight.fight(lacking[0], BIRD, ['术士的试炼', '死鸟人'], master, apps):
        raise t.Stop('死鸟人没打起来')
    got = {n: w.item_count(w.read_bag(t.Client(n).mem), TROPHY) for n in apps}
    t.say(f'女神奖杯 {got}')
    if not all(got.values()):
        raise t.Stop(f'有人没拿到女神奖杯: {got}')


if __name__ == '__main__':
    try:
        main(sys.argv[1], sys.argv[2:])
    except (t.Stop, subprocess.CalledProcessError) as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
