"""Master-led NPC talk in a wild map (round 3, task 183): the team is already next to the NPC; every member leaves the
team, steps up to it (teamwalk.step_to, a battle on the way -> run away), clicks it, picks the option holding WORD
(e.g. 勇者 for「勇者的考验［进行中］」; several words joined by |, also used at later choices), then takes the single
non-离开 option while there is one; stops on any other choice and prints it. Then everybody re-joins (teamwalk.regroup).

    python -X utf8 research/shitu/team_npc.py MAP NPC X Y WORD QID MASTER 千万1 千万2 ...

183 step 4 (17:4x): the 侦察兵 is「一具尸体」NPC 966 at 巨石之城西部遗址 1000 (3030,4569) — only in the server's 0x40a0
spawn list, not in NPCDirection.csv (the user pointed at it). Its dialog: 这会是那个侦察兵吗？ -> 掰开他紧握的手指看看 ->
choice 给你唱段安魂曲吧 / 我再掰 -> (安魂曲) 指节松开，露出一份带血的情报 -> 阿弥托佛，拾取情报 (needs a free bag slot:
千万1 got「物品栏已满！」). WORD = 勇者|安魂曲|拾取.
"""
import sys
import time

import teamwalk as d
import trial_run as t
from provisioner import world as w


def talk(c, npc, xy, word, qid):
    d.step_to(c, xy, near=80)
    before = w.read_quest(c.mem, qid)
    c.game.click_npc(npc)
    try:
        dlg = t.wait(lambda: c.dialog(), 5, f'{c.name} NPC {npc}')
    except t.Stop:
        d.step_to(c, xy, near=30)
        c.game.click_npc(npc)
        dlg = t.wait(lambda: c.dialog(), 5, f'{c.name} NPC {npc}（走近后）')
    seen = []
    for _ in range(10):
        opts = [(o, t.plain(l)) for o, l in dlg.options if o]
        hit = [(o, l) for o, l in opts if any(k in l for k in word.split('|'))]
        if not hit and len(opts) == 1:
            hit = opts
        if not hit:
            if opts:
                t.say(f'[{c.name}] 停在选择: {t.body(dlg)[:100]} {opts}')
            break
        o, l = hit[0]
        seen.append(l)
        prev = dlg.text
        c.game.select_dialog(o)
        time.sleep(0.8)
        dlg = c.dialog()
        if not dlg or dlg.text == prev:
            break
        t.say(f'[{c.name}] {t.body(dlg)[:120]}')
    t.say(f'[{c.name}] 选了 {seen}；{qid} {before.steps} -> {w.read_quest(c.mem, qid).steps}')


def main(map_id, npc, xy, word, qid, master, names):
    d.MAP = map_id
    lead = t.Client(master)
    apps = [t.Client(n) for n in names]
    for c in apps:
        if c.team():
            c.game.team_leave()
            t.wait(lambda: not c.team(), 5, f'{c.name} 离队')
    for c in apps:
        talk(c, npc, xy, word, qid)
    d.regroup(lead, apps)


if __name__ == '__main__':
    a = sys.argv[1:]
    try:
        main(int(a[0]), int(a[1]), (int(a[2]), int(a[3])), a[4], int(a[5]), a[6], a[7:])
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
