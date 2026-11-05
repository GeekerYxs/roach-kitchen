"""An apprentice leads the whole team (master + the others), talks an NPC into a fight, the master fights it out.

    python -X utf8 research/shitu/boss_fight.py LEADER NPC WORD[|WORD...] MASTER APP ...

元素使 route (2026-11-03): 死鸟人 1131 (187, 女神奖杯) and 土拨鼠 1133 (189, 土之微尘) are talked into a fight by a
quest holder; only a team's leader can talk to NPCs, so LEADER (an apprentice) leads and the master (a member) casts
and revives (lunhui15.Caster). On every page an option holding one of the words is picked (team_npc's rule).
-> exit 0 once a battle was fought, 1 when no battle came (e.g. the 土拨鼠 is back only ~4.5 min after a fight).
"""
import sys
import time

import trial_run as t
from lunhui15 import Caster
from well10 import form_team

TALK_WAIT, FIGHT_WAIT = 20, 240


def lead_team(lead, others):
    if not (lead.team() and lead.team()[0] == lead.char_id and len(lead.team()) == 1 + len(others)):
        for c in [lead] + others:
            if c.dialog():
                c.game.select_dialog(0)
            if c.team():
                c.game.team_leave()
        time.sleep(1.5)
        form_team(lead, others)


def fight(leader, npc, words, master, apps):
    lead, m = t.Client(leader), t.Client(master)
    lead_team(lead, [m] + [t.Client(n) for n in apps if n != leader])
    caster = Caster(m)
    if lead.dialog():
        lead.game.select_dialog(0)
        time.sleep(0.3)
    lead.game.click_npc(npc)
    try:
        t.wait(lambda: lead.dialog(), 5, f'NPC {npc}')
    except t.Stop:
        return False
    last, end = None, time.monotonic() + TALK_WAIT
    while time.monotonic() < end and not lead.world().in_battle:
        d = lead.dialog()
        if d and d.text + str(d.options) != last:
            hit = [(o, l) for o, l in d.options if o and any(wd in t.plain(l) for wd in words)]
            if not hit:
                t.say(f'[{leader}] NPC {npc} 没有要的选项: {t.body(d)[:60]} {d.options}')
                lead.game.select_dialog(0)
                return False
            last = d.text + str(d.options)
            lead.game.select_dialog(hit[0][0])
        time.sleep(0.3)
    end, started = time.monotonic() + FIGHT_WAIT, False
    while time.monotonic() < end:
        if m.world().in_battle:
            started = True
            caster.tick(time.monotonic())
        elif started:
            break
        time.sleep(0.03 if started else 0.15)  # lunhui15.BATTLE_TICK while fighting (user 2026-11-05)
    time.sleep(2)
    t.say(f'[{leader}] NPC {npc} 战斗{"打完" if started else "没开始"}')
    return started


if __name__ == '__main__':
    a = sys.argv[1:]
    try:
        ok = fight(a[0], int(a[1]), a[2].split('|'), a[3], a[4:])
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
    raise SystemExit(0 if ok else 1)
