"""Open the 成长大礼包 31140 and every N级成长礼包 (31141 = 5级 ... 31149 = 45级) the role's level allows.

    python -X utf8 research/shitu/open_packs.py 千万1 千万2 ...

User, round 3 (12:0x): open all apprentices' 成长大礼包. Live 千万1: use_item on 31140 -> the 9 level packs in the bag,
no dialog. One use_item at a time; a pack counts as opened when its stack is gone from the bag. Stops a role when
fewer than MIN_FREE bag slots are left or a pack does not open within WAIT seconds (level too low / bag full).
"""
import sys
import time

import trial_run as t
from factory.items import load_items
from provisioner import world as w

BIG, FIRST, LAST = 31140, 31141, 31149
MIN_FREE, WAIT = 1, 5.0


def need_level(item):
    return 0 if item == BIG else 5 * (item - FIRST + 1)


def run(name, items):
    c = t.Client(name)
    level, opened = w.read_level(c.mem), []
    while True:
        bag = w.read_bag(c.mem)
        free = w.read_bag_capacity(c.mem) - len(bag)
        packs = sorted((s for s in bag if BIG <= s.item_id <= LAST and need_level(s.item_id) <= level),
                       key=lambda s: s.item_id)
        if not packs:
            break
        if free < MIN_FREE:
            t.say(f'[{name}] 背包只剩 {free} 格，停下（还有 {[items[s.item_id].name for s in packs]}）')
            break
        s = packs[0]
        c.game.use_item(s.slot)
        try:
            t.wait(lambda: w.item_count(w.read_bag(c.mem), s.item_id) < s.quantity, WAIT, f'{items[s.item_id].name} 打开')
        except t.Stop:
            t.say(f'[{name}] {items[s.item_id].name} 没打开，停下')
            break
        opened.append(items[s.item_id].name)
        time.sleep(0.5)
    bag = w.read_bag(c.mem)
    left = [items[s.item_id].name for s in bag if BIG <= s.item_id <= LAST]
    t.say(f'[{name}] {level} 级，开了 {len(opened)} 个: {opened}；背包 {len(bag)}/{w.read_bag_capacity(c.mem)}；剩下 {left}')


if __name__ == '__main__':
    table = load_items()
    try:
        for n in sys.argv[1:]:
            run(n, table)
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
