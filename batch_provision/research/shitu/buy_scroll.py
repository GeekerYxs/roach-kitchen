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


def count(c):
    return w.item_count(w.read_bag(c.mem), SCROLL_ITEM)


def buy(c, n):
    walk(c, 300, XY, '铁公鸡 25')
    if c.dialog():
        c.game.select_dialog(0)
        time.sleep(0.5)
    gold = w.read_gold(c.mem)
    while (have := count(c)) < n:
        k = min(MAX_ONE, n - have)
        c.game.click_npc(NPC)
        d = t.wait(lambda: c.dialog(), 5, f'{c.name} 铁公鸡菜单')
        c.game.select_dialog(next(o for o, l in d.options if '购买' in t.plain(l)))
        time.sleep(0.6)
        c.game.send(0x55, struct.pack('<IIBBHBH', 0, NPC, 1, 0, 0, SHELF, k))
        t.wait(lambda: count(c) >= have + k, 5, f'{c.name} 回城卷 +{k}')
        c.game.select_dialog(0)
        time.sleep(0.5)
    t.say(f'[{c.name}] 回城卷 {count(c)}，金币 {gold} -> {w.read_gold(c.mem)}')


if __name__ == '__main__':
    n, *names = sys.argv[1:]
    for name in names:
        buy(t.Client(name), int(n))
