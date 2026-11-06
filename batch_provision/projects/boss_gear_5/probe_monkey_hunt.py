"""Research helper (2026-11-06, 金刚猴 quest 518): patrol two 850 points (tiger_fight.walk: re-paths, fights every
encounter), log who holds which item after each leg, until the leader holds 定土神针 and 鲜花铠甲 (or N legs).

    python -X utf8 probe_monkey_hunt.py AX AY BX BY [legs]
"""
import sys

from _bootstrap import ROLES

import monkey as mk
import tiger_fight
import trial_run as t


def main(a, b, legs):
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    for i in range(legs):
        if mk.has(lead, mk.PIN) and mk.has(lead, mk.ARMOR):
            break
        xy = (a, b)[i % 2]
        tiger_fight.walk(lead, xy, f'巡逻点 {xy}', mk.BAOKU, '秘密宝窟', 'enter_baoku.py')
        mk.say_state(cs, f'第 {i + 1} 段走完')


if __name__ == '__main__':
    v = [int(x) for x in sys.argv[1:]]
    main((v[0], v[1]), (v[2], v[3]), v[4] if len(v) > 4 else 10)
