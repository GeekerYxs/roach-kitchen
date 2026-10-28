"""Exp statistics per map and level for the 师徒 runs, from the exp monitor's per-battle CSV (read-only).

    python -X utf8 research/shitu/r4_stats.py [csv] [--md out.md]
        default csv: batch_provision/logs/expwatch/shitu_battles.csv (python -m expwatch expwatch_shitu.toml)

Per (map, level): battles, apprentices, mean live enemies at the start (0 = not recorded), mean exp per battle, mean fight seconds, mean cycle seconds (battle start to
next battle start, i.e. fight + walking), exp per minute (= mean gain / mean cycle), minutes per level (exp table
need / exp per minute). Double exp shows up as a higher gain at the same map and level; the battles CSV has no flag
for it, so compare rows of the same map / level over time when tuning.
"""
import csv
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
CSV = ROOT / 'logs' / 'expwatch' / 'shitu_battles.csv'
TABLE = ROOT / 'expwatch' / 'explib.csv'
MAPS = {651: '阴森古井', 130: '夕阳草原', 555: '轮回之城', 600: '暗影迷城', 700: '八阵图', 750: '遗忘洞穴',
        280: '通天塔一区', 281: '通天塔二区', 141: '无尽平原2区', 142: '无尽平原3区', 140: '无尽平原1区',
        170: '苦无沙漠1区', 1000: '巨石之城西部遗址', 650: '逍遥古迹', 82: '平静海岸3区', 81: '平静海岸2区', 20: '龙之都外城'}


def load_table():
    with open(TABLE, encoding='utf-8', newline='') as f:
        return {int(r['level']): int(r['playerexp']) for r in csv.DictReader(f)}


def rows(path):
    with open(path, encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f):
            if r['gain'] in ('', 'None'):
                continue
            yield dict(role=r['role'], level=int(r['level']), map=int(r['map_id']), gain=int(r['gain']),
                       fight=float(r['fight']), cycle=float(r['cycle']) if r['cycle'] not in ('', 'None') else None,
                       enemies=int(r.get('enemies') or 0))


def summarize(rs, table):
    """[(map, level, n, roles, gain, fight, cycle, per_min, min_per_level)] sorted by level then map."""
    g = defaultdict(list)
    for r in rs:
        g[(r['map'], r['level'])].append(r)
    out = []
    for (m, lv), b in g.items():
        gain = sum(x['gain'] for x in b) / len(b)
        fight = sum(x['fight'] for x in b) / len(b)
        cyc = [x['cycle'] for x in b if x['cycle']]
        cycle = sum(cyc) / len(cyc) if cyc else None
        per_min = gain / cycle * 60 if cycle else None
        need = table.get(lv)
        mpl = need / per_min if per_min and need else None
        en = [x['enemies'] for x in b if x['enemies']]
        enemies = sum(en) / len(en) if en else None
        out.append((m, lv, len(b), len({x['role'] for x in b}), gain, fight, cycle, per_min, mpl, enemies))
    return sorted(out, key=lambda x: (x[1], x[0]))


def fmt(v, spec):
    return '-' if v is None else format(v, spec)


def markdown(summary):
    lines = ['| 等级 | 地图 | 场数 | 号数 | 每场怪数 | 每场经验 | 每只怪经验 | 战斗秒 | 一场秒(含走路) | 每分钟经验 | 升一级分钟 |',
             '|---|---|---|---|---|---|---|---|---|---|---|']
    for m, lv, n, k, gain, fight, cycle, pm, mpl, en in summary:
        lines.append(f'| {lv} | {MAPS.get(m, m)} ({m}) | {n} | {k} | {fmt(en, ".1f")} | {gain:.0f} | '
                     f'{fmt(gain / en if en else None, ".0f")} | {fight:.1f} | {fmt(cycle, ".1f")} | '
                     f'{fmt(pm, ".0f")} | {fmt(mpl, ".1f")} |')
    return '\n'.join(lines)


if __name__ == '__main__':
    args = sys.argv[1:]
    out = None
    if '--md' in args:
        i = args.index('--md')
        out = Path(args[i + 1])
        del args[i:i + 2]
    path = Path(args[0]) if args else CSV
    text = markdown(summarize(list(rows(path)), load_table()))
    print(text)
    if out:
        out.write_text(text + '\n', encoding='utf-8')
