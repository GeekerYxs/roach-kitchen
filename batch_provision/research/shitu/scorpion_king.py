"""Task 183 step 6: challenge 蝎子王邪爪 (NPC 1127, 巨石之城西部遗址 1000 (2682,3285)) with an apprentice as team leader
(user 17:5x: 「由任一队员做队长，发起挑战就行了」 — the boss told the master 伏地魔1 「走开，我要找的是杀死我徒子徒孙的…」).

    python -X utf8 research/shitu/scorpion_king.py LEADER MEMBER ...      e.g. 千万1 伏地魔1 千万2 千万3 千万4

Everybody leaves the old team, the apprentice leader re-forms it (teamwalk.regroup), clicks 1127 and takes the challenge
option (or the only one); in the battle every team member acts (lunhui15.Caster: the master's 扫射 + pet, the
apprentices' 普攻). Afterwards prints each one's 蝎爪 count and task 183 steps.
"""
import sys
import time

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
    d.regroup(lead, cs)
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
    t.wait(lambda: lead.world().in_battle, 10, '进入战斗')
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
    for c in [lead] + cs:
        b = w.read_bag(c.mem)
        t.say(f'[{c.name}] 蝎爪 {sum(w.item_count(b, i) for i in claw)}；183 {w.read_quest(c.mem, 183).steps}；地图 {c.world().map_id}')


if __name__ == '__main__':
    try:
        main(sys.argv[1], sys.argv[2:])
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
