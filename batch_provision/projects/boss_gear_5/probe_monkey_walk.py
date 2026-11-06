"""Research helper (2026-11-06, 金刚猴 quest 518): the leader walks the team to an 850 point, then logs items / layer.

    python -X utf8 probe_monkey_walk.py X Y
"""
import sys

from _bootstrap import ROLES

import monkey as mk
import tiger_fight
import trial_run as t


def main(x, y):
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    mk.say_state(cs, '之前')
    tiger_fight.walk(lead, (x, y), f'({x},{y})', mk.BAOKU, '秘密宝窟', 'enter_baoku.py')
    s = lead.world()
    mk.say_state(cs, f'之后 map {s.map_id} ({s.x:.0f},{s.y:.0f}) 上层 {mk.upper(lead)}')


if __name__ == '__main__':
    main(int(sys.argv[1]), int(sys.argv[2]))
