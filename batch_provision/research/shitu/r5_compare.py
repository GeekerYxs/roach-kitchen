"""Compare the teams of one v5 batch (round 5: which master is faster), read-only, markdown on stdout.

    python -X utf8 research/shitu/r5_compare.py [--batch 3] [--teams a,b,fei,tian] [--md out.md]

Sources: logs/<LOGID>_line.json (step checkpoints: the step ends at its「完成」event, starts at the previous one;
the first step starts at the first `== STEP` marker of logs/<LOGID>_line_make.log), the expwatch per-battle CSV
(r4_stats.CSV, rows of the team's apprentices after the batch started) and logs/sp_watch.csv (sp_watch.py).
"""
import csv
import json
import re
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

import r4_stats
from line import plan, route as R

HERE = Path(__file__).resolve().parent
LOGS = HERE / 'logs'
YEAR = time.localtime().tm_year
DONE = re.compile(r'^(\d\d-\d\d \d\d:\d\d:\d\d) (\S+) 完成')


def ts(text, year=YEAR):
    return time.mktime(time.strptime(f'{year}-{text}', '%Y-%m-%d %H:%M:%S'))


def step_times(events, start):
    """events of a _line.json + batch start epoch -> {step: (start, end)} for the finished steps (route order)."""
    out, prev = {}, start
    for e in events:
        m = DONE.match(e)
        if m and m.group(2) in R.NAMES:
            end = ts(m.group(1))
            out[m.group(2)] = (prev, end)
            prev = end
    return out


def batch_start(logid, events=(), team=None, batch=None, logs=LOGS):
    """Epoch the batch started: its「批次开始」event, else the first `== STEP` marker of the make log (date from the
    file's mtime day), else the controller's「[team] 第 N 批开始」line in logs/line_run*.log (round 5 batch 3 ran
    before either was written)."""
    for e in events:
        if e.endswith(' 批次开始'):
            return ts(e[:14])
    for c in sorted(logs.glob('line_run*.log')) if team else ():
        m = re.search(rf'^(\d\d:\d\d:\d\d) \[{re.escape(team)}\] 第 {batch} 批开始', c.read_text(encoding='utf-8',
                      errors='replace'), re.M)
        if m:
            return ts(time.strftime('%m-%d', time.localtime(c.stat().st_mtime)) + ' ' + m.group(1))
    p = logs / f'{logid}_line_make.log'
    try:
        text = p.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return None
    m = re.search(r'^== STEP \S+ (\d\d:\d\d:\d\d)', text, re.M)
    if not m:
        return None
    day = time.strftime('%m-%d', time.localtime(p.stat().st_mtime))
    return ts(f'{day} {m.group(1)}')


def retries(events):
    return sum('失败' in e for e in events)


def stage_of(name):
    return R.step(name).stage


def mins(sec):
    return '-' if sec is None else f'{sec / 60:.1f}'


def exp_rows(names, since, path=r4_stats.CSV):
    out = []
    with open(path, encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f):
            if r['role'] in names and r['gain'] not in ('', 'None') and float(r['start']) >= since:
                out.append(r)
    return out


def exp_by_map(rows):
    """{map: (battles, lv_min, lv_max, fight_s, cycle_s, exp_per_min)} (one battle = one row per apprentice: per
    apprentice exp per minute, averaged)."""
    g = defaultdict(list)
    for r in rows:
        g[int(r['map_id'])].append(r)
    out = {}
    for m, rs in g.items():
        gain = statistics.mean(int(r['gain']) for r in rs)
        fight = statistics.mean(float(r['fight']) for r in rs)
        cyc = [float(r['cycle']) for r in rs if r['cycle'] not in ('', 'None')]
        cycle = statistics.mean(cyc) if cyc else None
        lvs = [int(r['level']) for r in rs]
        out[m] = (len(rs) // max(1, len({r['role'] for r in rs})), min(lvs), max(lvs), fight, cycle,
                  gain / cycle * 60 if cycle else None)
    return out


def sp_summary(path=LOGS / 'sp_watch.csv'):
    by = defaultdict(lambda: ([], [], []))
    try:
        with open(path, encoding='utf-8', newline='') as f:
            for r in csv.DictReader(f):
                me, pet, bs = by[r['role']]
                if r['me_s']:
                    me.append(float(r['me_s']))
                if r['pet_s']:
                    pet.append(float(r['pet_s']))
                bs.append(float(r['battle_s']))
    except OSError:
        pass
    return by


def report(teams, batch):
    bs = {t: plan.Batch(t, batch) for t in teams}
    data = {}
    for t, b in bs.items():
        try:
            p = json.loads((LOGS / f'{b.logid}_line.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            p = {'events': [], 'excluded': []}
        start = batch_start(b.logid, p['events'], t, batch)
        data[t] = (start, step_times(p['events'], start) if start else {}, p)
    head = '| 步骤 | ' + ' | '.join(f'{t} {bs[t].master}' for t in teams) + ' |'
    sep = '|---|' + '---|' * len(teams)
    out = [f'## 每步用时（分钟），第 {batch} 批', '', head, sep]
    for name in R.NAMES:
        out.append(f'| {name} | ' + ' | '.join(mins((lambda se: se and se[1] - se[0])(data[t][1].get(name)))
                                            for t in teams) + ' |')
    out += ['', '## 各段合计（分钟）', '', '| 段 | ' + ' | '.join(teams) + ' |', sep]
    for stage in ('make', 'early', 'mid', 'late'):
        row = []
        for t in teams:
            st = [e - s for n, (s, e) in data[t][1].items() if stage_of(n) == stage]
            row.append(mins(sum(st)) if st else '-')
        out.append(f'| {stage} | ' + ' | '.join(row) + ' |')
    row = []
    for t in teams:
        start, steps, _ = data[t]
        row.append(mins(max(e for _, e in steps.values()) - start) if steps else '-')
    out.append('| 合计（建号 → 最后完成的一步） | ' + ' | '.join(row) + ' |')
    out.append('| 失败重跑次数 | ' + ' | '.join(str(retries(data[t][2]['events'])) for t in teams) + ' |')
    out.append('| 排除的徒弟 | ' + ' | '.join(','.join(data[t][2].get('excluded', [])) or '-' for t in teams) + ' |')

    out += ['', '## 各地图每分钟经验（每个徒弟；一场 = 开战到下一场开战，含走路）', '',
            '| 地图 | ' + ' | '.join(f'{t} 场数 / 等级 / 战斗秒 / 一场秒 / 每分钟' for t in teams) + ' |', sep]
    per = {t: exp_by_map(exp_rows(set(bs[t].all_names), data[t][0] or 0)) for t in teams}
    maps = sorted({m for v in per.values() for m in v}, key=lambda m: min(per[t][m][1] for t in teams if m in per[t]))
    for m in maps:
        cells = []
        for t in teams:
            v = per[t].get(m)
            cells.append('-' if not v else f'{v[0]} / {v[1]}–{v[2]} / {v[3]:.1f} / '
                         f'{"-" if v[4] is None else f"{v[4]:.1f}"} / {"-" if v[5] is None else f"{v[5]:.0f}"}')
        out.append(f'| {r4_stats.MAPS.get(m, m)} ({m}) | ' + ' | '.join(cells) + ' |')

    sp = sp_summary()
    out += ['', '## 师傅蓄力（sp_watch：开战到蓄力点第一次 +1 的秒数）', '',
            '| 师傅 | 场数 | 本人 中位 | 宠物 中位 | 每场战斗秒 中位 |', '|---|---|---|---|---|']
    for t in teams:
        me, pet, b = sp.get(bs[t].master, ([], [], []))
        med = lambda v: f'{statistics.median(v):.2f}' if v else '-'
        out.append(f'| {bs[t].master} | {len(b)} | {med(me)} | {med(pet)} | {med(b)} |')
    return '\n'.join(out)


def arg(argv, name, default):
    return argv[argv.index(name) + 1] if name in argv else default


if __name__ == '__main__':
    a = sys.argv[1:]
    text = report(arg(a, '--teams', 'a,b,fei,tian').split(','), int(arg(a, '--batch', '3')))
    print(text)
    if '--md' in a:
        Path(arg(a, '--md', '')).write_text(text + '\n', encoding='utf-8')
