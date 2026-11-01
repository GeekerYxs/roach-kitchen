"""The master's bag over many batches (user 2026-10-31: masters lead 24 x 7, drops must not fill the bag so that 回城卷 /
蓝 / 宠物 drinks can still be bought).

    python -X utf8 research/shitu/master_bag.py snapshot MASTER          first time only: the item kinds in the bag now
                                                                        = the master's own (logs/master_bag/<name>.json)
    python -X utf8 research/shitu/master_bag.py clean MASTER [--if-free 5]
                                                                        every slot whose item kind is not in the snapshot
                                                                        and not kept below: tradable -> sold at 宠物商人小美
                                                                        (逍遥村), the rest dropped; --if-free N = only when
                                                                        N or fewer bag slots are free

Kept although new: 辅助品 (type 0x400: 回城卷, 红药 / 蓝药, 胡萝卜汁 ... what the line buys), 任务品 / 任务触发道具
(a quest of this batch may still need them) and ItemLib `important` items. Everything else new is a drop of the
fields and mazes. clean walks to the shop only on map 1 (逍遥村); elsewhere it only drops the untradable ones.
"""
import json
import sys

KEEP_TYPES = {0x400, 0x2000, 0x824}      # 辅助品 (bought drinks / scrolls), 任务品, 任务触发道具
VILLAGE, SHOP_XY = 1, (1338, 1155)


def snapshot_file(name):
    from common import LOGS
    return LOGS / 'master_bag' / f'{name}.json'


def load_kinds(name):
    try:
        return set(json.loads(snapshot_file(name).read_text(encoding='utf-8'))['kinds'])
    except (OSError, ValueError, KeyError):
        return None


def new_slots(bag, kinds, items):
    """(sell, drop): bag slots of item kinds not in the snapshot and not kept; unknown item ids are left alone."""
    sell, drop = [], []
    for s in bag:
        it = items.get(s.item_id)
        if s.item_id in kinds or it is None or it.type in KEEP_TYPES or it.important:
            continue
        (sell if it.tradable else drop).append(s)
    return sell, drop


def snapshot(name):
    import trial_run as t
    from factory.items import load_items
    from provisioner import world as w
    if load_kinds(name) is not None:
        t.say(f'[{name}] 背包记录已有（{snapshot_file(name).name}），不重记')
        return
    items = load_items()
    bag = w.read_bag(t.Client(name).mem)
    kinds = sorted({s.item_id for s in bag})
    path = snapshot_file(name)
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({'kinds': kinds, 'names': {i: items[i].name if i in items else '' for i in kinds}},
                               ensure_ascii=False, indent=1), encoding='utf-8')
    t.say(f'[{name}] 记下背包 {len(kinds)} 种物品（{len(bag)} 格）: {[items[i].name for i in kinds if i in items]}')


def clean(name, if_free=None):
    import struct
    import trial_run as t
    from drop_prank import OP_DROP
    from factory.items import load_items
    from factory.supply import PETSHOP, ShopClient
    from provisioner import log, world as w
    from zhuanzhi_finish import walk
    kinds = load_kinds(name)
    if kinds is None:
        t.say(f'[{name}] 没有背包记录，不清理（先 snapshot）')
        return
    c = t.Client(name)
    bag, cap = w.read_bag(c.mem), w.read_bag_capacity(c.mem)
    if if_free is not None and cap - len(bag) > if_free:
        return
    items = load_items()
    sell, drop = new_slots(bag, kinds, items)
    nm = lambda s: items[s.item_id].name          # noqa: E731
    gold = w.read_gold(c.mem)
    if sell and c.world().map_id == VILLAGE:
        walk(c, VILLAGE, SHOP_XY, '宠物商人小美')
        shop = ShopClient(c.game, c.mem, log.for_account(name))
        shop.sell(PETSHOP, sell)
        shop.close()
        left = {(s.slot, s.item_id) for s in w.read_bag(c.mem)}
        drop += [s for s in sell if (s.slot, s.item_id) in left]       # the shop refused it: drop it like the rest
    for s in drop:
        c.game.send(OP_DROP, struct.pack('<IBBH', 0, 0, s.slot, s.quantity))
        t.wait(lambda: not any(x.slot == s.slot and x.item_id == s.item_id for x in w.read_bag(c.mem)), 5,
               f'{name} 丢掉 {nm(s)}')
    t.say(f'[{name}] 背包清理：卖 {[nm(s) for s in sell if s not in drop]}，丢 {[nm(s) for s in drop]}；'
          f'金币 {gold} -> {w.read_gold(c.mem)}，背包 {len(bag)} -> {len(w.read_bag(c.mem))}/{cap}')


def main(argv):
    op, name, *rest = argv
    if op == 'snapshot':
        snapshot(name)
    elif op == 'clean':
        clean(name, int(rest[1]) if rest[:1] == ['--if-free'] else None)
    else:
        raise SystemExit(__doc__)


if __name__ == '__main__':
    import trial_run as t
    try:
        main(sys.argv[1:])
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
