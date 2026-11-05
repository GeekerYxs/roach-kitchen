r"""Regenerate potions.csv from the client's unpacked ResLib.

    python research/shitu/data/make_potions.py D:\Codes\Gemini_Prj\smsm2_game\unpacked_game_data\ResLib

potions.csv = every item in AutoUseItemID.csv (the items the server drinks by itself after a battle, player and pet)
that really restores something, per ItemProp.csv: PropID 25797 = 生命, 26050 = 法力, 26432 = 宠物忠诚 (PropValue = points
per item). 2026-11-05 SUPPLY_DESIGN.md §2.1: the table's 补魔法 rows hold 63955 鸡蛋饼干 (忠诚) and 63956-63959
(script items, no restore), so the AutoUseItemID class is not trusted; the ItemProp effect decides the kind.
Columns: item_id, kind (hp / mp / loyal), points, name. master_supply.py counts a master's bag with it.
"""
import csv
import io
import sys
from pathlib import Path

KINDS = {25797: 'hp', 26050: 'mp', 26432: 'loyal'}


def rows(path):
    text = Path(path).read_bytes().decode('gbk', errors='replace')
    return [r for r in csv.reader(io.StringIO(text)) if r and not r[0].startswith('//')]


def potions(auto_use, props, names):
    """auto_use: AutoUseItemID rows (class, item); props: ItemProp rows; names: {item: name} -> sorted rows."""
    ids = set()
    for r in auto_use:
        try:
            ids.add(int(r[1]))
        except (ValueError, IndexError):
            continue
    out = {}
    for r in props:
        try:
            item, prop, value = int(r[0]), int(r[4]), int(r[5])
        except (ValueError, IndexError):
            continue
        if item in ids and prop in KINDS and value > 0:
            out[item] = (item, KINDS[prop], value, names.get(item, ''))
    return sorted(out.values())


def main():
    lib = Path(sys.argv[1])
    names = {}
    for r in rows(lib / 'ItemLib.csv')[1:]:
        try:
            names[int(r[0])] = r[17].strip()
        except (ValueError, IndexError):
            continue
    out = potions(rows(lib / 'AutoUseItemID.csv'), rows(lib / 'ItemProp.csv')[1:], names)
    dest = Path(__file__).with_name('potions.csv')
    with dest.open('w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(('item_id', 'kind', 'points', 'name'))
        w.writerows(out)
    print(f'{len(out)} 种药 -> {dest}')


if __name__ == '__main__':
    main()
