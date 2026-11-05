"""元素使 line end (user 2026-11-05): open the bag's 囧盒仔 and send the 囧盒仔 pet out to fight, each apprentice at once.

    python -X utf8 research/shitu/jiong.py 元素使01 元素使02 ...        (default: SHITU_APPRENTICES)

(御)囧盒仔 41848 / 囧盒仔 41847 (type 0x2080) is used like a gift pack (game.use_item on its slot): the pet list grows
by one. The fighting pet is then set with 0x0105 <I 0><B pet index> (projects/fullcrit_mage_leveling_70/pet_level_40.py,
which levels that second pet; verified there by P+PET_FIGHTING). A role that already has the extra pet only gets
the fighting switch; one with neither the item nor a second pet is reported and skipped.
"""
import struct
import sys
import time

import trial_run as t
from common import APPRENTICES
from provisioner import world as w

ITEMS = (41848, 41847)               # (御)囧盒仔, 囧盒仔
OP_SET_FIGHTING_PET = 0x0105


def pets(c):
    p = w._player_data(c.mem)
    first, last = w._vector(c.mem, p + w.PET_VECTOR, 4 * 50)
    return (last - first) // 4, struct.unpack('<i', c.mem.read(p + w.PET_FIGHTING, 4))[0]


def one(name):
    c = t.Client(name)
    t.wait(lambda: not (s := c.world()).in_battle and not s.busy, 120, f'{name} 战斗结束')
    count, fighting = pets(c)
    box = next((s for s in w.read_bag(c.mem) if s.item_id in ITEMS), None)
    if box and count < 2:
        if c.dialog():
            c.game.select_dialog(0)
            time.sleep(0.3)
        c.game.use_item(box.slot)
        t.wait(lambda: pets(c)[0] > count, 5, f'{name} 打开囧盒仔后宠物变多')
        count = pets(c)[0]
        t.say(f'[{name}] 打开囧盒仔，宠物 {count} 只')
        if c.dialog():                  # a confirmation / notice page, if the game opens one
            c.game.select_dialog(0)
    elif count < 2:
        t.say(f'[{name}] 背包里没有囧盒仔，也没有第二只宠物，跳过')
        return
    target = count - 1                  # the newest pet = the 囧盒仔
    if fighting != target:
        c.game.send(OP_SET_FIGHTING_PET, struct.pack('<I', 0) + bytes((target,)))
        t.wait(lambda: pets(c)[1] == target, 5, f'{name} 囧盒仔出战')
    t.say(f'[{name}] 囧盒仔出战（宠物 {count} 只，出战第 {target + 1} 只）')


def main(names):
    t.each(names, one)


if __name__ == '__main__':
    try:
        main(sys.argv[1:] or list(APPRENTICES))
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
