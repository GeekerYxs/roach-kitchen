"""Shared entry for the one-shot per-alt stages (meat, shoe, quest): find alts, run one job per client, summarise."""
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from provisioner import log, procs

from . import db
from .phase import VILLAGE_MAP

ROOT = Path(__file__).resolve().parent.parent
# mw01r1 -> account mw01, number 1. Rebuilt roles (stage 11e) count on by 4: mw01r1 -> mw01r5 -> mw01r9 -> mw01r13.
ROLE_NAME = re.compile(r'^(.+?)r(\d+)$')


def run_stage(prefix, settings, job_factory, map_id=VILLAGE_MAP, map_name='逍遥村西区'):
    """job_factory(client, account, slot, logger) -> object with run() -> result dict ('ok', 'name', ...).
    Only alts standing on map_id are handled."""
    log_path = log.setup(ROOT / 'logs', prefix=prefix)
    logger = log.for_account('main')
    logger.info('日志文件: %s', log_path)
    logger.info('数据库: %s', settings.db_path)
    db.connect(settings.db_path).close()     # create the file and schema once, before the worker threads
    targets = []
    for c in procs.discover(logger):
        m = ROLE_NAME.match(c.name)
        if c.map_id != map_id:
            logger.info('%s 在地图 %d，不是%s，跳过', c.name, c.map_id, map_name)
        elif not m:
            logger.warning('%s 角色名不是 <账号>r<槽> 格式，跳过', c.name)
        else:
            targets.append((c, m.group(1), int(m.group(2))))
    if not targets:
        logger.info('没有需要处理的角色')
        return 0
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=len(targets), thread_name_prefix=prefix) as pool:
        results = list(pool.map(lambda t: job_factory(*t, log.for_account(t[0].name)).run(), targets))
    out = ROOT / 'logs' / (log_path.stem.replace(f'{prefix}_', f'{prefix}_summary_') + '.json')
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), 'utf-8')
    logger.info('=' * 60)
    for r in results:
        logger.info('%-8s %s %s', r['name'], '完成' if r['ok'] else '失败',
                    r.get('error', '已做过' if r.get('skipped') else ''))
    ok = sum(r['ok'] for r in results)
    logger.info('完成 %d/%d，总用时 %.1fs。汇总: %s', ok, len(results), time.monotonic() - started, out)
    return 0 if ok == len(results) else 1
