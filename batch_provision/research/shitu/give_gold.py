"""Every apprentice trades all its gold to the master, the last step of a batch (user 2026-10-31).

    python -X utf8 research/shitu/give_gold.py MASTER 亿万1 亿万2 ...

One gold trade per apprentice (supply_go.trade_until: the giver walks up to the master, verified on the master's gold),
like give_box.py without the equipment. Rerun-safe: an apprentice with 0 gold is skipped.
"""
import sys

import trial_run as t
from provisioner import world as w
from supply_go import trade_until


def give(m, name):
    a = t.Client(name)
    for c in (a, m):
        if c.team():
            c.game.team_leave()
            t.wait(lambda: not c.team(), 5, f'{c.name} 离队')
    gold, before = w.read_gold(a.mem), w.read_gold(m.mem)
    if gold:
        trade_until(a, m, (a.game.trade_offer_gold, (gold,)), lambda: w.read_gold(m.mem) >= before + gold,
                    f'{m.name} 收到 {gold} 金币')
    t.say(f'[{name}] -> {m.name}: 金币 {gold}（{name} 剩 {w.read_gold(a.mem)}，{m.name} {before} -> {w.read_gold(m.mem)}）')
    return gold


if __name__ == '__main__':
    master, *names = sys.argv[1:]
    m = t.Client(master)
    try:
        total = sum(give(m, n) for n in names)
        t.say(f'[{master}] 收齐 {len(names)} 人金币共 {total}，现有 {w.read_gold(m.mem)}')
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
