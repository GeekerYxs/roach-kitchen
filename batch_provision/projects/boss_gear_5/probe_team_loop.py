"""Research helper (2026-11-06): with the full team, the leader touches one bottle again and again (user: bottles
are unlimited, the team does it together) until the leader holds the crystal; every bag is logged after each touch.

    python -X utf8 probe_team_loop.py <npc id> [max tries, default 5]
"""
import sys
import time

from _bootstrap import ROLES

import pp_chain
import trial_run as t
from lunhui15 import fight_out
from probe_bottle import CAGE, CRYSTALS, NPCS, report
from provisioner import world as w
from well10 import form_team

KIND = {4067: 11052, 4068: 11052, 4069: 11052, 4070: 11051, 4071: 11051, 4072: 11051,
        4073: 11050, 4074: 11050, 4075: 11050, 4076: 11050}


def has(c, item):
    return any(b.item_id == item for b in w.read_bag(c.mem) or ())


def main(npc, tries):
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    fight_out(lead, 300)
    if set(lead.team()) != {c.char_id for c in cs}:
        form_team(lead, cs[1:])
    item = KIND[npc]
    for i in range(1, tries + 1):
        if has(lead, item):
            t.say(f'队长已经有 {CRYSTALS[item]}，停')
            break
        for attempt in range(5):
            try:
                pp_chain.walk(lead, CAGE, NPCS[npc], f'NPC {npc}')
                break
            except t.Stop:
                if attempt == 4:
                    raise
                fight_out(lead, 300)
        fight_out(lead, 300)
        time.sleep(0.5)
        lead.game.click_npc(npc)
        time.sleep(2.5)
        report(cs, f'第 {i} 次')
        if lead.world().in_battle:
            t.say('点完进了战斗，打完')
            fight_out(lead, 300)
            report(cs, f'第 {i} 次打完')


if __name__ == '__main__':
    try:
        main(int(sys.argv[1]), int(sys.argv[2]) if len(sys.argv) > 2 else 5)
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
