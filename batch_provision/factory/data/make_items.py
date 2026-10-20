r"""Regenerate items.csv from the client's unpacked ResLib (ItemLib.csv, GBK).

    python factory/data/make_items.py D:\Codes\Gemini_Prj\smsm2_game\unpacked_game_data\ResLib

items.csv = every ItemLib item with a price (the shop pays half of it), for factory/items.py: the sell rule and the
bag inventory. Columns: item_id, type (EItemType, luas/game_define.lua), quality (0 灰 1 白 2 绿 3 蓝 4 橙 ...),
price, tradable (1 = ItemLib -1 可交易), important (ItemLib 重要物品: the client asks once more before selling; not a
sell ban), name.
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
    out = []
    for r in rows(lib / 'ItemLib.csv')[1:]:
        try:
            item, kind, price, quality = int(r[0]), int(r[1]), int(r[3]), int(r[16])
            tradable, important = r[18].strip() == '-1', r[19].strip() == '1'
        except (ValueError, IndexError):
            continue
        if price > 0:
            out.append((item, kind, quality, price, int(tradable), int(important), r[17].strip()))
    dest = Path(__file__).with_name('items.csv')
    with dest.open('w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(('item_id', 'type', 'quality', 'price', 'tradable', 'important', 'name'))
        w.writerows(sorted(out))
    print(f'{len(out)} 种物品 -> {dest}')


if __name__ == '__main__':
    main()
