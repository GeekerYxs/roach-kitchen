"""Buy 回城卷 9801 at the 自由市场 补给商 铁公鸡 (NPC 25, map 300 (1650,1071)) up to N per role.

    python -X utf8 research/shitu/buy_scroll.py N 千万1 千万2 ...

User round 3 16:1x: everybody restocks 回城卷 here before going out. Shelf like 花袭人 (factory/supply.py):
Shelf = order in the 0x40c0 list: 0 萝卜糕, 1 胡萝卜汁, 2 回城卷 (live 2026-10-27 16:2x). Each buy = ClickNpc + 「购买杂货」 + one
0x55 <I0><I npc><B1><B0 buy><H0><B shelf><H qty> (client 2.100, qty 16 bits as for sells; the <B qty> body and
shelf 4 were refused with 0x40c1), verified in the bag (20 = 50 gold); dialog closed after.
"""
import struct
import sys
import time

import trial_run as t
from pp_chain import walk
from provisioner import world as w
from quanshou import SCROLL_ITEM

NPC, XY, SHELF, MAX_ONE = 25, (1650, 1071), 2, 50


# 2026-10-30 user: the masters' pets drink 胡萝卜汁 (AutoUseItemID: 宠物补魔法 = 63954 胡萝卜汁 / 8456 劲爆汽水); when
# they have fewer than JUICE_LOW, buy JUICE_FULL (20 x 99) here. 伏地魔1 had run dry: pet mp 68, 烈焰爆发 stopped.
# 胡萝卜汁 gives 50 mp, 劲爆汽水 590 (ItemProp PropValue): 1980 juice lasted 伏地魔1 about 2.5 h of 烈焰爆发, so
# every home() checks too (r4_util.home).
JUICE, JUICE_SHELF, PET_MP_ITEMS, JUICE_LOW, JUICE_FULL = 63954, 1, (63954, 8456), 50, 20 * 99


def count(c, item=SCROLL_ITEM):
    return w.item_count(w.read_bag(c.mem), item)


def pet_mp_items(c):
    bag = w.read_bag(c.mem)
    return sum(w.item_count(bag, i) for i in PET_MP_ITEMS)


def buy(c, n, item=SCROLL_ITEM, shelf=SHELF, label='回城卷'):
    """Buy `item` (shelf index at 铁公鸡) until the bag holds n of it."""
    walk(c, 300, XY, '铁公鸡 25')
    if c.dialog():
        c.game.select_dialog(0)
        time.sleep(0.5)
    gold = w.read_gold(c.mem)
    while (have := count(c, item)) < n:
        k = min(MAX_ONE, n - have)
        c.game.click_npc(NPC)
        d = t.wait(lambda: c.dialog(), 5, f'{c.name} 铁公鸡菜单')
        c.game.select_dialog(next(o for o, l in d.options if '购买' in t.plain(l)))
        time.sleep(0.6)
        c.game.send(0x55, struct.pack('<IIBBHBH', 0, NPC, 1, 0, 0, shelf, k))
        t.wait(lambda: count(c, item) >= have + k, 5, f'{c.name} {label} +{k}')
        c.game.select_dialog(0)
        time.sleep(0.5)
    t.say(f'[{c.name}] {label} {count(c, item)}，金币 {gold} -> {w.read_gold(c.mem)}')


def juice_needed(c):
    """How many 胡萝卜汁 to buy: up to JUICE_FULL once the pet's mp drinks are below JUICE_LOW, else 0."""
    have = pet_mp_items(c)
    return JUICE_FULL if have < JUICE_LOW else 0


if __name__ == '__main__':
    n, *names = sys.argv[1:]
    for name in names:
        buy(t.Client(name), int(n))
