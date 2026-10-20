"""Log in the resident station characters listed in stations.toml and register them in factory.db.

Entry: python -m factory.stations [stations.toml]
Per station: already online in one of OUR windows (same char id as last registered) -> just re-register.
A game window of the same character WITHOUT our DLL -> refuse (logging in again would kick it; the user
closes it first). Otherwise log in, enter the configured slot, verify the char id, register.
"""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from provisioner import config, layout, log, native, procs
from provisioner.enter import EnterJob
from provisioner.login import LaunchThrottle

from . import db
from .config import ROOT, load_settings
from .relogin import other_login_running, relogin_mark


def foreign_windows(name):
    """Game windows showing this character name in their title that do not run our DLL."""
    return [pid for pid, titles in procs.game_window_titles().items()
            if not native.has_dll(pid) and any(f'-{name}_' in t for t in titles)]


def main():
    cfg = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'stations.toml'
    log_path = log.setup(ROOT / 'logs', prefix='stations')
    logger = log.for_account('main')
    logger.info('日志文件: %s', log_path)
    try:
        enter_settings, stations = config.load_stations(cfg)
    except Exception as e:
        logger.error('配置错误 (%s): %s', cfg, e)
        return 2
    # [stations] factory = '...' picks another database (testrun/ uses its own); default = the shared factory.toml
    data = config._read(cfg)
    factory_cfg = data.get('stations', {}).get('factory', 'factory.toml')
    # station windows are never minimized ([batch] minimize is for the supervisor's alt windows): laid out instead
    return _run(cfg, log_path, logger, enter_settings, stations, factory_cfg,
                bool(data.get('batch', {}).get('arrange', True)))


def arrange(conn, logger):
    """Lay out the windows of every registered station that is online ([batch] arrange)."""
    rows = layout.order(conn.execute('SELECT station_id, role, pid FROM stations').fetchall())
    try:
        moved = layout.arrange([r['pid'] if native.has_dll(r['pid']) else None for r in rows])
    except Exception as e:      # noqa: BLE001 - the logins are done; a window chore never fails the run
        logger.warning('排列工位窗口出错: %s', e)
        return
    logger.info('排列工位窗口 %d 个（主屏幕，保持窗口大小；之后可以手动拖动）', len(moved))


def _run(cfg, log_path, logger, enter_settings, stations, factory_cfg, arrange_windows=True):
    settings = load_settings(ROOT / factory_cfg)
    conn = db.connect(settings.db_path)
    for sid in db.prune_stations(conn, [s.station_id for s in stations], time.time()):
        logger.info('工位 %s 已不在 %s 里（或 enabled = false），从数据库删除登记；重启总大脑后不再为它开工人',
                    sid, cfg.name)
    if not stations:
        logger.info('%s 里没有启用的工位', cfg)
        conn.close()
        return 0
    online = {c.char_id: c for c in procs.discover(logger)}
    results, to_login = [], []
    for s in stations:
        known = db.station(conn, s.station_id)
        if known and known['char_id'] in online and known['account'] == s.account.name:
            c = online[known['char_id']]
            db.register_station(conn, s.station_id, s.role, c.char_id, s.account.name, c.name, c.session.pid,
                                time.time())
            logger.info('%s 已在线: %s pid=%d，不重新登录', s.label, c.name, c.session.pid)
            results.append({'station': s.station_id, 'ok': True, 'already_online': True, 'name': c.name})
            continue
        if known and other_login_running(known['status'], known['heartbeat_at'], time.time()):
            logger.error('%s: 总大脑正在自动重登这个工位，这次不登（免得两边同时登录互相挤号）', s.label)
            results.append({'station': s.station_id, 'ok': False, 'error': '总大脑正在自动重登'})
            continue
        name = s.name or (known['name'] if known else '')
        if name and (pids := foreign_windows(name)):
            logger.error('%s: %s 已在别的窗口登录 (pid=%s，不是本工具启动的)。请先关掉那个窗口再运行，'
                         '否则重新登录会把它挤下线', s.label, name, pids)
            results.append({'station': s.station_id, 'ok': False, 'error': f'已在外部窗口 {pids} 登录'})
            continue
        to_login.append(s)
    if to_login:
        logger.info('需要登录的工位: %s', ', '.join(f'{s.label}={s.account.name}(槽{s.account.slot})' for s in to_login))
        logger.info('提示: 如果这些号已经在别的（非本工具启动的）窗口里在线，请先关掉，否则会互相挤号')
        throttle = LaunchThrottle(enter_settings.launch_interval, enter_settings.min_free_memory_mb)
        known = {s.station_id: db.station(conn, s.station_id) for s in to_login}
        for s in to_login:              # a running supervisor sees this and does not log the same station in
            if known[s.station_id]:
                k = known[s.station_id]
                db.heartbeat(conn, s.station_id, k['role'], k['char_id'], relogin_mark(os.getpid()), time.time())
        jobs = [(s, EnterJob(enter_settings, s.account, throttle)) for s in to_login]
        with ThreadPoolExecutor(max_workers=len(jobs), thread_name_prefix='station') as pool:
            summaries = list(pool.map(lambda sj: sj[1].run(), jobs))
        for (s, _), r in zip(jobs, summaries):
            if r['ok'] and s.name and r.get('role') != s.name:
                r.update(ok=False, error=f'槽{s.account.slot} 的角色是 {r.get("role")}，不是配置的 {s.name}（未登记，窗口保留）')
                logger.error('%s: %s', s.label, r['error'])
            if r['ok']:
                db.register_station(conn, s.station_id, s.role, r['char_id'], s.account.name, r['role'], r['pid'],
                                    time.time())
            elif known[s.station_id]:
                k = known[s.station_id]
                db.heartbeat(conn, s.station_id, k['role'], k['char_id'], 'offline', time.time())
            results.append({'station': s.station_id, 'ok': r['ok'], 'name': r.get('role'), 'char_id': r.get('char_id'),
                            'pid': r.get('pid'), 'map_id': r.get('map_id'), 'error': r.get('error')})
    if arrange_windows:
        arrange(conn, logger)
    conn.close()
    out = ROOT / 'logs' / (log_path.stem.replace('stations_', 'stations_summary_') + '.json')
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), 'utf-8')
    logger.info('=' * 60)
    for r in results:
        logger.info('%-12s %s %s %s', r['station'], '在线' if r['ok'] else '失败', r.get('name') or '',
                    r.get('error') or ('（原本就在线）' if r.get('already_online') else ''))
    ok = sum(r['ok'] for r in results)
    logger.info('完成 %d/%d。汇总: %s', ok, len(results), out)
    return 0 if ok == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
