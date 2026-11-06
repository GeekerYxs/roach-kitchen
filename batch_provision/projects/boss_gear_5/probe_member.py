"""Research helper (2026-11-06): one role clicks a 陷阱囚牢 bottle where it stands (no walking), logs the result.

    python -X utf8 probe_member.py <role> <npc id>
"""
import sys
import time

from _bootstrap import ROLES

import trial_run as t
from lunhui15 import fight_out
from probe_bottle import report


def main(name, npc):
    cs = [t.Client(n) for n in ROLES]
    c = next(x for x in cs if x.name == name)
    fight_out(cs[0])
    report([c], '之前')
    c.game.click_npc(npc)
    time.sleep(2.5)
    report([c], '之后')
    if cs[0].world().in_battle:
        t.say('点完进了战斗，打完')
        fight_out(cs[0], 300)
        report([c], '打完')


if __name__ == '__main__':
    try:
        main(sys.argv[1], int(sys.argv[2]))
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
