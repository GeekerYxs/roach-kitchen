"""Research helper (2026-11-06): the leader leads the team to one 陷阱囚牢 NPC, clicks it, and logs what happens.

    python -X utf8 probe_bottle.py <npc id> [option to pick ...]
    PROBE_ROLE=伏地魔2 python -X utf8 probe_bottle.py <npc id>     (a role out of the team walks and clicks alone)

Live 2026-11-06: a team member's click on a bottle does nothing; out of the team 伏地魔2 got 荒土结晶 from 4076,
which had failed for the leader -> crystals are per role and random per touch.

Logs the dialog, the five bags' crystals (11050 荒土 / 11051 大风 / 11052 烈火), quest 1130 steps, hp and battle.
"""
import os
import sys
import time

from _bootstrap import ROLES

import pp_chain
from lunhui15 import fight_out
import trial_run as t
from provisioner import world as w

CAGE = 1150
NPCS = {4067: (834, 2259), 4068: (1446, 2613), 4069: (3186, 3447),            # 烈火之瓶
        4070: (6630, 2139), 4071: (4386, 999), 4072: (3750, 687),             # 大风之瓶
        4073: (4122, 3969), 4074: (5322, 3417), 4075: (5874, 3129), 4076: (7062, 2475),   # 荒土之瓶
        4077: (3381, 1998)}                                                    # 琉璃瓶 (ResLib NPCDirection)
CRYSTALS = {11050: '荒土结晶', 11051: '大风结晶', 11052: '烈火结晶'}


def report(cs, why):
    for c in cs:
        s = c.world()
        bag = w.read_bag(c.mem) or ()
        got = {CRYSTALS[b.item_id]: b.quantity for b in bag if b.item_id in CRYSTALS}
        q = w.read_quest(c.mem, 1130)
        t.say(f'{why} [{c.name}] map {s.map_id} ({s.x:.0f},{s.y:.0f}) 战斗 {s.in_battle} 结晶 {got} '
              f'任务 {q.steps if q else None}')


def show(lead):
    d = lead.dialog()
    if d:
        t.say(f'对话: {t.plain(d.text)}')
        t.say(f'选项: {[(o, t.plain(l)) for o, l in d.options]}')
    else:
        t.say('没有对话框')
    return d


def main(npc, picks):
    cs = [t.Client(n) for n in ROLES]
    lead = next(c for c in cs if c.name == os.environ.get('PROBE_ROLE', ROLES[0]))
    cs = [lead] + [c for c in cs if c is not lead]
    report(cs, '之前')
    fight_out(lead)
    for attempt in range(5):                 # live 12:57: battles on the way ate pp_chain.walk's 120 s
        try:
            pp_chain.walk(lead, CAGE, NPCS[npc], f'NPC {npc}')
            break
        except t.Stop:
            if attempt == 4:
                raise
            fight_out(lead, 300)
    fight_out(lead)
    time.sleep(1)
    lead.game.click_npc(npc)
    time.sleep(1.5)
    d = show(lead)
    for p in picks:
        before = d.text if d else None
        lead.game.select_dialog(int(p))
        time.sleep(1.5)
        t.say(f'选了 {p}')
        d = show(lead)
    time.sleep(1)
    report(cs, '之后')
    if lead.world().in_battle:
        t.say('点完进了战斗，打完')
        fight_out(lead)
        report(cs, '打完')


if __name__ == '__main__':
    try:
        main(int(sys.argv[1]), sys.argv[2:])
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
