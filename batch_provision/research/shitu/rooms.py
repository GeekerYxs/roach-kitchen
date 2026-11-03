"""189: the team from 逍遥村 into 通天塔3号房 (297) through 1号房 and 2号房 (元素使 route).

    python -X utf8 research/shitu/rooms.py LEADER MASTER APP ...

Live 2026-11-03 09:02-09:06 (the user showed the way): tower1_go.py into 通天塔一区 280, walk to (756,2186) and on
into 1号房 295 (lands (761,802)); the path-finder cannot target 295 itself (stalled 10x). The quest holder leading
the team (the master gets only the inscription) clicks 石像 1088「传送至2号房」-> 291 (414,597), 石像 1089「传送至
3号房」-> 297 (582,759); the whole team goes along.
"""
import subprocess
import sys
import time

import boss_fight
import trial_run as t

DOOR, STEP_IN = (756, 2186), (777, 2230)
HOPS = ((295, 1088, '传送至2号房', 291), (291, 1089, '传送至3号房', 297))


def run(script, *args):
    subprocess.run([sys.executable, '-X', 'utf8', script, *map(str, args)], check=True)


def main(leader, master, apps):
    m = t.Client(master)
    if m.world().map_id not in (280, 295, 291, 297):
        run('tower1_go.py', 480, 400)
    if m.world().map_id == 280:
        run('go_goal.py', 280, 280, *DOOR)
        m.game.navigate(280, *STEP_IN)
        t.wait(lambda: m.world().map_id == 295, 20, '走进 1号房')
    lead = t.Client(leader)
    boss_fight.lead_team(lead, [m] + [t.Client(n) for n in apps if n != leader])
    for here, npc, word, there in HOPS:
        if lead.world().map_id != here:
            continue
        if lead.dialog():
            lead.game.select_dialog(0)
            time.sleep(0.3)
        lead.game.click_npc(npc)
        d = t.wait(lambda: lead.dialog(), 6, f'石像 {npc}')
        lead.game.select_dialog(t.pick(d, word))
        t.wait(lambda: lead.world().map_id == there, 8, word)
        time.sleep(1.5)
        t.say(f'[{leader}] {word} -> map {there}')
    if lead.world().map_id != 297:
        raise t.Stop(f'没到 3号房: map {lead.world().map_id}')


if __name__ == '__main__':
    try:
        main(sys.argv[1], sys.argv[2], sys.argv[3:])
    except (t.Stop, subprocess.CalledProcessError) as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
