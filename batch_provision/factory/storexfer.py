"""料理仓库号: move the stores rows (stage 2a/2b/2c) from one machine's factory.db to another's.

factory.db is a SQLite file (not text), so the rows go through a JSON file:
  python -m factory.storexfer export   (一键导出仓库号.cmd)  state/仓库号导出.json  <- every stores row of this factory.db
  python -m factory.storexfer import   (一键导入仓库号.cmd)  state/仓库号导出.json  -> this machine's factory.db
Import adds the rows this db does not have and replaces older ones; a row this db changed later (e.g. the supervisor
here already filled it) is kept. Only the stores table is touched. Running it twice changes nothing.
Pure part: plan_import (tests/test_factory_storexfer.py).
"""
import json
import sys
import time
from pathlib import Path

from provisioner import log

from . import db
from .config import ROOT, load_settings

FILE = ROOT / 'state' / '仓库号导出.json'
COLUMNS = ('account', 'slot', 'name', 'char_id', 'status', 'free_slots', 'capacity', 'map_id', 'x', 'y', 'error',
           'updated_at', 'gold', 'potato_at', 'dishes')


def plan_import(existing, incoming):
    """existing / incoming: stores rows (dicts). -> [(incoming row, 'add' | 'update' | 'same' | 'keep')]:
    keep = this db's row was updated at the same time or later and differs (it is the newer truth here)."""
    have = {(r['account'], r['slot']): r for r in existing}
    out = []
    for r in incoming:
        old = have.get((r['account'], r['slot']))
        if old is None:
            out.append((r, 'add'))
        elif all(old.get(c) == r.get(c) for c in COLUMNS):
            out.append((r, 'same'))
        elif (old.get('updated_at') or 0) >= (r.get('updated_at') or 0):
            out.append((r, 'keep'))
        else:
            out.append((r, 'update'))
    return out


def write_row(conn, r):
    conn.execute(f'INSERT OR REPLACE INTO stores({", ".join(COLUMNS)}) VALUES ({", ".join("?" * len(COLUMNS))})',
                 tuple(r.get(c) for c in COLUMNS))


def describe(r):
    return f'{r["name"]} {r["status"]} 地图 {r["map_id"]} ({r["x"]},{r["y"]}) 料理 {r.get("dishes")} 空 {r["free_slots"]} 格'


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    log_path = log.setup(ROOT / 'logs', prefix='storexfer')
    logger = log.for_account('main')
    logger.info('日志文件: %s', log_path)
    if mode not in ('export', 'import'):
        logger.error('用法: python -m factory.storexfer export|import')
        return 2
    fs = load_settings(ROOT / 'factory.toml')
    conn = db.connect(fs.db_path)
    try:
        if mode == 'export':
            rows = [{c: r[c] for c in COLUMNS} for r in db.stores(conn)]
            FILE.parent.mkdir(parents=True, exist_ok=True)
            FILE.write_text(json.dumps({'exported_at': time.time(), 'db': str(fs.db_path), 'stores': rows},
                                       ensure_ascii=False, indent=1), 'utf-8')
            for r in rows:
                logger.info('导出 %s', describe(r))
            logger.info('导出 %d 行 -> %s；把这个文件复制到生产机同一位置（batch_provision\\state\\），再双击 一键导入仓库号.cmd',
                        len(rows), FILE)
            return 0
        if not FILE.is_file():
            logger.error('没有 %s；先在开发机双击 一键导出仓库号.cmd，把文件复制到这里', FILE)
            return 2
        rows = json.loads(FILE.read_text('utf-8'))['stores']
        plan = plan_import([dict(r) for r in db.stores(conn)], rows)
        for r, action in plan:
            if action in ('add', 'update'):
                write_row(conn, r)
            label = {'add': '新增', 'update': '更新', 'same': '相同，跳过', 'keep': '本机的更新，保留本机的'}[action]
            logger.info('%s: %s', label, describe(r))
        counts = {a: sum(1 for _, x in plan if x == a) for a in ('add', 'update', 'same', 'keep')}
        logger.info('导入到 %s：新增 %d 更新 %d 相同 %d 保留本机 %d；就绪(ready) 的现在有 %d 个', fs.db_path, counts['add'],
                    counts['update'], counts['same'], counts['keep'],
                    sum(1 for r in db.stores(conn) if r['status'] == db.STORE_READY))
        return 0
    finally:
        conn.close()


if __name__ == '__main__':
    sys.exit(main())
