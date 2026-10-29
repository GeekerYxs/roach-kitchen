"""Which bag slots the 禁锢 team sells at 钱德勒 (user 2026-10-29): everything the farm map drops, plus the
南方联军将领勋章 that 银狐王勇 hands out per 10 crystals. Tradable only (the shop refuses 不可交易).

  - MAP_DROPS: drops known before the drop log existed, always sold.
  - any other tradable item id that research/jingu/drops.py SAW DROPPING in the farm map (logs/drops.csv): sold,
    whatever kind (blue/green equipment, 葫芦, 技能石 ...). The same kind brought from elsewhere goes too; put what
    must stay into NEVER (the first sale took 神射之火枪, which the user needs).
  - junk wherever it came from (user 2026-10-29 01:3x: 笔杆, 蜻蜓的壳, 动物皮毛C, 葫芦, 破碎的碗, 虎皮, 大贱豪的剑, 屠刀,
    白色装备, 生产制造的配方): the factory junk types 杂物 / 配方 / 技能石 / 残骸 (factory.items.SELL_TYPES) and
    white / green equipment. Items marked 重要 are kept (e.g. 赤炎混沌以太晶石 is a 杂物 but 重要).
  - NEVER: kept whatever a rule says.
"""
import csv
from pathlib import Path

from factory import items as fi

MAP_DROPS = {
    11354: '幽冥磷火', 11355: '黑暗之血', 11356: '妖兽骨粉', 65275: '神兽之齿', 65280: '百变根茎', 65270: '不朽灵魂',
}
MEDAL = {28030: '南方联军将领勋章'}
# 2026-10-29: the 葫芦 are type 0x400 辅助品, not 杂物, so the junk types missed them (user: sell or drop all three)
GOURDS = {31801: '紫金红葫芦', 31802: '黄玉葫芦', 31803: '碧玉葫芦'}
NEVER = {670: '神射之火枪', 4475: '圣母之软甲'}      # user 2026-10-29: keep, even if a rule above ever matches
BLUE = 3
DROPS_CSV = Path(__file__).resolve().parent / 'logs' / 'drops.csv'


def seen_drops(path=DROPS_CSV):
    """Item ids drops.py logged as dropping in the farm map (columns: t, role, item, name, n)."""
    if not path.is_file():
        return frozenset()
    with open(path, encoding='utf-8', newline='') as f:
        return frozenset(int(row[2]) for row in csv.reader(f) if len(row) >= 3 and row[2].isdigit())


def why(it, dropped=frozenset()):
    if it is None or not it.tradable or it.item_id in NEVER:
        return None
    if it.item_id in MEDAL:
        return '勋章'
    if it.item_id in GOURDS:
        return '葫芦'
    if it.item_id in MAP_DROPS or it.item_id in dropped:
        return '地图掉落'
    if it.important:
        return None
    if it.type in fi.SELL_TYPES:
        return fi.type_name(it.type)
    if it.type in fi.EQUIP_TYPES and it.quality < BLUE:
        return f'{fi.QUALITY_NAMES[it.quality]}装'
    return None


def to_sell(bag, table, dropped=None):
    dropped = seen_drops() if dropped is None else dropped
    return [(s, w) for s in bag if (w := why(table.get(s.item_id), dropped))]
