"""Task 183 step 2: put the 5 蝎子药 (10687) at 5 水源 in 苦无沙漠1区 (170), master leading (user 17:2x).

    python -X utf8 research/shitu/scorpion_water.py MASTER 千万1 千万2 ...

Same pattern as dew_team.py, helpers in teamwalk.py (通天塔 花露): the leader walks to each 水源 (casting in battles) and OVER px past it so the
trailing members stand next to it; every member still holding 蝎子药 leaves the team, clicks the 水源 and takes its one
two dialog layers (「勇者的考验［进行中］」 ->「哈，是这里没错，投放蝎子药」, 17:25 live), then everybody re-joins (teamwalk.regroup: walk onto the leader, invite, accept 1.5 s later).
A placement counts when the member's 蝎子药 count drops. 水源 NPCDirection.csv 967-973; the five used, nearest first
from 营长孙大胜 (1890,567): 971 (2010,1317), 968 (1650,2205), 967 (2718,1521), 972 (3162,1054), 973 (3858,1725).
"""
import sys

import teamwalk as d
import trial_run as t
from lunhui15 import Caster
from provisioner import world as w

d.MAP = 170
POTION = 10687
SOURCES = ((971, (2010, 1317)), (968, (1650, 2205)), (967, (2718, 1521)), (972, (3162, 1054)), (973, (3858, 1725)),
           (969, (354, 1809)), (970, (162, 963)))


def potions(c):
    return w.item_count(w.read_bag(c.mem), POTION)


def place(c, npc, xy):
    """One member at one 水源. -> True when a 蝎子药 was used up."""
    d.step_to(c, xy)
    before = potions(c)
    c.game.click_npc(npc)
    try:
        dlg = t.wait(lambda: c.dialog(), 5, f'{c.name} 水源 {npc}')
    except t.Stop:
        d.step_to(c, xy, near=30)
        c.game.click_npc(npc)
        dlg = t.wait(lambda: c.dialog(), 5, f'{c.name} 水源 {npc}（走近后）')
    for _ in range(3):         # 17:25 live: 「勇者的考验［进行中］」 first, then「哈，是这里没错，投放蝎子药」
        opts = [(o, t.plain(l)) for o, l in dlg.options if o]
        if not opts:
            t.say(f'[{c.name}] 水源 {npc}: {t.body(dlg)[:60]}（没有选项）')
            c.game.select_dialog(0)
            return False
        pick = next((o for o, l in opts if '投放' in l), None)
        if pick is not None:
            break
        nxt = next((o for o, l in opts if '勇者' in l), opts[0][0] if len(opts) == 1 else None)
        if nxt is None:
            c.game.select_dialog(0)
            raise t.Stop(f'{c.name} 水源 {npc} 选项不认识: {opts}')
        prev = dlg.text
        c.game.select_dialog(nxt)
        dlg = t.wait(lambda: (x := c.dialog()) and x.text != prev and x, 5, f'{c.name} 水源 {npc} 下一层')
    else:
        c.game.select_dialog(0)
        raise t.Stop(f'{c.name} 水源 {npc} 三层都没有「投放」')
    c.game.select_dialog(pick)
    try:
        t.wait(lambda: potions(c) < before, 5, f'{c.name} 蝎子药 -1')
    except t.Stop:
        t.say(f'[{c.name}] 水源 {npc} 投放后蝎子药没少（{before}）')
        return False
    if c.dialog():
        c.game.select_dialog(0)
    return True


def main(master, names):
    lead = t.Client(master)
    apps = {n: t.Client(n) for n in names}
    caster = Caster(lead)
    st = lead.world()
    lead.came_from = (round(st.x), round(st.y))
    d.regroup(lead, list(apps.values()))
    for npc, xy in SOURCES:
        need = [n for n, c in apps.items() if potions(c) > 0]
        if not need:
            break
        d.lead_to(lead, caster, xy)
        d.past(lead, caster, xy)
        for n in need:
            c = apps[n]
            c.game.team_leave()
            t.wait(lambda: not c.team(), 5, f'{n} 离队')
        for n in need:
            ok = place(apps[n], npc, xy)
            t.say(f'[{n}] 水源 {npc}: {"放好" if ok else "没放上"}，还剩 {potions(apps[n])} 瓶')
        d.regroup(lead, list(apps.values()))
    left = {n: potions(c) for n, c in apps.items()}
    q = {n: w.read_quest(c.mem, 183).steps for n, c in apps.items()}
    t.say(f'剩余蝎子药 {left}；183 {q}')


if __name__ == '__main__':
    master, *names = sys.argv[1:]
    try:
        main(master, names)
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
