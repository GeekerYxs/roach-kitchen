"""Master-led NPC talk in a wild map (round 3, task 183): the team is already next to the NPC; every member leaves the
team, steps up to it (teamwalk.step_to, a battle on the way -> run away), clicks it, picks the option holding WORD
(e.g. 勇者 for「勇者的考验［进行中］」; several words joined by |, also used at later choices), then takes the single
non-离开 option while there is one; stops on any other choice and prints it. Then everybody re-joins (teamwalk.regroup).

    python -X utf8 research/shitu/team_npc.py MAP NPC X Y WORD QID MASTER 千万1 千万2 ... [--no-regroup]
    --no-regroup: leave the team apart afterwards (the caller scrolls everybody home next)

183 step 4 (17:4x): the 侦察兵 is「一具尸体」NPC 966 at 巨石之城西部遗址 1000 (3030,4569) — only in the server's 0x40a0
spawn list, not in NPCDirection.csv (the user pointed at it). Its dialog: 这会是那个侦察兵吗？ -> 掰开他紧握的手指看看 ->
choice 给你唱段安魂曲吧 / 我再掰 -> (安魂曲) 指节松开，露出一份带血的情报 -> 阿弥托佛，拾取情报 (needs a free bag slot:
千万1 got「物品栏已满！」). WORD = 勇者|安魂曲|拾取.
"""
import os
import sys
import time

import teamwalk as d
import trial_run as t
from provisioner import world as w


def talk(c, npc, xy, word, qid):
    import r4_util
    r4_util.space_one(c, 2)     # the NPC may hand over an item; loot from the walk filled the bag (2026-10-28)
    d.step_to(c, xy, near=80)
    before = w.read_quest(c.mem, qid)
    c.game.click_npc(npc)
    try:
        dlg = t.wait(lambda: c.dialog(), 5, f'{c.name} NPC {npc}')
    except t.Stop:
        if w.read_quest(c.mem, qid).steps != before.steps:      # an object that counts on a plain click, no dialog
            t.say(f'[{c.name}] 点 NPC {npc} 没有对话框，{qid} {before.steps} -> {w.read_quest(c.mem, qid).steps}')
            return
        taps = d._taps(c)
        d.step_to(c, xy, near=30)
        c.game.click_npc(npc)
        try:
            dlg = t.wait(lambda: c.dialog(), 5, f'{c.name} NPC {npc}（走近后）')
        except t.Stop:
            if w.read_quest(c.mem, qid).steps != before.steps:
                t.say(f'[{c.name}] 点 NPC {npc} 没有对话框，{qid} {before.steps} -> {w.read_quest(c.mem, qid).steps}')
                return
            # 2026-10-28 亿万24 (古迹水晶, 尸体) / 亿万28 (水源): the client stood at the NPC, the server had it
            # elsewhere. A path-found walk away and back sends the real position; then click once more.
            t.say(f'[{c.name}] 走近后点 NPC {npc} 还是没对话框（系统提示 {d._texts(taps)}），走开再回来重点')
            c.game.cancel_navigation()
            c.game.navigate(d.MAP, xy[0] + 150, xy[1])
            try:
                t.wait(lambda: not c.world().moving and not c.world().nav_active, 20, f'{c.name} 走开')
            except t.Stop:
                pass
            d.step_to(c, xy, near=30)
            c.game.click_npc(npc)
            dlg = t.wait(lambda: c.dialog(), 5, f'{c.name} NPC {npc}（走开再回来后）')
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


RETRY_PASSES, RETRY_WAIT = 2, 15


def main(map_id, npc, xy, word, qid, master, names, regroup=True):
    d.MAP = map_id
    lead = t.Client(master)
    apps = [t.Client(n) for n in names]
    for c in apps:
        if c.team():
            c.game.team_leave()
            t.wait(lambda: not c.team(), 5, f'{c.name} 离队')
    todo = apps
    for attempt in range(1 + RETRY_PASSES):
        failed = []
        for c in todo:
            try:
                talk(c, npc, xy, word, qid)
            except t.Stop as e:
                failed.append((c, e))
        if not failed:
            break
        if attempt == RETRY_PASSES:
            raise failed[0][1]
        # 2026-10-29: three times in a row (树 亿万52, 水晶 亿万56, 花) the last apprentice got no dialog right after
        # the others had fled a battle there; the step then went home and passed on the rerun. Wait, retry only them
        names = [c.name for c, _ in failed]
        if attempt == RETRY_PASSES - 1 and os.environ.get('PAIRS'):
            # 2026-10-29 亿万56: three passes in a row ignored by NPC 986, only a trip home helped (state on the
            # server side). A relog resets that too and puts it back right here: last pass after a relog
            import r4_util
            t.say(f'{names} 还是点不出对话框，原地关窗重登后再点最后一轮')
            r4_util.relog(os.environ['PAIRS'].split(), names)
        else:
            t.say(f'{names} 点不出对话框（{failed[0][1]}），{RETRY_WAIT} 秒后只给他们再点一轮')
            time.sleep(RETRY_WAIT)
        todo = [t.Client(n) for n in names]
    if regroup:     # --no-regroup: the next command scrolls everybody home, which breaks the team anyway (user 2026-10-28)
        d.regroup(lead, apps)


if __name__ == '__main__':
    a = sys.argv[1:]
    keep = '--no-regroup' not in a
    a = [x for x in a if x != '--no-regroup']
    try:
        main(int(a[0]), int(a[1]), (int(a[2]), int(a[3])), a[4], int(a[5]), a[6], a[7:], regroup=keep)
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
