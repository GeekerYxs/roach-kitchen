"""Research helper (2026-11-06, 老树叶 quest 673): log the team's state, optionally click one NPC (raw 0x50, no
walking) and pick options by word, logging every page.

    python -X utf8 probe_leaf.py                       (state only)
    python -X utf8 probe_leaf.py <npc id> [word ...]   (click, then pick the option holding each word in turn)
    python -X utf8 probe_leaf.py - [word ...]          (the dialog already open: just pick)
    PROBE_QUEST=518 python -X utf8 probe_leaf.py ...   (another quest's steps; 2026-11-06 金刚猴)
"""
import os
import sys
import time

from _bootstrap import ROLES

import trial_run as t
from eagle_cage import click
from provisioner import world as w

QUEST = int(os.environ.get("PROBE_QUEST", "673"))
ITEMS = {11173: "拜山帖", 11169: "老树根", 11172: "老树叶", 11026: "传送石", 11040: "传送石b",
         11170: "定土神针", 11171: "鲜花铠甲",
         11162: "守护者白旗", 11163: "守卫者白旗", 11175: "1号通行证", 11176: "2号通行证"}


def report(cs, why):
    for c in cs:
        s = c.world()
        bag = w.read_bag(c.mem) or ()
        got = {ITEMS[b.item_id]: b.quantity for b in bag if b.item_id in ITEMS}
        q = w.read_quest(c.mem, QUEST)
        t.say(f'{why} [{c.name}] map {s.map_id} ({s.x:.0f},{s.y:.0f}) 战斗 {s.in_battle} 物品 {got} '
              f'任务 {q.steps if q and q.active else None} 队伍 {len(c.team())}')


def show(c):
    d = c.dialog()
    if d:
        t.say(f'对话: {t.plain(d.text)}')
        t.say(f'选项: {[(o, t.plain(l)) for o, l in d.options]}')
    else:
        t.say('没有对话框')
    return d


def main(argv):
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    report(cs, '之前')
    if not argv:
        return
    if argv[0] != '-':                        # '-' = go on with the dialog already open
        click(lead, int(argv[0]))
        time.sleep(1.5)
    d = show(lead)
    for word in argv[1:]:
        if d is None:
            break
        opt = next((o for o, l in d.options if word in t.plain(l)), None)
        if opt is None:
            t.say(f'没有「{word}」，停')
            break
        before = d.text
        lead.game.select_dialog(opt)
        end = time.monotonic() + 5
        while time.monotonic() < end and not lead.world().in_battle:
            if (x := lead.dialog()) is None or x.text != before:
                break
            time.sleep(0.2)
        time.sleep(0.8)
        t.say(f'--- 选了「{word}」')
        d = show(lead)
    time.sleep(1)
    report(cs, '之后')


if __name__ == '__main__':
    main(sys.argv[1:])
