"""Wear the best bag equipment the role's level allows (user, round 3 12:2x).

    python -X utf8 research/shitu/wear_best.py 千万1 ...

Weapon: 酷·太公钓竿 64214 (攻击 396-792, 力量+15; ItemProp 38400 = 攻击 low/high word) beats 强劲之棍 64293 (攻击 327-654,
力量+8, 敏捷+8) and 专打屁屁扳手 118 (no props). Other slots: the bag holds at most one piece per slot, worn when ItemLib
等级要求 (column 7) <= level. Vehicles (香蕉车) are left alone. Equip = 0x47 move bag -> equip slot (the server picks the
real slot for armour; the weapon slot 2 swaps the old weapon into the bag). Every move is checked on the worn list.
"""
import csv
import io
import os
import struct
import sys
import time

import trial_run as t
from factory.items import load_items
from provisioner import world as w
from provisioner.game import OP_MOVE_ITEM, move_item_body

LIB = r'D:/Codes/Gemini_Prj/smsm2_game/unpacked_game_data/ResLib/ItemLib_utf8.csv'
WEAPON, BEST_WEAPON = 0x103, 64214
ARMOR = range(0x101, 0x10A)
# the five 新手装 (头巾 / T恤 / 泡裤 / 腰绳 / 休闲鞋): three have no 新手 / 新人 in the name (2026-11-02 元素使 batch)
NOVICE = frozenset((21000, 21500, 22000, 22500, 23000))          # 帽子 .. 靴子, without vehicles / pet gear


EQUIP_LIB = LIB.replace('ItemLib_utf8', 'EquipLib_utf8')
STAT_OFFSETS = (0xF18, 0xF1C, 0xF20, 0xF24, 0xF28)    # 力 / 感 / 耐(体质) / 敏 / 运, confirmed values (provisioner.game)


def stat_req():
    """{item id: (力, 感, 耐, 敏, 运) required} from EquipLib (columns 6-10). The 成长礼包 armour (升华 / 守护 / 专注 /
    勇猛) needs 耐力 32-38 at 20-23; most shop armour needs nothing (2026-11-02)."""
    rows = csv.reader(io.StringIO(open(EQUIP_LIB, encoding='utf-8', errors='replace').read()))
    return {int(r[0]): tuple(int(x or 0) for x in r[5:10]) for r in rows if r and r[0].isdigit() and len(r) >= 10}


def read_stats(mem):
    s = mem.u32(mem.base + w.SESSION_MGR_RVA)
    return tuple(struct.unpack('<H', mem.read(s + o, 2))[0] for o in STAT_OFFSETS)


def wearable(item_id, stats, reqs):
    return all(have >= need for have, need in zip(stats, reqs.get(item_id, (0,) * 5)))


def need_level():
    rows = csv.reader(io.StringIO(open(LIB, encoding='utf-8', errors='replace').read()))
    return {int(r[0]): int(r[6]) for r in rows if r and r[0].isdigit()}


def better(it, req, other, item_id, other_id):
    """Rank of a piece: required level first, then quality (a pack piece for 15 beats the 5 one)."""
    return (req.get(item_id, 0), it.quality) > (req.get(other_id, 0), other.quality) if other else True


def run(name, items, req, weapon=True, novice=True):
    """weapon=False / novice=False (元素使 team, user 2026-11-02): no weapon at all (it adds 蓄力), and the 新手装 are
    not worn but sold; a piece goes on only when it ranks above what that slot holds now."""
    c = t.Client(name)
    level, done = w.read_level(c.mem), []
    stats, reqs = read_stats(c.mem), stat_req()
    worn = lambda: {e.item_id for e in w.read_equipment(c.mem)}          # noqa: E731
    on = {e.slot: e.item_id for e in w.read_equipment(c.mem)}
    best = {}                                                            # equip slot -> best bag item id
    for s in sorted(w.read_bag(c.mem), key=lambda s: s.slot):
        it = items.get(s.item_id)
        if not it or it.type not in ARMOR or (it.type == WEAPON and (not weapon or s.item_id != BEST_WEAPON)):
            continue
        if not novice and s.item_id in NOVICE:
            continue
        if req.get(s.item_id, 999) > level:
            t.say(f'[{name}] {it.name} 要 {req.get(s.item_id)} 级，现在 {level} 级，先不穿')
            continue
        if not wearable(s.item_id, stats, reqs):
            t.say(f'[{name}] {it.name} 属性要求 {reqs[s.item_id]}，现在 {stats}，穿不上')
            continue
        k = it.type - 0x101
        cur = best.get(k, on.get(k))
        if cur is None or better(it, req, items.get(cur), s.item_id, cur):
            best[k] = s.item_id
    for k, item_id in best.items():
        it = items[item_id]
        slot = next(x.slot for x in w.read_bag(c.mem) if x.item_id == item_id)
        c.game.send(OP_MOVE_ITEM, move_item_body(False, True, slot, k))
        try:
            t.wait(lambda: item_id in worn(), 4, f'{name} 穿上 {it.name}')
            done.append(it.name)
        except t.Stop:
            t.say(f'[{name}] {it.name} 没穿上（属性要求不够？）')
        time.sleep(0.5)
    t.say(f'[{name}] {level} 级，穿上 {done}；现在身上 {[items[i].name for i in worn() if i in items]}')


if __name__ == '__main__':
    table, req = load_items(), need_level()
    plain = os.environ.get('SHITU_TIDY') != '1'        # tidy teams (元素使): no weapon, no 新手装 (tidy.py)
    # --no-weapon: the 勇者 line's apprentices wear no weapon (user 2026-11-04, sell_tradable --weapons sells them);
    # the rest of the gear as before
    no_weapon = '--no-weapon' in sys.argv
    names = [a for a in sys.argv[1:] if a != '--no-weapon']
    try:
        t.each(names, lambda n: run(n, table, req, weapon=plain and not no_weapon, novice=plain))      # each its own bag, at once (user 2026-11-01)
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
