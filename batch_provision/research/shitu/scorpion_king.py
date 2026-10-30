"""Task 183 step 6: challenge 蝎子王邪爪 (NPC 1127, 巨石之城西部遗址 1000 (2682,3285)) with an apprentice as team leader
(user 17:5x: 「由任一队员做队长，发起挑战就行了」 — the boss told the master 伏地魔1 「走开，我要找的是杀死我徒子徒孙的…」).

    python -X utf8 research/shitu/scorpion_king.py LEADER MEMBER ...      e.g. 千万1 伏地魔1 千万2 千万3 千万4

Everybody leaves the old team, the apprentice leader re-forms it (teamwalk.regroup), clicks 1127 and takes the challenge
option (or the only one); in the battle every team member acts (lunhui15.Caster: the master's 扫射 + pet, the
apprentices' 普攻). Afterwards prints each one's 蝎爪 count and task 183 steps.
"""
import sys
import time

import boss_quiz
import teamwalk as d
import trial_run as t
from lunhui15 import Caster
from provisioner import world as w
from factory.items import load_items

BOSS, XY = 1127, (2682, 3285)


def main(leader, members):
    d.MAP = 1000
    items = load_items()
    claw = [i for i, x in items.items() if x.name == '蝎爪']
    lead = t.Client(leader)
    cs = [t.Client(n) for n in members]
    for c in [lead] + cs:
        if c.team():
            c.game.team_leave()
            t.wait(lambda: not c.team(), 5, f'{c.name} 离队')
    import r4_util
    from common import APPRENTICES
    apps = [c for c in [lead] + cs if c.name in APPRENTICES]
    claws = lambda c: sum(w.item_count(w.read_bag(c.mem), i) for i in claw)
    # 2026-10-28 team C: only 亿万11 got a 蝎爪, the other three had full bags; clear room, fight again for the rest
    everyone = [lead] + cs
    for round_ in range(1, 4):
        for c in apps:
            r4_util.space_one(c, 2)
        # 2026-10-28 team B: the boss says 走开 to a leader that already holds a 蝎爪; lead with one still short of it
        short = [c for c in apps if not claws(c) and len(w.read_quest(c.mem, 183).steps) == 6]
        if short and short[0] is not lead:
            for c in everyone:
                if c.team():
                    c.game.team_leave()
                    t.wait(lambda: not c.team(), 5, f'{c.name} 离队')
            lead = short[0]
            leader = lead.name
            t.say(f'第 {round_} 次: {leader} 当队长（还没蝎爪）')
        cs = [c for c in everyone if c is not lead]
        d.regroup(lead, cs)
        fight(lead, cs, leader)
        for c in [lead] + cs:
            t.say(f'[{c.name}] 蝎爪 {claws(c)}；183 {w.read_quest(c.mem, 183).steps}；地图 {c.world().map_id}')
        short = [c.name for c in apps if not claws(c) and len(w.read_quest(c.mem, 183).steps) == 6]
        if not short:
            return
        t.say(f'第 {round_} 次打完还没有蝎爪: {short}，再打一次')
    raise t.Stop(f'打了 3 次蝎子王还有人没蝎爪: {short}')


def fight(lead, cs, leader):
    for attempt in range(1, 5):
        if not lead.dialog():
            lead.game.click_npc(BOSS)
        dlg = t.wait(lambda: lead.dialog(), 5, f'{leader} 蝎子王')
        # 17:57 live: 「就是你这个家伙在我的地盘上捣乱吗！」 是的！ -> 「单挑，群殴，由你选！」 单挑 / 群殴 -> 群殴 (whole team)
        for _ in range(4):
            opts = [(o, t.plain(l)) for o, l in dlg.options if o]
            t.say(f'[{leader}] 蝎子王: {t.body(dlg)[:60]} {opts}')
            pick = next((o for o, l in opts if '群殴' in l), None) or (opts[0][0] if len(opts) == 1 else None)
            if pick is None:
                lead.game.select_dialog(0)
                raise t.Stop(f'蝎子王对话不认识: {opts}')
            prev = dlg.text
            lead.game.select_dialog(pick)
            time.sleep(1)
            if lead.world().in_battle:
                break
            dlg = lead.dialog()
            if not dlg or dlg.text == prev:
                break
        end = time.monotonic() + 10
        while time.monotonic() < end and not lead.world().in_battle and not lead.world().verification:
            time.sleep(0.2)
        if lead.world().in_battle:
            break
        # 开战被换成了 boss 答题 0x46f5：答题器（静默）或 boss_quiz 自己答掉，然后重新点蝎子王
        if boss_quiz.solve(lead, say=t.say) is None:
            raise t.Stop(f'第 {attempt} 次没进战斗，也没有 boss 答题面板')
        t.wait(lambda: not getattr(lead.world(), 'verification', False), 120, '答题结束')
        if boss_quiz.kicked(lead):       # 答错 = 服务器踢下线：退出，产线重登后整步重跑（再开打、再答）
            raise t.Stop(f'[{leader}] boss 题答错被服务器踢下线，交给产线重登后重跑这一步')
        time.sleep(1)
    else:
        raise t.Stop('点了 4 次蝎子王都没进战斗')
    t0 = time.monotonic()
    casters = {c.name: Caster(c) for c in [lead] + cs}
    while lead.world().in_battle and time.monotonic() - t0 < 300:
        now = time.monotonic()
        for c in [lead] + cs:
            if c.world().in_battle:
                casters[c.name].tick(now)
        time.sleep(0.15)
    t.say(f'战斗结束 {time.monotonic() - t0:.0f}s')
    time.sleep(1.5)


if __name__ == '__main__':
    try:
        main(sys.argv[1], sys.argv[2:])
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
