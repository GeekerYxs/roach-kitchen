"""Pipeline: for each account, login -> enter role slot -> novice stage -> close the window.

Entry: python -m provisioner.pipeline [pipeline.toml]
At most `max_windows` of OUR windows exist at once (one worker = one window, closed before the
worker takes the next account). Only processes started by this run are ever closed: every close
goes through OwnWindows, which checks pid + hwnd against what this run launched. Other game
windows (the user's own accounts, other tools) are never read, touched or counted.
Results: state/pipeline/<account>.json, logs/pipeline_*.log, logs/pipeline_report_*.md.
"""
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config, log, native
from .enter import enter_role, verify_in_world
from .login import LaunchThrottle, login, read_session
from .novice import NOVICE_MAP, VILLAGE_MAP, NoviceJob, NoviceSettings
from .procs import Client, game_pids, game_window_titles

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / 'state' / 'pipeline'


class OwnWindows:
    """Registry of the game processes THIS run started. The only way the pipeline closes anything."""

    def __init__(self, limit, log_):
        self.limit, self.log = limit, log_
        self._open = {}
        self._lock = threading.Lock()

    def add(self, session):
        with self._lock:
            self._open[session.pid] = session
            if len(self._open) > self.limit:  # cannot happen with one window per worker; checked anyway
                self.log.error('本工具窗口数 %d 超过上限 %d: %s', len(self._open), self.limit, sorted(self._open))
            return len(self._open)

    def count(self):
        with self._lock:
            return len(self._open)

    def owns(self, pid):
        with self._lock:
            return pid in self._open

    def close(self, session, log_):
        with self._lock:
            own = self._open.get(session.pid)
        if own is None or own.hwnd != session.hwnd:
            log_.error('拒绝关闭 pid=%d：不是本次运行启动的窗口', session.pid)
            return
        if native.alive(session.pid):
            # same process still? the DLL status block must still describe the same window
            try:
                same = native.read_status(session.pid)['hwnd'] == session.hwnd
            except OSError:
                same = False
            if not same:
                log_.error('拒绝关闭 pid=%d：进程身份对不上（pid 可能已被系统复用）', session.pid)
            else:
                native.kill(session.pid)
                log_.info('已关闭本工具窗口 pid=%d', session.pid)
        with self._lock:
            self._open.pop(session.pid, None)


class AccountRun:
    def __init__(self, s, account, slot, throttle, own, account_lock, run_id):
        self.s, self.account, self.slot, self.throttle, self.own = s, account, slot, throttle, own
        self.account_lock, self.run_id = account_lock, run_id
        self.log = log.for_account(f'{account.name}#{slot}')
        self.runtime = ROOT / 'runtime'
        self.step = 'init'

    def run(self):
        # one window per account at a time: a second login of the same account would kick the first
        with self.account_lock:
            return self._run()

    def _run(self):
        started = time.monotonic()
        r = {'account': self.account.name, 'slot': self.slot, 'ok': False, 'step': None, 'error': None,
             'run': self.run_id}
        session = None
        try:
            self._step('登录前检查')
            elsewhere = online_elsewhere(self.account.name, self.own)
            if elsewhere:
                raise RuntimeError(f'该账号的角色正在其他窗口在线（{elsewhere}），为避免把它挤下线，跳过')
            self._step('登录')
            # kill_on_failure=True: a failed launch is our own process (pid from our launcher), close it
            session = login(self.s, self.account, self.runtime, self.throttle, self.log, kill_on_failure=True)
            n = self.own.add(session)
            self.log.info('本工具窗口 %d/%d', n, self.s.max_windows)
            self._step('读取选角列表')
            _, roster = read_session(session, self.account.name, self.log)
            remember_roster(self.account.name, roster)
            if self.slot > len(roster):
                raise RuntimeError(f'槽{self.slot} 没有角色（这个号只有 {len(roster)} 个角色）')
            char_id, level, name = roster[self.slot - 1]
            r.update(role=name, char_id=char_id)
            self._step(f'进入槽{self.slot}: {name}')
            enter_role(session, self.slot, self.s.enter_timeout, self.log)
            world = verify_in_world(session, char_id, name, self.log)
            if world.map_id == NOVICE_MAP:
                self._step('新手出村')
                client = Client(session, char_id, name, world.map_id, world.x, world.y)
                novice = NoviceJob(client, NoviceSettings(self.s.escape_action, self.s.novice_timeout, self.s.tick),
                                   self.log).run()
                r.update(battles=novice['battles'], escapes=novice['escapes'], novice_seconds=novice['seconds'])
                if not novice['ok']:
                    raise RuntimeError(f"新手出村失败: {novice.get('error')}")
                r.update(map_id=VILLAGE_MAP, x=novice['x'], y=novice['y'])
            elif world.map_id == VILLAGE_MAP:
                self.log.info('角色已经在逍遥村西区')
                r.update(map_id=world.map_id, x=round(world.x), y=round(world.y))
            else:
                raise RuntimeError(f'角色在地图 {world.map_id}，既不是菜鸟训练营也不是逍遥村西区，不处理')
            r['ok'] = True
        except Exception as e:
            r.update(step=self.step, error=f'{type(e).__name__}: {e}')
            self.log.error('步骤「%s」失败: %s', self.step, e, exc_info=not isinstance(e, RuntimeError))
        finally:
            if session:
                if r['ok']:
                    time.sleep(1.0)   # let the client finish the arrival before disconnecting
                self.own.close(session, self.log)
        r['seconds'] = round(time.monotonic() - started, 1)
        r['time'] = time.strftime('%Y-%m-%d %H:%M:%S')
        self._save(r)
        self.log.info('结束: %s 用时 %.1fs%s', '成功' if r['ok'] else '失败', r['seconds'],
                      f" 错误={r['error']}" if r['error'] else '')
        return r

    def _step(self, name):
        self.step = name
        self.log.info('== %s ==', name)

    def _save(self, r):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        path = slot_state_path(self.account.name, self.slot)
        history = json.loads(path.read_text('utf-8')).get('history', []) if path.is_file() else []
        history.append({k: r.get(k) for k in ('run', 'ok', 'step', 'error', 'seconds', 'time')})
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps({**r, 'history': history[-20:]}, ensure_ascii=False, indent=2), 'utf-8')
        tmp.replace(path)


def slot_state_path(account, slot):
    return STATE_DIR / f'{account}_slot{slot}.json'


def already_done(account, slot):
    path = slot_state_path(account, slot)
    if not path.is_file():
        return False
    data = json.loads(path.read_text('utf-8'))
    return bool(data.get('ok') and data.get('slot') == slot and data.get('map_id') == VILLAGE_MAP)


_ROSTER_FILE = STATE_DIR / 'rosters.json'
_roster_lock = threading.Lock()


def remember_roster(account, roster):
    """Keep every account's role names, so online_elsewhere() can recognise them in window titles."""
    with _roster_lock:
        data = json.loads(_ROSTER_FILE.read_text('utf-8')) if _ROSTER_FILE.is_file() else {}
        data[account] = [name for _, _, name in roster]
        _ROSTER_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _ROSTER_FILE.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), 'utf-8')
        tmp.replace(_ROSTER_FILE)


def known_role_names(account):
    names = set()
    with _roster_lock:
        if _ROSTER_FILE.is_file():
            names.update(json.loads(_ROSTER_FILE.read_text('utf-8')).get(account, []))
    created = ROOT / 'state' / f'{account}.json'          # batch role creation records
    if created.is_file():
        data = json.loads(created.read_text('utf-8'))
        names.update(data.get('roles', {}))
        names.update(r['name'] for r in data.get('roster', []))
    return names


def online_elsewhere(account, own):
    """Window titles (only titles) of game windows NOT started by this run that show one of the
    account's roles. A selection-screen window has no role in its title and cannot be detected."""
    names = known_role_names(account)
    if not names:
        return None
    for pid, titles in game_window_titles().items():
        if own.owns(pid):
            continue
        for title in titles:
            hit = next((n for n in names if f'-{n}_' in title), None)
            if hit:
                return f'pid={pid} 角色 {hit}'
    return None


def write_report(path, results, settings, seconds):
    ok = [r for r in results if r['ok']]
    bad = [r for r in results if not r['ok']]
    lines = [f'# 流水线报告 {time.strftime("%Y-%m-%d %H:%M")}', '',
             f'槽 {list(settings.slots)}，{len(results)} 个角色：成功 {len(ok)}，失败 {len(bad)}，'
             f'总用时 {seconds:.0f}s。', '']
    if bad:
        lines += ['## 失败', '', '|账号|槽|角色|失败步骤|原因|', '|---|---|---|---|---|']
        lines += [f"|{r['account']}|{r['slot']}|{r.get('role', '')}|{r['step']}|{r['error']}|" for r in bad]
        lines.append('')
    battles = sum(r.get('battles', 0) for r in ok)
    lines += ['## 成功', '', f'新手战斗 {battles} 场；平均每号 {sum(r["seconds"] for r in ok) / max(1, len(ok)):.1f}s。', '']
    path.write_text('\n'.join(lines) + '\n', 'utf-8')


def main():
    cfg_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'pipeline.toml'
    log_path = log.setup(ROOT / 'logs', prefix='pipeline')
    logger = log.for_account('main')
    logger.info('日志文件: %s', log_path)
    try:
        s = config.load_pipeline(cfg_path)
    except Exception as e:
        logger.error('配置错误 (%s): %s', cfg_path, e)
        return 2
    run_id = time.strftime('%Y%m%d_%H%M%S')
    # slot-major order: every account's slot 2, then every account's slot 3, ...
    jobs = [(a, slot) for slot in s.slots for a in s.accounts]
    if s.skip_done:
        done = [(a, slot) for a, slot in jobs if already_done(a.name, slot)]
        if done:
            logger.info('已完成、跳过 %d 个: %s', len(done), ', '.join(f'{a.name}#{slot}' for a, slot in done))
        jobs = [j for j in jobs if j not in done]
    others = game_pids()
    logger.info('启动前已有 %d 个游戏进程（不属于本次运行，不会被关闭）: %s', len(others), others)
    logger.info('待处理 %d 个角色（槽 %s），本工具同时最多 %d 个窗口', len(jobs), list(s.slots), s.max_windows)

    own = OwnWindows(s.max_windows, logger)
    throttle = LaunchThrottle(s.launch_interval, s.min_free_memory_mb)
    locks = {a.name: threading.Lock() for a in s.accounts}
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=s.max_windows, thread_name_prefix='pipe') as pool:
        results = list(pool.map(
            lambda j: AccountRun(s, j[0], j[1], throttle, own, locks[j[0].name], run_id).run(), jobs))
    seconds = time.monotonic() - started

    stamp = log_path.stem.replace('pipeline_', '')
    (ROOT / 'logs' / f'pipeline_summary_{stamp}.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), 'utf-8')
    report = ROOT / 'logs' / f'pipeline_report_{stamp}.md'
    write_report(report, results, s, seconds)
    logger.info('=' * 60)
    for r in results:
        if not r['ok']:
            logger.info('%-6s 槽%d 失败 | 步骤=%s %s', r['account'], r['slot'], r['step'], r['error'])
    ok = sum(r['ok'] for r in results)
    left = own.count()
    logger.info('完成 %d/%d，总用时 %.0fs，本工具残留窗口 %d。报告: %s', ok, len(results), seconds, left, report)
    return 0 if ok == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
