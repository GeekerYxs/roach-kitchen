"""Drop every 整人道具 (ItemLib type 0x802 / 0x803: 定身丸, 就看你不爽, 蒙娜丽沙微笑, 变身卡 ...) from the bag.

    python -X utf8 research/shitu/drop_prank.py 千万1 千万2 ...
    python -X utf8 research/shitu/drop_prank.py --name 新手洗点卡 --name 葫芦 千万1 ...   instead: every item whose name
                                                                                      contains one of the words

Drop = 0x0048 <I 0><B 0><B bag slot><H quantity>, captured 2026-10-27 12:17 when the user dropped (御)定身丸 from 千万1 by
hand (slot 0x18, qty 1) and replayed on 千万1's (御)就看你不爽 (gone from the bag). One drop at a time, each checked.
"""
import struct
import sys

import trial_run as t
from factory.items import load_items
from provisioner import world as w

OP_DROP, PRANK = 0x48, (0x802, 0x803)


def run(name, items, words=()):
    hit = (lambda it: any(x in it.name for x in words)) if words else (lambda it: it.type in PRANK)
    c = t.Client(name)
    dropped = []
    for s in w.read_bag(c.mem):
        it = items.get(s.item_id)
        if not it or not hit(it):
            continue
        c.game.send(OP_DROP, struct.pack('<IBBH', 0, 0, s.slot, s.quantity))
        t.wait(lambda: not any(x.slot == s.slot and x.item_id == s.item_id for x in w.read_bag(c.mem)), 5,
               f'{name} 丢掉 {it.name}')
        dropped.append(f'{it.name}x{s.quantity}')
    left = [items[s.item_id].name for s in w.read_bag(c.mem) if s.item_id in items and hit(items[s.item_id])]
    t.say(f'[{name}] 丢了 {dropped}；背包 {len(w.read_bag(c.mem))}/{w.read_bag_capacity(c.mem)}' + (f'；还剩 {left}' if left else ''))


if __name__ == '__main__':
    table = load_items()
    try:
        args, words = sys.argv[1:], []
        while '--name' in args:
            i = args.index('--name')
            words.append(args[i + 1])
            del args[i:i + 2]
        for n in args:
            run(n, table, tuple(words))
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
