"""Take off everything the named roles wear, into free bag slots (user 18:2x: 「所有小号脱下身上所有装备」).

    python -X utf8 research/shitu/unequip_all.py 千万1 千万2 ...

One move per worn slot (game.unequip = 0x47 move equip -> bag), each verified: the slot is empty afterwards.
Stops a role when the bag has no free slot left.
"""
import sys
import time

import trial_run as t
from factory.items import load_items
from provisioner import world as w


def run(name, items):
    c = t.Client(name)
    off, kept = [], []
    for e in w.read_equipment(c.mem) or ():
        used = {s.slot for s in w.read_bag(c.mem)}
        free = next((i for i in range(w.read_bag_capacity(c.mem)) if i not in used), None)
        nm = items[e.item_id].name if e.item_id in items else str(e.item_id)
        if free is None:
            kept.append(nm)
            continue
        c.game.unequip(e.slot, free)
        try:
            t.wait(lambda: not any(x.slot == e.slot for x in w.read_equipment(c.mem)), 5, f'{name} 脱 {nm}')
            off.append(nm)
        except t.Stop:
            kept.append(nm)
        time.sleep(0.3)
    t.say(f'[{name}] 脱下 {off}' + (f'；没脱下 {kept}' if kept else '') +
          f'；身上还剩 {len(w.read_equipment(c.mem) or ())} 件，背包 {len(w.read_bag(c.mem))}/{w.read_bag_capacity(c.mem)}')


if __name__ == '__main__':
    table = load_items()
    for n in sys.argv[1:]:
        run(n, table)
