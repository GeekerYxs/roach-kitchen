"""What may be sold at a shop, and a read-only bag inventory to check that rule on real bags.

Entry (read only, sends nothing): python -m factory.items [角色名 ...]   (no name = every window of this tool)
Prints every bag slot with name, type, quality, shop price (half the ItemLib price) and 卖 / 留 with the reason.

Sell rule (user, 2026-10-20: sell equipment, junk and EVERY 技能石 of leaders and alts, not a fixed item list):
  sold     equipment (types 0x101..0x118), 技能石 0x821 (all qualities), 配方 0x823, 杂物 0x1000, 残骸 0x82B
  kept     everything else by type: 辅助品 0x400 holds the supplies we buy, 美味小强料理, 小肉林 / 地瓜 / 香水;
           任务品 0x2000 holds the quest-78 legs / rumps
  kept     items in `keep` (the supplies a station buys), items without a price, items not in items.csv
  kept     bound items (ItemLib 重要 AND not tradable: event rewards like 香蕉车 / 羽翼材料 / 冒险精气, the shop pays 1),
           except 技能石
  leaders  keep blue-or-better equipment (quality >= 3; user 2026-10-20: e.g. the spare blue 狂暴之球棒 of 真男人r1-3)
Alts (factory/sell.py) also take off what they wear (the 专打屁屁扳手) and sell it.
Pure decisions (tests/test_factory_items.py).
"""
import csv
import sys
from dataclasses import dataclass
from pathlib import Path

ITEMS_CSV = Path(__file__).with_name('data') / 'items.csv'

EQUIP_TYPES = range(0x101, 0x119)
SELL_TYPES = {0x821, 0x823, 0x1000, 0x82B}
LEADER_KEEP_QUALITY = 3         # leaders keep blue-or-better equipment (user, 2026-10-20)

TYPE_NAMES = {
    0x101: '帽子', 0x102: '口罩', 0x103: '武器', 0x104: '项链', 0x105: '戒指', 0x106: '上衣', 0x107: '裤子',
    0x108: '腰带', 0x109: '靴子', 0x10A: '交通工具', 0x10B: '交通工具', 0x10C: '交通工具', 0x10D: '交通工具',
    0x10E: '圣物', 0x111: '时装', 0x112: '翅膀', 0x113: '宠物武器', 0x114: '宠物护腕', 0x115: '项圈', 0x116: '宠物铠甲',
    0x117: '宠物腰带', 0x118: '宠物背心', 0x200: '投掷品', 0x400: '辅助品', 0x800: '特殊品', 0x801: '时效品',
    0x820: '宠物卡片', 0x821: '技能石', 0x822: '捕捉道具', 0x823: '配方', 0x824: '任务触发道具', 0x825: '交通工具模块',
    0x826: '传送道具', 0x827: '强化药剂', 0x828: '亲密度道具', 0x82A: '神骨碎片', 0x82B: '残骸', 0x1000: '杂物',
    0x2000: '任务品', 0x4000: '奖励品', 0x8000: '消耗品',
}
QUALITY_NAMES = {0: '灰', 1: '白', 2: '绿', 3: '蓝', 4: '橙', 5: '金', 6: '紫', 7: '红', 8: '青'}


@dataclass(frozen=True)
class Item:
    item_id: int
    type: int
    quality: int
    price: int
    tradable: bool
    important: bool
    name: str


_TABLE = None


def table():
    """items.csv loaded once per process (observe() needs it for every alt, every few seconds)."""
    global _TABLE
    if _TABLE is None:
        _TABLE = load_items()
    return _TABLE


def load_items(path=ITEMS_CSV):
    """item_id -> Item for every priced item (factory/data/make_items.py)."""
    with open(path, encoding='utf-8', newline='') as f:
        return {int(r['item_id']): Item(int(r['item_id']), int(r['type']), int(r['quality']), int(r['price']),
                                        r['tradable'] == '1', r['important'] == '1', r['name'])
                for r in csv.DictReader(f)}


def type_name(t):
    return TYPE_NAMES.get(t, f'类型{t:#x}')


def verdict(item_id, items, keep=frozenset(), leader=False):
    """(sell?, reason) for one item id."""
    it = items.get(item_id)
    if it is None:
        return False, '物品表里没有（无价格）'
    if item_id in keep:
        return False, '补给品'
    if it.important and not it.tradable and it.type != 0x821:
        return False, '绑定物品（重要且不可交易）'
    if it.type in EQUIP_TYPES:
        if leader and it.quality >= LEADER_KEEP_QUALITY:
            return False, '队长的蓝色及以上装备'
        return True, type_name(it.type)
    if it.type in SELL_TYPES:
        return True, type_name(it.type)
    return False, f'{type_name(it.type)}不卖'


def sell_slots(bag, items, keep=frozenset(), leader=False, limit=None):
    """Bag slots to sell, in slot order (at most `limit`)."""
    out = [s for s in bag if verdict(s.item_id, items, keep, leader)[0]]
    return out if limit is None else out[:limit]


def worn_to_sell(equipment, items, leader=False):
    """Worn items (BagSlots, slot = equipment slot) the rule would sell once they are taken off."""
    return [e for e in equipment if verdict(e.item_id, items, leader=leader)[0]]


def junk_count(bag, equipment, items, keep=frozenset()):
    """Alt rule: bag slots to sell + worn items to take off and sell (0 = nothing left for the shop)."""
    return len(sell_slots(bag, items, keep)) + len(worn_to_sell(equipment, items))


def unequip_plan(equipment, bag, capacity, items):
    """[(equipment slot, free bag slot)] for the worn items an alt sells, while the bag has room."""
    used = {s.slot for s in bag}
    free = [i for i in range(capacity) if i not in used]
    return list(zip((e.slot for e in worn_to_sell(equipment, items)), free))


def shop_value(slots, items):
    """Gold the shop pays for these slots (half the ItemLib price, rounded down per piece)."""
    return sum(items[s.item_id].price // 2 * s.quantity for s in slots)


def inventory_lines(bag, items, keep=frozenset(), leader=False):
    """Human-readable lines for the inventory command."""
    lines = []
    for s in bag:
        sell, why = verdict(s.item_id, items, keep, leader)
        it = items.get(s.item_id)
        desc = (f'{it.name} [{type_name(it.type)} {QUALITY_NAMES.get(it.quality, it.quality)}'
                f'{" 重要" if it.important else ""}{"" if it.tradable else " 不可交易"}] 单价收 {it.price // 2}'
                if it else f'物品 {s.item_id}')
        lines.append(f'  第{s.slot:2d}格 {desc} ×{s.quantity}  -> {"卖" if sell else "留"}（{why}）')
    return lines


def main():
    from provisioner import log, procs
    from provisioner.memory import ProcessMemory
    from provisioner.world import read_bag, read_bag_capacity, read_gold

    from .config import ROOT
    from .supply import ITEM_NAMES

    names = set(sys.argv[1:])
    log.setup(ROOT / 'logs', prefix='items')
    logger = log.for_account('main')
    items = load_items()
    clients = [c for c in procs.discover(logger) if not names or c.name in names]
    if not clients:
        print('没有找到在线的角色窗口')
        return 2
    for c in clients:
        with ProcessMemory(c.session.pid, c.session.base) as mem:
            bag, cap, gold = read_bag(mem), read_bag_capacity(mem), read_gold(mem)
        if bag is None:
            print(f'{c.name}: 读不到背包')
            continue
        for leader in (True, False):
            sold = sell_slots(bag, items, set(ITEM_NAMES), leader)
            print(f'\n{c.name}（地图 {c.map_id}，金币 {gold}，背包 {len(bag)}/{cap}）按{"队长" if leader else "小号"}规则：'
                  f'卖 {len(sold)} 格，商店约付 {shop_value(sold, items)} 金币')
            if leader:
                print('\n'.join(inventory_lines(bag, items, set(ITEM_NAMES), True)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
