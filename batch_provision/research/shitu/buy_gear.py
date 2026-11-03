"""Buy the 35 级 白装 set (恶魔 = 布, 职业 999 like the 术士's pack armour) at 乐乐姐 and wear it, each apprentice at once.

    python -X utf8 research/shitu/buy_gear.py 元素使01 元素使02 ...        (default: SHITU_APPRENTICES)

User 2026-11-02: the 元素使 team (体质 3, everything in 敏捷) dies in 通天塔二区, so before it they buy a white set.
乐乐姐 NPC 560, 龙之都外城 20 (606,1119): 购买30 / 35 / 40 / 45 / 50级装备. Her 35 级 shelf (0x40c0, live 23:40) holds three
sets in this order: 恶魔 布帽 / 疾风 头罩 / 磐石 头甲, then 布甲 / 软甲 / 精甲, 热裤 / 护腿 / 腿甲, 腰带 / 护腰 / 束带,
轻靴 / 便鞋 / 长靴; no stat requirement anywhere (疾风 = 职业 620, 磐石 = 100). Buy = packets like factory.supply.ShopClient (0x50 click,
0x51 menu option, 0x55 with buy_scroll's <IIBBHBH> body, qty 16 bits), one piece per fresh open, no UI: after the
shelf had been opened once, ClickNpc(560) gave no dialog any more (23:42, the client's shop window). The bag must then
hold that item, else stop.
A walker with a dialog open does not move (23:39: 元素使01 stood 2 min at 得禄's shop), so dialogs are closed first.
Run it with the team in 龙之都外城 (pp_chain 龙之都).
"""
import struct
import sys
import time

import trial_run as t
import wear_best
from common import APPRENTICES
from factory.items import load_items
from pp_chain import walk
from provisioner import world as w

NPC, MAP, XY, OPTION = 560, 20, (606, 1160), 2           # menu: 1 30级 / 2 35级 / 3 40级 / 4 45级 / 5 50级
SET = ((0, 2729), (5, 4229), (10, 5235), (15, 6235), (20, 7243))   # (shelf slot, item): 恶魔 布帽 布甲 热裤 腰带 轻靴
# shelf slots are a grid of rows of 5 with 3 sets per row (the user bought 布甲 by hand 23:45: slot 5; list order 3 was
# 「商品已下架」), so a set is slot 0 / 5 / 10 / 15 / 20 + its column


def close(c):
    if c.dialog():
        c.game.select_dialog(0)
        time.sleep(0.5)


def one(name, items, req):
    c = t.Client(name)
    c.game.cancel_navigation()
    if c.team():
        c.game.team_leave()
        t.wait(lambda: not c.team(), 5, f'{name} 离队')
    close(c)
    have = {e.item_id for e in w.read_equipment(c.mem)} | {s.item_id for s in w.read_bag(c.mem)}
    todo = [(slot, i) for slot, i in SET if i not in have]
    if todo:
        walk(c, MAP, XY, f'乐乐姐 {NPC}')
    gold = w.read_gold(c.mem)
    for slot, item in todo:
        c.game.send(0x50, struct.pack('<II', 0, NPC))
        time.sleep(0.5)
        c.game.send(0x51, struct.pack('<III', 0, OPTION, 0))
        time.sleep(0.5)
        before = w.item_count(w.read_bag(c.mem), item)
        c.game.send(0x55, struct.pack('<IIBBHBH', 0, NPC, 1, 0, 0, slot, 1))
        try:
            t.wait(lambda: w.item_count(w.read_bag(c.mem), item) > before, 5, f'{name} 买 {items[item].name}')
        except t.Stop:
            got = [items[s.item_id].name for s in w.read_bag(c.mem) if s.item_id not in have and s.item_id in items]
            raise t.Stop(f'{name} 第 {slot} 格没买到 {items[item].name}（背包新东西: {got}）')
    t.say(f'[{name}] 买了 {[items[i].name for _, i in todo]}，金币 {gold} -> {w.read_gold(c.mem)}')
    wear_best.run(name, items, req, weapon=False, novice=False)


def main(names):
    items, req = load_items(), wear_best.need_level()
    t.each(names, lambda n: one(n, items, req))


if __name__ == '__main__':
    try:
        main(sys.argv[1:] or list(APPRENTICES))
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
