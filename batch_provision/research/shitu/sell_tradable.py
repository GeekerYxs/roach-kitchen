"""Take off the weapon and sell EVERY tradable bag slot at 宠物商人小美 (NPC 329, map 1 (1338,1155)).

    python -X utf8 research/shitu/sell_tradable.py 十万1 十万2 十万3
    python -X utf8 research/shitu/sell_tradable.py --junk 百万1 ...     mid-run: keep the weapon on and keep 回城卷
    python -X utf8 research/shitu/sell_tradable.py --safe 千万1 ...     round 3 (apprentices kept): only 杂物 / 残骸 and
                                                                        equipment below 蓝 (quality < 3); weapon stays on
    python -X utf8 research/shitu/sell_tradable.py --zawu 伏地魔1 ...   masters: only tradable 杂物 (type 0x1000)
    python -X utf8 research/shitu/sell_tradable.py --stones 伏地魔1 千万1 ...   user 16:2x, everybody: 杂物 / 残骸 / every
                                                                        技能石 (0x821, 蓝 and 橙 too) / 图纸, 配方;
                                                                        no equipment, 回城卷 kept
    python -X utf8 research/shitu/sell_tradable.py --noorange 千万1 ...   user 18:1x: 杂物 + every equipment below 橙
                                                                        (白/绿/蓝, quality < 4); 橙 kept, worn items stay on
    python -X utf8 research/shitu/sell_tradable.py --name 配方,碧玉葫芦 千万1 ...   only tradable items whose name holds
                                                                        one of the words (user 18:2x: 配方 / 专打屁屁扳手 /
                                                                        碧玉葫芦 / 紫金红葫芦 / 酷·太公钓竿)

User, 2026-10-27: sell everything that can be sold; pick the slots by the item's trade flag first and put them in
one request (up to 20 slots per 0x55, factory.supply.SELL_BATCH) instead of trying slot after slot.
Evidence (02:55 十万1): of 35 slots, all 13 tradable ones sold and all 22 不可交易 ones (the (御) gift items,
新手洗点卡, 神秘的金属) were refused, so the ItemLib trade flag (factory/data/items.csv) is the rule.
"""
import sys

import trial_run as t
from common import APPRENTICES
from factory.items import EQUIP_TYPES, load_items
from factory.supply import PETSHOP, ShopClient
from provisioner import log, world as w
from zhuanzhi_finish import walk

WEAPON_SLOT = 2


def unequip_weapon(c, nm):
    for e in w.read_equipment(c.mem) or ():
        if e.slot == WEAPON_SLOT:
            used = {s.slot for s in w.read_bag(c.mem)}
            free = next(i for i in range(w.read_bag_capacity(c.mem)) if i not in used)
            c.game.unequip(WEAPON_SLOT, free)
            t.wait(lambda: not any(x.slot == WEAPON_SLOT for x in w.read_equipment(c.mem)), 5, f'{c.name} 脱下武器')
            t.say(f'[{c.name}] 脱下 {nm(e.item_id)} -> 背包第 {free} 格')


KEEP_JUNK = {9801}              # --junk keeps 回城卷 (round 2, 04:57: all bags full in the cave, sold mid-run)
KEEP_QUALITY = 3                # user, round 3: never sell 蓝 (3) / 橙 (4) equipment; quality = items.csv per item id
ZAWU, RELIC, STONE, RECIPE = 0x1000, 0x82B, 0x821, 0x823   # factory/items.py type names


NAMES = ()


def wanted(it, mode):
    """Sell this tradable item in `mode`?  all / junk: everything tradable (junk keeps 回城卷);
    safe: 杂物 / 残骸 + equipment below 蓝; zawu: 杂物 only; stones: 杂物 / 残骸 / 技能石 / 图纸 / 配方; noorange: 杂物 + equipment below 橙."""
    if it.item_id in KEEP_JUNK and mode != 'all':
        return False
    if mode == 'zawu':
        return it.type == ZAWU
    if mode == 'name':
        return any(k in it.name for k in NAMES)
    if mode == 'noorange':
        return it.type == ZAWU or (it.type in EQUIP_TYPES and it.quality < 4)
    if mode == 'stones':
        # 配方 by TYPE: their names look like gear (学识之头罩, 猛袭之软甲 ...), so the name test missed them (18:2x)
        return it.type in (ZAWU, RELIC, STONE, RECIPE) or '图纸' in it.name or '配方' in it.name
    if mode == 'safe':
        return it.type in (ZAWU, RELIC) or (it.type in EQUIP_TYPES and it.quality < KEEP_QUALITY)
    return True


def main(names, mode='all'):
    log.setup(t.HERE / 'logs', prefix='sell_tradable')
    items = load_items()
    nm = lambda i: items[i].name if i in items else str(i)        # noqa: E731
    for n in names:
        c = t.Client(n)
        if mode == 'all':
            unequip_weapon(c, nm)
        walk(c, 1, (1338, 1155), '宠物商人小美')
        bag = w.read_bag(c.mem)
        sell = [s for s in bag if s.item_id in items and items[s.item_id].tradable and wanted(items[s.item_id], mode)]
        keep = [nm(s.item_id) for s in bag if s not in sell]
        gold = w.read_gold(c.mem)
        t.say(f'[{n}] 模式 {mode}：卖 {len(sell)} 格: {[nm(s.item_id) for s in sell]}；留 {len(keep)} 格: {keep}')
        shop = ShopClient(c.game, c.mem, log.for_account(n))
        sold = shop.sell(PETSHOP, sell) if sell else 0
        shop.close()
        left = [nm(s.item_id) for s in w.read_bag(c.mem) if s in sell]
        t.say(f'[{n}] 卖了 {sold}/{len(sell)} 格，金币 {gold} -> {w.read_gold(c.mem)}' +
              (f'；可交易但没卖掉: {left}' if left else ''))


if __name__ == '__main__':
    flags = {'--junk': 'junk', '--safe': 'safe', '--zawu': 'zawu', '--stones': 'stones', '--noorange': 'noorange'}
    argv = sys.argv[1:]
    if '--name' in argv:
        i = argv.index('--name')
        NAMES = tuple(argv[i + 1].split(','))
        argv = argv[:i] + ['--name'] + argv[i + 2:]
        flags['--name'] = 'name'
    args = [a for a in argv if a not in flags]
    modes = [flags[a] for a in argv if a in flags]
    main(args or list(APPRENTICES), modes[0] if modes else 'all')
