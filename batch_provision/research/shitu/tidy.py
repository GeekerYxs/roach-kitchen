"""Tidy the apprentices' bags at every trip home (user 2026-11-02, 元素使 team), each apprentice at once.

    python -X utf8 research/shitu/tidy.py 元素使01 元素使02 ...        (default: SHITU_APPRENTICES)

Per apprentice, in this order (first live run 21:43: packs first left no room, 38-39/40 bags):
  1. take off the weapon (apprentices carry none: it adds 蓄力) and any worn 新手装 (wear_best.NOVICE)
  2. drop every (御) 整人道具 (drop_prank)
  3. at 宠物商人小美 (map 1 (1338,1155)) sell 杂物 / 残骸, tradable equipment below 蓝 (the 新手装) and the
     专打屁屁扳手 (sell_tradable mode tidy; 回城卷 and the 不可交易 pack gear stay)
  4. open the 成长大礼包 and every N级成长礼包 the level allows (5, 10, 15 ... ; open_packs), drop their 整人道具
  5. wear the bag armour that ranks above what the slot holds (pack gear), never a weapon, never the 新手装
  6. sell again: what the packs brought that tidy sells, plus every armour piece whose stat requirement the role does
     not meet (the pack armour wants 耐力 32-38, these roles have 体质 3; the shop takes it although 不可交易, live
     21:46 元素使01 升华热裤)
Run it where the team is home in 逍遥村西区 (the 回城卷 lands next to 小美).
"""
import sys

import drop_prank
import open_packs
import sell_tradable
import trial_run as t
import wear_best
from common import APPRENTICES
from factory.items import load_items
from provisioner import world as w


STAT_REQ = {}


def take_off_novice(c, nm):
    for e in w.read_equipment(c.mem) or ():
        if e.item_id in wear_best.NOVICE:
            used = {s.slot for s in w.read_bag(c.mem)}
            free = next((i for i in range(w.read_bag_capacity(c.mem)) if i not in used), None)
            if free is None:
                t.say(f'[{c.name}] 背包满了，{nm(e.item_id)} 先不脱')
                return
            c.game.unequip(e.slot, free)
            t.wait(lambda: not any(x.item_id == e.item_id for x in w.read_equipment(c.mem)), 5, f'{c.name} 脱下 {nm(e.item_id)}')
            t.say(f'[{c.name}] 脱下 {nm(e.item_id)} -> 背包第 {free} 格')


def one(name, items, req):
    nm = lambda i: items[i].name if i in items else str(i)        # noqa: E731
    c = t.Client(name)
    sell_tradable.unequip_weapon(c, nm)
    take_off_novice(c, nm)
    drop_prank.run(name, items)
    sell_tradable.one(name, 'tidy', items, nm)
    open_packs.run(name, items)
    drop_prank.run(name, items)
    wear_best.run(name, items, req, weapon=False, novice=False)
    sell_tradable.one(name, 'tidy', items, nm)
    sell_unwearable(c, items, nm)


def sell_unwearable(c, items, nm):
    from factory.supply import ShopClient
    from provisioner import log
    stats, reqs = wear_best.read_stats(c.mem), STAT_REQ
    bad = [s for s in w.read_bag(c.mem) if s.item_id in items and items[s.item_id].type in wear_best.ARMOR
           and not wear_best.wearable(s.item_id, stats, reqs)]
    if not bad:
        return
    shop = ShopClient(c.game, c.mem, log.for_account(c.name))
    sold = shop.sell(sell_tradable.PETSHOP, bad)
    shop.close()
    t.say(f'[{c.name}] 属性不够穿不上，卖 {sold}/{len(bad)} 格: {[nm(s.item_id) for s in bad]}（力感耐敏运 {stats}）')


def main(names):
    from provisioner import log
    log.setup(t.HERE / 'logs', prefix='tidy')
    global STAT_REQ
    items, req = load_items(), wear_best.need_level()
    STAT_REQ = wear_best.stat_req()
    t.each(names, lambda n: one(n, items, req))


if __name__ == '__main__':
    try:
        main(sys.argv[1:] or list(APPRENTICES))
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
