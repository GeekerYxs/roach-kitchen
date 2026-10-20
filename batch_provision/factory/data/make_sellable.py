r"""Regenerate sellable.csv from the client's unpacked ResLib (ItemLib.csv + CSItemList.csv, GBK).

    python factory/data/make_sellable.py D:\Codes\Gemini_Prj\smsm2_game\unpacked_game_data\ResLib

sellable.csv = every item in one of the categories the game's own 自动卖店 offers (luas/auto_sell.lua: an item is
sold when its ItemLib type AND quality match a checked CSItemList row), minus the items ItemLib marks 重要物品.
Columns: item_id, type, quality, price (ItemLib price; the shop pays half), name.
"""
import csv
import io
import sys
from pathlib import Path


def rows(path):
    text = Path(path).read_bytes().decode('gbk', errors='replace')
    return [r for r in csv.reader(io.StringIO(text)) if r and not r[0].startswith('//')]


def main():
    lib = Path(sys.argv[1])
    cats = {(int(r[1]), int(r[2])) for r in rows(lib / 'CSItemList.csv')}
    out = []
    for r in rows(lib / 'ItemLib.csv')[1:]:
        try:
            item, kind, price, quality, important = int(r[0]), int(r[1]), int(r[3]), int(r[16]), r[19].strip()
        except (ValueError, IndexError):
            continue
        if (kind, quality) in cats and important != '1':
            out.append((item, kind, quality, price, r[17].strip()))
    dest = Path(__file__).with_name('sellable.csv')
    with dest.open('w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(('item_id', 'type', 'quality', 'price', 'name'))
        w.writerows(sorted(out))
    print(f'{len(out)} 种物品 -> {dest}')


if __name__ == '__main__':
    main()
