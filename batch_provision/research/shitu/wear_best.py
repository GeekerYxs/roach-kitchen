"""Wear the best bag equipment the role's level allows (user, round 3 12:2x).

    python -X utf8 research/shitu/wear_best.py 千万1 ...

Weapon: 酷·太公钓竿 64214 (攻击 396-792, 力量+15; ItemProp 38400 = 攻击 low/high word) beats 强劲之棍 64293 (攻击 327-654,
力量+8, 敏捷+8) and 专打屁屁扳手 118 (no props). Other slots: the bag holds at most one piece per slot, worn when ItemLib
等级要求 (column 7) <= level. Vehicles (香蕉车) are left alone. Equip = 0x47 move bag -> equip slot (the server picks the
real slot for armour; the weapon slot 2 swaps the old weapon into the bag). Every move is checked on the worn list.
"""
import csv
import io
import sys
import time

import trial_run as t
from factory.items import load_items
from provisioner import world as w
from provisioner.game import OP_MOVE_ITEM, move_item_body

LIB = r'D:/Codes/Gemini_Prj/smsm2_game/unpacked_game_data/ResLib/ItemLib_utf8.csv'
WEAPON, BEST_WEAPON = 0x103, 64214
ARMOR = range(0x101, 0x10A)          # 帽子 .. 靴子, without vehicles / pet gear


def need_level():
    rows = csv.reader(io.StringIO(open(LIB, encoding='utf-8', errors='replace').read()))
    return {int(r[0]): int(r[6]) for r in rows if r and r[0].isdigit()}


def run(name, items, req):
    c = t.Client(name)
    level, done = w.read_level(c.mem), []
    worn = lambda: {e.item_id for e in w.read_equipment(c.mem)}          # noqa: E731
    for s in sorted(w.read_bag(c.mem), key=lambda s: s.slot):
        it = items.get(s.item_id)
        if not it or it.type not in ARMOR or (it.type == WEAPON and s.item_id != BEST_WEAPON):
            continue
        if req.get(s.item_id, 999) > level:
            t.say(f'[{name}] {it.name} 要 {req.get(s.item_id)} 级，现在 {level} 级，先不穿')
            continue
        slot = next(x.slot for x in w.read_bag(c.mem) if x.item_id == s.item_id)
        c.game.send(OP_MOVE_ITEM, move_item_body(False, True, slot, it.type - 0x101))
        try:
            t.wait(lambda: s.item_id in worn(), 4, f'{name} 穿上 {it.name}')
            done.append(it.name)
        except t.Stop:
            t.say(f'[{name}] {it.name} 没穿上（属性要求不够？）')
        time.sleep(0.5)
    t.say(f'[{name}] {level} 级，穿上 {done}；现在身上 {[items[i].name for i in worn() if i in items]}')


if __name__ == '__main__':
    table, req = load_items(), need_level()
    try:
        for n in sys.argv[1:]:
            run(n, table, req)
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
