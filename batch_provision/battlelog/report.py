"""Stage 4: analysis of the battle database -> logs/battlelog/report.md (python -m battlelog report).

Exp is normalised to single exp (exp / x_exp) so doubled and plain battles compare; an hour = fight + patrol of
each battle (patrols over MAX_PATROL seconds are pauses and left out). Only battles with a result and a known own
level count. Pure SQL + Python over the rows, no game access.
"""
import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

MAX_PATROL = 120.0
MIN_BATTLES = 30            # a (map, level) cell needs this many battles to be shown


def rows(db):
    sql = ('select role, map_id, level, monster_levels, exp, x_exp, potential, x_potential, pet_exp, fight_s,'
           ' patrol_s, own_dead, own_pet_dead, escaped, items, quiz_count, quiz_s from battles'
           ' where end_tick is not null and level is not null and exp is not null')
    for r in db.execute(sql):
        (role, m, lv, ml, exp, xe, pot, xp, pexp, f, pa, dead, pdead, esc, items, qc, qs) = r
        mons = [int(x) for x in (ml or '').split()]
        cycle = (f or 0) + (pa if pa is not None and pa <= MAX_PATROL else 0)
        yield dict(role=role, map=m, level=lv, mons=mons, exp=exp / (xe or 1), raw_exp=exp, x_exp=xe or 1,
                   potential=(pot or 0) / (xp or 1), pet_exp=pexp or 0, cycle=cycle, fight=f or 0,
                   dead=dead or 0, pet_dead=pdead or 0, escaped=esc or 0, items=json.loads(items or '[]'),
                   quiz=qc or 0, quiz_s=qs or 0.0)


def item_names(path):
    out = {}
    with open(path, encoding='utf-8') as f:
        for r in csv.reader(f):
            if r and r[0].isdigit():
                out[int(r[0])] = r[-1]
    return out


def gap_of(d):
    return round(d['level'] - sum(d['mons']) / len(d['mons']))


def per_hour(cells):
    t = sum(c['cycle'] for c in cells)
    return sum(c['exp'] for c in cells) / t * 3600 if t else 0.0


def build(db, items_csv, map_names=None):
    """-> report text (markdown)."""
    from . import live
    live.init(db)                               # the memory columns exist even if the live recorder never ran
    names = item_names(items_csv)
    npc = dict(db.execute('select npc_id, name from npcs'))
    mname = (lambda m: (map_names or {}).get(m, str(m)))
    data = list(rows(db))
    out = [f'# 战斗记录分析（{len(data)} 场有结算和等级）', '',
           '经验一律换算成单倍（开了人物双倍的场次经验除以 2）；每小时 = 战斗 + 巡逻时间（巡逻超过 '
           f'{MAX_PATROL:.0f} 秒算暂停，不计）。每格至少 {MIN_BATTLES} 场才列出。', '']

    by = defaultdict(list)
    for d in data:
        by[(d['map'], d['level'])].append(d)

    # 1. best map per level
    out += ['## 1. 每个等级哪张图最快（单倍经验/小时）', '', '| 等级 | 最快的图 | 万经验/时 | 次快 | 万经验/时 | 怪物等级 |',
            '|---|---|---|---|---|---|']
    levels = sorted({lv for _, lv in by})
    for lv in levels:
        cand = sorted(((per_hour(c), m, c) for (m, l), c in by.items() if l == lv and len(c) >= MIN_BATTLES),
                      key=lambda x: -x[0])
        if not cand or cand[0][0] < 1000:         # roles far above every map they fought on (~0 exp)
            continue
        a = cand[0]
        b = cand[1] if len(cand) > 1 else None
        mons = [x for c in a[2] for x in c['mons']]
        span = f'{min(mons)}~{max(mons)}' if mons else '?'
        out.append(f'| {lv} | {mname(a[1])} | {a[0] / 1e4:.1f} | {mname(b[1]) if b else "-"} | '
                   f'{b[0] / 1e4 if b else 0:.1f} | {span} |')

    # 2. level gap curve: per map, exp per battle vs that map's best level; then the median over maps
    out += ['', '## 2. 等级差曲线（人物等级 − 怪物平均等级）', '',
            '先在每张图里算"这场单倍经验 ÷ 这张图各等级中位数的最大值"，再取各图的中位数（每图每格至少 '
            f'{MIN_BATTLES} 场），避免不同地图混在一起。', '', '| 等级差 | 地图数 | 场数 | 相对满额 |', '|---|---|---|---|']
    best = {}
    for (m, lv), cells in by.items():
        if len(cells) >= MIN_BATTLES:
            best[m] = max(best.get(m, 0), statistics.median(c['exp'] for c in cells))
    per_map = defaultdict(list)                 # (gap, map) -> ratios
    for d in data:
        if d['mons'] and best.get(d['map']):
            per_map[(gap_of(d), d['map'])].append(d['exp'] / best[d['map']])
    curve = defaultdict(list)
    for (gap, m), v in per_map.items():
        if len(v) >= MIN_BATTLES:
            curve[gap].append((statistics.median(v), len(v)))
    for gap in sorted(curve):
        v = curve[gap]
        out.append(f'| {gap:+d} | {len(v)} | {sum(n for _, n in v)} | {statistics.median(r for r, _ in v):.0%} |')

    # 3. doubles: same map and level, with vs without the character double
    out += ['', '## 3. 人物双倍的效果（同一张图、同一个等级里比）', '',
            '每个（地图, 等级）格子里开和不开人物双倍各至少 '
            f'{MIN_BATTLES} 场时，算"开 ÷ 不开"的中位数之比，再取各格子的中位数。', '',
            '| 格子数 | 人物经验 | 宠物经验 | 潜能 |', '|---|---|---|---|']
    ratios = defaultdict(list)
    for cells in by.values():
        one = [c for c in cells if c['x_exp'] == 1]
        two = [c for c in cells if c['x_exp'] == 2]
        if len(one) >= MIN_BATTLES and len(two) >= MIN_BATTLES:
            for key in ('raw_exp', 'pet_exp', 'potential'):
                m1 = statistics.median(c[key] for c in one)
                if m1:
                    ratios[key].append(statistics.median(c[key] for c in two) / m1)
    if ratios['raw_exp']:
        f = (lambda k: f'{statistics.median(ratios[k]):.2f} 倍' if ratios[k] else '-')
        out.append(f'| {len(ratios["raw_exp"])} | {f("raw_exp")} | {f("pet_exp")} | {f("potential")} |')
    else:
        out.append('| 0 | 同一格子里两种都够多的还没有 | | |')

    # 4. deaths / escapes / quiz per map
    out += ['', '## 4. 各图的阵亡、逃跑、答题打断', '',
            '答题只有实时记录（一键战斗记录.cmd）跑着时才有；历史监听文件里看不到。', '',
            '| 地图 | 场数 | 本人阵亡 | 宠物阵亡 | 逃跑成功 | 答题次数 | 答题耗时(秒) | 平均战斗秒 |', '|---|---|---|---|---|---|---|---|']
    maps = defaultdict(list)
    for d in data:
        maps[d['map']].append(d)
    for m, v in sorted(maps.items(), key=lambda kv: -len(kv[1]))[:25]:
        out.append(f'| {mname(m)} | {len(v)} | {sum(d["dead"] for d in v)} | {sum(d["pet_dead"] for d in v)} | '
                   f'{sum(d["escaped"] for d in v)} | {sum(d["quiz"] for d in v)} | {sum(d["quiz_s"] for d in v):.0f} | '
                   f'{statistics.mean(d["fight"] for d in v):.1f} |')

    # 5. drops
    out += ['', '## 5. 各图掉落（每 100 场）', '']
    for m, v in sorted(maps.items(), key=lambda kv: -len(kv[1]))[:12]:
        c = Counter()
        for d in v:
            for item_id, qty, _slot in d['items']:
                c[item_id] += qty
        if not c:
            continue
        top = '、'.join(f'{names.get(i, i)} {n * 100 / len(v):.1f}' for i, n in c.most_common(8))
        out.append(f'- **{mname(m)}**（{len(v)} 场）：{top}')

    # 6. monsters per map
    out += ['', '## 6. 各图的怪', '']
    for m, ids in db.execute('select map_id, group_concat(monsters, "|") from (select map_id, monsters from battles'
                             ' where monsters is not null limit 200000) group by map_id'):
        c = Counter()
        for part in (ids or '').split('|'):
            for npc_id, level, *_ in json.loads(part or '[]'):
                c[(npc_id, level)] += 1
        if sum(c.values()) < 50:
            continue
        top = '、'.join(f'{npc.get(i, i)}{lv}级' for (i, lv), _ in c.most_common(6))
        out.append(f'- **{mname(m)}**：{top}')
    return '\n'.join(out) + '\n'


def map_names(path):
    """Client ResLib/MapNameLib (id, kind, name) -> {id: name}; {} when the file is missing."""
    out = {}
    if Path(path).is_file():
        with open(path, encoding='utf-8') as f:
            for r in csv.reader(f):
                if len(r) >= 3 and r[0].isdigit():
                    out[int(r[0])] = r[2]
    return out
