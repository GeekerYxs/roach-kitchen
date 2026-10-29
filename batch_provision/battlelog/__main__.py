"""Battle log: decode the DLL tap files into one SQLite table of battles (stage 1: offline import).

    python -X utf8 -m battlelog import [folder ...]   (default: runtime/ and research/shitu/runtime/)
    python -X utf8 -m battlelog summary

Reads runtime/tap_<pid>.jsonl + tap_<pid>_codec.json written by provision_native.dll (launcher windows) or by the
copy research/shitu/attach_tap.py injects. Read-only on the game side. A file whose size and mtime did not change
since the last import is skipped. Database: logs/battlelog/battles.sqlite.
"""
import json
import re
import sys
import time
from pathlib import Path

from . import decode, store

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / 'logs' / 'battlelog' / 'battles.sqlite'
FOLDERS = (ROOT / 'runtime', ROOT / 'research' / 'shitu' / 'runtime')


def import_file(db, path, now=None):
    """-> number of battles stored, or None when skipped (unchanged / no codec file)."""
    pid = int(re.fullmatch(r'tap_(\d+)\.jsonl', path.name).group(1))
    codec = path.with_name(f'tap_{pid}_codec.json')
    st = path.stat()
    if not codec.is_file() or store.source_unchanged(db, path, st.st_size, st.st_mtime):
        return None
    tables = [bytes.fromhex(x) for x in json.loads(codec.read_text())['decode']]
    lines = path.read_bytes().splitlines()
    while lines and not lines[-1].rstrip().endswith(b'}'):     # a line still being written
        lines.pop()
    if not lines:
        return 0
    anchor = st.st_mtime - json.loads(lines[-1])['tick'] / 1000   # the DLL writes every record at once
    battles = decode.assemble(decode.tap_packets(lines, tables))
    store.save(db, [store.to_row(b, str(path), pid, anchor) for b in battles])
    store.mark_source(db, path, pid, st.st_size, st.st_mtime, anchor, len(battles), now or time.time())
    db.commit()
    return len(battles)



def run_import(folders):
    db = store.connect(DB)
    files = sorted(p for f in folders if Path(f).is_dir() for p in Path(f).glob('tap_*.jsonl')
                   if re.fullmatch(r'tap_\d+\.jsonl', p.name))
    done = skipped = total = 0
    for i, p in enumerate(files, 1):
        try:
            n = import_file(db, p)
        except (OSError, ValueError) as e:
            print(f'  [{i}/{len(files)}] {p.name}: 读不了 {e}')
            continue
        if n is None:
            skipped += 1
            continue
        done += 1
        total += n
        if n:
            print(f'  [{i}/{len(files)}] {p.parent.name}/{p.name}: {n} 场')
    store.fill_from_teammates(db)
    print(f'导入 {done} 个文件 {total} 场，跳过 {skipped} 个（没变化或缺 codec），数据库 {DB}')
    summary(db)


def summary(db=None):
    db = db or store.connect(DB)
    n, done = db.execute('select count(*), count(end_tick) from battles').fetchone()
    print(f'共 {n} 场，{done} 场有结算')
    print('地图  场数  人物等级  怪物等级  平均经验  平均潜能  平均宠物经验  平均战斗秒  平均巡逻秒(<300)')
    by = {}
    for m, lv, ml, e, pot, pe, f, pa in db.execute(
            'select map_id, level, monster_levels, exp, potential, pet_exp, fight_s, patrol_s from battles'
            ' where end_tick is not null'):
        by.setdefault(m, []).append((lv, [int(x) for x in (ml or '').split()], e, pot, pe, f, pa))
    for m, rows in sorted(by.items(), key=lambda kv: -len(kv[1]))[:30]:
        lv = [r[0] for r in rows if r[0] is not None]
        ml = [x for r in rows for x in r[1]]
        avg = (lambda i: sum(r[i] or 0 for r in rows) / len(rows))
        pa = [r[6] for r in rows if r[6] is not None and r[6] < 300]
        span = (lambda xs: f'{min(xs)}~{max(xs)}' if xs else '?')
        print(f'{m!s:>5} {len(rows):>5}  {span(lv):>7}  {span(ml):>7}  {avg(2):8.0f}  {avg(3):8.0f}  {avg(4):10.0f}  '
              f'{avg(5):8.1f}  {sum(pa) / len(pa) if pa else 0:8.1f}')


def main(argv):
    if not argv or argv[0] == 'import':
        run_import([Path(a) for a in argv[1:]] or FOLDERS)
    elif argv[0] == 'summary':
        summary()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
