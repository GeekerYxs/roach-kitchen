"""Research helper (2026-11-06, 葵花宝典 quest 475): pull the given 葵花 over and over (they grow back within ~4 min)
and after every pull click 葵花姐姐 1146 from near her spot, until she answers.

    python -X utf8 probe_kuihua_loop.py <rounds> <npc id> ...
"""
import sys
import time

from _bootstrap import ROLES

import kuihua as kh
import probe_kuihua_walk
import trial_run as t
from eagle_cage import click, settle
from tiger_fight import fight_all

REACH = 20                   # user 2026-11-06: pulling from 250 px said「距离太远」; stand on the flower


def sister(lead):
    probe_kuihua_walk.main(*kh.SISTER_XY, 20)   # 2026-11-06 live: she answered from 14 px, never from 240 px
    settle(lead)
    click(lead, kh.SISTER)
    time.sleep(2)
    d = lead.dialog()
    if d:
        t.say(f'葵花姐姐: {t.plain(d.text)} {[t.plain(l) for _, l in d.options]}')
    return d


def pull(cs, npc):
    lead = cs[0]
    probe_kuihua_walk.main(*kh.FLOWERS[npc], REACH)
    settle(lead)
    click(lead, npc)
    try:
        d = t.wait(lambda: lead.dialog(), 4, f'葵花 {npc} 菜单')
    except t.Stop:
        t.say(f'葵花 {npc} 没出菜单（还没长回来？战斗 {lead.world().in_battle}）')
        return False
    opt = next((o for o, l in d.options if '连根拔起' in t.plain(l)), None)
    time.sleep(0.5)
    lead.game.select_dialog(opt)
    end = time.monotonic() + 4
    while time.monotonic() < end and not lead.world().in_battle and lead.dialog():
        time.sleep(0.2)
    time.sleep(1.5)
    s = lead.world()
    t.say(f'拔了 {npc}: 战斗 {s.in_battle} 对话 {t.plain(lead.dialog().text)[:50] if lead.dialog() else None}')
    if s.in_battle:
        f0 = time.monotonic()
        fight_all(cs, 300, f'葵花 {npc} 战斗')
        t.say(f'葵花 {npc} 的战斗打完（{time.monotonic() - f0:.0f} 秒），任务 {kh.steps(lead)}')
    return True


def main(rounds, npcs):
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    pulled = 0
    for r in range(rounds):
        for n in npcs:
            pulled += pull(cs, n)
            t.say(f'第 {r + 1} 轮，一共拔了 {pulled} 朵')
            if sister(lead):
                return


if __name__ == '__main__':
    main(int(sys.argv[1]), [int(x) for x in sys.argv[2:]])
