"""Give every tradable 橙 (quality 4) equipment, then all gold, of the named roles to one receiver (user 18:2x: 8 个
小号的橙装和金币全部交易给 box06).

    python -X utf8 research/shitu/give_box.py RECEIVER 千万1 千万2 ...

One item per trade (supply_go.trade_until: the giver walks up to the receiver, six requests, verified in the
receiver's bag), then one gold trade with the giver's whole gold, verified on the receiver's gold.
"""
import sys

import trial_run as t
from factory.items import EQUIP_TYPES, load_items
from provisioner import world as w
from supply_go import trade_until


def orange(c, items):
    return [s for s in w.read_bag(c.mem) if s.item_id in items and items[s.item_id].type in EQUIP_TYPES
            and items[s.item_id].quality == 4 and items[s.item_id].tradable]


def give(rcv, name, items):
    g = t.Client(name)
    for c in (g, rcv):
        if c.team():
            c.game.team_leave()
            t.wait(lambda: not c.team(), 5, f'{c.name} 离队')
    sent = []
    for s in orange(g, items):
        before = w.item_count(w.read_bag(rcv.mem), s.item_id)
        trade_until(g, rcv, (g.game.trade_offer_item, (s.slot, 1)),
                    lambda: w.item_count(w.read_bag(rcv.mem), s.item_id) > before, f'{rcv.name} 收到 {items[s.item_id].name}')
        sent.append(items[s.item_id].name)
    gold, before = w.read_gold(g.mem), w.read_gold(rcv.mem)
    if gold:
        trade_until(g, rcv, (g.game.trade_offer_gold, (gold,)), lambda: w.read_gold(rcv.mem) >= before + gold,
                    f'{rcv.name} 收到 {gold} 金币')
    t.say(f'[{name}] -> {rcv.name}: 橙装 {sent}；金币 {gold}（{name} 剩 {w.read_gold(g.mem)}，{rcv.name} '
          f'{before} -> {w.read_gold(rcv.mem)}）；{rcv.name} 背包 {len(w.read_bag(rcv.mem))}/{w.read_bag_capacity(rcv.mem)}')


if __name__ == '__main__':
    receiver, *names = sys.argv[1:]
    table = load_items()
    r = t.Client(receiver)
    try:
        for n in names:
            give(r, n, table)
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
