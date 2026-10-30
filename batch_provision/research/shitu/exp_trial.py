"""Exp-map trial (2026-10-29, EXP_MAP_TRIAL.md): which map is best at which level, per team, read-only.

    python -X utf8 research/shitu/exp_trial.py [--teams oa,ob,oc] [--batch 1] [--db] [--md out.md]

--db reads logs/battlelog/battles.sqlite (python -m battlelog import) instead of the expwatch CSV.

Sources: the expwatch per-battle CSV (r4_stats.CSV, one row per apprentice and battle, with enemy_levels since
2026-10-29) and the step checkpoints of r5_compare (logs/<LOGID>_line.json). Per team and (map, level): battles,
enemies per battle, the monsters' level range and rounded mean (the server's L_eff, BATTLELOG.md 3.2), dL = level -
L_eff, median exp per battle, mean cycle (battle start to next start: fight + walking), exp per minute; then per
level the map with the most exp per minute and the minutes each team spent per level (first battle at the level to
first battle at the next, all maps and walking included).
"""
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import r4_stats
import r5_compare
from line import plan

MAPS = {**r4_stats.MAPS, 279: '通天塔路口', 1: '逍遥村西区', 271: '菜鸟训练营'}
TRAIN = {651, 555, 600, 700, 750, 280, 281}          # the leveling mazes (the rest = battles on the way)


def l_eff(levels):
    """Server's monster level of a battle: the rounded mean (floor(mean + 0.5)), None when not read."""
    return int(sum(levels) / len(levels) + 0.5) if levels else None


def rows(names, since, path=r4_stats.CSV):
    """Battles of these roles after `since` -> dicts (enemy_levels as a tuple of ints)."""
    import csv
    out = []
    with open(path, encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f):
            if r['role'] not in names or r['gain'] in ('', 'None') or float(r['start']) < since:
                continue
            lv = tuple(int(x) for x in (r.get('enemy_levels') or '').split())
            out.append(dict(role=r['role'], start=float(r['start']), level=int(r['level']),
                            level_after=int(r['level_after']), map=int(r['map_id']), gain=int(r['gain']),
                            fight=float(r['fight']), cycle=float(r['cycle']) if r['cycle'] not in ('', 'None') else None,
                            enemies=int(r.get('enemies') or 0), enemy_levels=lv))
    return out


DB = r4_stats.ROOT / 'logs' / 'battlelog' / 'battles.sqlite'
MAX_CYCLE = 120              # a gap longer than this between two battles is a trip / quest, not walking in the map


def rows_db(names, since, path=DB):
    """The same rows from the battle log (python -m battlelog import: every armed apprentice's tap, so batches the exp
    monitor missed are there too). cycle = next battle's start - this start (None past MAX_CYCLE or for the last);
    level_after taken from the next battle when the log has none."""
    import sqlite3
    db = sqlite3.connect(path)
    q = ('select role, start_time, fight_s, map_id, level, level_after, exp, monster_count, monster_levels '
         f'from battles where role in ({",".join("?" * len(names))}) and start_time >= ? and exp is not null and level is not null '
         'order by role, start_time')
    raw = db.execute(q, (*names, since)).fetchall()
    db.close()
    out = []
    for i, (role, start, fight, m, lv, after, exp, count, levels) in enumerate(raw):
        nxt = raw[i + 1] if i + 1 < len(raw) and raw[i + 1][0] == role else None
        gap = nxt[1] - start if nxt else None
        out.append(dict(role=role, start=start, level=lv, level_after=after or (nxt[4] if nxt else lv), map=m,
                        gain=exp, fight=fight or 0.0, cycle=gap if gap is not None and gap <= MAX_CYCLE else None,
                        enemies=count or 0, enemy_levels=tuple(int(x) for x in (levels or '').split())))
    return out


def by_map_level(rs):
    """{(map, level): summary} over battles that did not level up (a level-up battle's gain spans two levels)."""
    g = defaultdict(list)
    for r in rs:
        if r['level'] == r['level_after'] and r['gain'] > 0:
            g[(r['map'], r['level'])].append(r)
    out = {}
    for (m, lv), b in g.items():
        cyc = [x['cycle'] for x in b if x['cycle']]
        mons = [x for x in b if x['enemy_levels']]
        effs = [l_eff(x['enemy_levels']) for x in mons]
        gain = statistics.median(x['gain'] for x in b)
        cycle = statistics.fmean(cyc) if cyc else None
        out[(m, lv)] = dict(n=len(b), gain=gain, mean_gain=statistics.fmean(x['gain'] for x in b),
                            fight=statistics.fmean(x['fight'] for x in b), cycle=cycle,
                            per_min=(statistics.fmean(x['gain'] for x in b) / cycle * 60) if cycle else None,
                            enemies=statistics.fmean(x['enemies'] for x in b if x['enemies']) if any(
                                x['enemies'] for x in b) else None,
                            mon_lo=min(min(x['enemy_levels']) for x in mons) if mons else None,
                            mon_hi=max(max(x['enemy_levels']) for x in mons) if mons else None,
                            l_eff=statistics.median(effs) if effs else None)
    return out


def level_minutes(rs):
    """{level: minutes} per role averaged: first battle at level L to first battle at L+1 (all maps, walking,
    quests in between included)."""
    first = defaultdict(dict)
    for r in sorted(rs, key=lambda x: x['start']):
        first[r['role']].setdefault(r['level'], r['start'])
    per = defaultdict(list)
    for role, f in first.items():
        for lv, t0 in f.items():
            if lv + 1 in f:
                per[lv].append((f[lv + 1] - t0) / 60)
    return {lv: statistics.fmean(v) for lv, v in per.items()}


def best_maps(tables):
    """tables {team: by_map_level()} -> {level: (team, map, per_min)} the fastest training map seen at each level."""
    best = {}
    for team, t in tables.items():
        for (m, lv), s in t.items():
            if m in TRAIN and s['per_min'] and s['n'] >= 8 and (lv not in best or s['per_min'] > best[lv][2]):
                best[lv] = (team, m, s['per_min'])
    return best


def events(logid):
    import json
    try:
        return json.loads((r5_compare.LOGS / f'{logid}_line.json').read_text(encoding='utf-8')).get('events', [])
    except (OSError, ValueError):
        return []


def fmt(v, spec='.0f'):
    return '-' if v is None else format(v, spec)


def markdown(teams, batch, source=rows):
    tables, mins, out = {}, {}, []
    for team in teams:
        b = plan.Batch(team, batch)
        start = r5_compare.batch_start(b.logid, events(b.logid), team=team, batch=batch)
        rs = source(set(b.all_names), start or 0)
        tables[team], mins[team] = by_map_level(rs), level_minutes(rs)
        out += [f'### 队 {team}（{b.master}，{", ".join(b.all_names)}）', '',
                '| 等级 | 地图 | 场数 | 怪/场 | 怪物等级 | L_eff | ΔL | 每场经验(中位) | 一场秒(含走路) | 每分钟经验 |',
                '|---|---|---|---|---|---|---|---|---|---|']
        for (m, lv), s in sorted(tables[team].items(), key=lambda x: (x[0][1], x[0][0])):
            if m not in TRAIN or s['n'] < 3:
                continue
            mon = f'{s["mon_lo"]}–{s["mon_hi"]}' if s['mon_lo'] is not None else '-'
            dl = f'{lv - s["l_eff"]:+.0f}' if s['l_eff'] is not None else '-'
            out.append(f'| {lv} | {MAPS.get(m, m)} ({m}) | {s["n"]} | {fmt(s["enemies"], ".1f")} | {mon} | '
                       f'{fmt(s["l_eff"])} | {dl} | {s["gain"]:.0f} | {fmt(s["cycle"], ".1f")} | {fmt(s["per_min"])} |')
        out.append('')
    out += ['### 每级用时（分钟，第一次在这一级打怪 → 第一次在下一级打怪，含走路和中间的任务）', '',
            '| 等级 | ' + ' | '.join(teams) + ' |', '|---|' + '---|' * len(teams)]
    levels = sorted({lv for t in mins.values() for lv in t})
    for lv in levels:
        out.append(f'| {lv} | ' + ' | '.join(fmt(mins[t].get(lv), '.1f') for t in teams) + ' |')
    out.append('| 合计 | ' + ' | '.join(f'{sum(mins[t].values()):.0f}' for t in teams) + ' |')
    out += ['', '### 每级最快的练级图（三队里每分钟经验最高，≥ 8 场）', '', '| 等级 | 地图 | 队 | 每分钟经验 |',
            '|---|---|---|---|']
    for lv, (team, m, pm) in sorted(best_maps(tables).items()):
        out.append(f'| {lv} | {MAPS.get(m, m)} ({m}) | {team} | {pm:.0f} |')
    return '\n'.join(out)


if __name__ == '__main__':
    argv = sys.argv[1:]
    teams = r5_compare.arg(argv, '--teams', 'oa,ob,oc').split(',')
    text = markdown(teams, int(r5_compare.arg(argv, '--batch', '1')), rows_db if '--db' in argv else rows)
    md = r5_compare.arg(argv, '--md', None)
    if md:
        Path(md).write_text(text + '\n', encoding='utf-8')
    print(text)
