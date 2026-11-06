"""Research helper (2026-11-06, 葵花宝典 quest 475): the leader walks to each given 葵花 NPC in 葵花魔穴 and picks
「将它连根拔起」, logging the menu and what happens.

    python -X utf8 probe_kuihua_pull.py <npc id> ...
"""
import sys
import time

from _bootstrap import ROLES

import kuihua as kh
import probe_kuihua_walk
import trial_run as t
from eagle_cage import click, settle


def pull(lead, npc):
    x, y = kh.FLOWERS[npc]
    probe_kuihua_walk.main(x, y, 20)          # user 2026-11-06: from 250 px the game said「距离太远」
    settle(lead)
    click(lead, npc)
    try:
        d = t.wait(lambda: lead.dialog(), 5, f'葵花 {npc} 菜单')
    except t.Stop:
        t.say(f'葵花 {npc} 没出菜单（已经拔过？战斗 {lead.world().in_battle}）')
        return
    t.say(f'葵花 {npc}: {t.plain(d.text)[:40]} {[t.plain(l) for _, l in d.options]}')
    opt = next((o for o, l in d.options if '连根拔起' in t.plain(l)), None)
    if opt is None:
        return
    lead.game.select_dialog(opt)
    time.sleep(2)
    s = lead.world()
    d = lead.dialog()
    t.say(f'拔了 {npc}: 战斗 {s.in_battle} 对话 {t.plain(d.text)[:60] if d else None} 任务 {kh.steps(lead)}')


if __name__ == '__main__':
    lead = t.Client(ROLES[0])
    for n in sys.argv[1:]:
        pull(lead, int(n))
