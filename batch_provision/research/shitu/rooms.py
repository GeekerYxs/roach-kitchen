"""189: the team from 逍遥村 into 通天塔3号房 (297) through 1号房 and 2号房 (元素使 route).

    python -X utf8 research/shitu/rooms.py LEADER MASTER APP ...

Live 2026-11-03 09:02-09:06 (the user showed the way): tower1_go.py into 通天塔一区 280, walk to (756,2186) and on
into 1号房 295 (lands (761,802)); the path-finder cannot target 295 itself (stalled 10x). The quest holder leading
the team (the master gets only the inscription) clicks 石像 1088「传送至2号房」-> 291 (414,597), 石像 1089「传送至
3号房」-> 297 (582,759); the whole team goes along.
"""
import math
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
    import os
    # 2026-11-07 (the r4ys25 books loop): on a rerun only who still lacks the 第五元素 needs 3号房, and the leader must be
    # one of them (a quest holder clicks the 石像; one that handed in may get only the inscription, like the master)
    import fifth
    from provisioner import world as w
    todo = [n for n in apps if not fifth.handed_in(t.Client(n)) and not w.item_count(w.read_bag(t.Client(n).mem), fifth.ITEM)]
    if not todo:
        t.say('每个徒弟都已有第五元素或已交，不用去 3号房')
        return
    if leader not in todo:
        t.say(f'{leader} 已有第五元素或已交，改由 {todo[0]} 带队进 3号房')
        leader = todo[0]
    m = t.Client(master)
    if m.world().map_id not in (280, 295, 291, 297):
        run('tower1_go.py')               # the master takes the team into 通天塔一区 (its landing spot)
    lead = t.Client(leader)
    # user 2026-11-03: the quest holder leads from here on. 2nd run: with the master leading, the team stopped on the
    # door itself, the master stepped into 1号房 alone and the apprentice could not regroup with it (two maps).
    # So the apprentice takes the lead at the landing and walks the team (master following and casting) in.
    if lead.world().map_id == 280:
        boss_fight.lead_team(lead, [m] + [t.Client(n) for n in apps if n != leader])
        env = dict(os.environ, SHITU_LEADER=leader)
        subprocess.run([sys.executable, '-X', 'utf8', 'go_goal.py', '280', '280', *map(str, DOOR)], check=True, env=env)
        lead.game.navigate(280, *STEP_IN)
        t.wait(lambda: lead.world().map_id == 295, 30, '走进 1号房')
        time.sleep(1.5)
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
