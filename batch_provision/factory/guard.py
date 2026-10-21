"""Stage B1 guard ("一键守护"): runs the supervisor as a child process and restarts the whole line when it dies or
stalls.

Entry: python -m factory.guard [supervisor.toml]   (settings: [guard] in supervisor.toml)
2026-10-14 runner: the supervisor stalled 35 min with nobody to notice. 2026-10-20 runner: after a network fault a
leader sat on the login screen; the user stopped the supervisor, killed every game process, logged the stations in
and started the supervisor again, and the line ran. The guard does that by itself:
  - every `check_every` s: supervisor exited, or its heartbeat (factory/heartbeat.py) older than `stall_seconds`
  - then: kill the supervisor, every process it started (launcher / game clients still logging in), and every game
    client carrying our DLL (alts and, with `kill_stations`, the stations); the user's own windows (no DLL) are never
    touched; wait `kill_settle` s; start the supervisor again, which logs the stations in itself (station_relogin)
  - at most `max_restarts` restarts per `restart_window_minutes`; more -> wait `cooldown_minutes`, then go on
  - the supervisor refusing to start (config error, another supervisor running) or stopped by Ctrl+C -> the guard
    stops too, a restart would not help
  - planned maintenance ([maintenance], factory/maintenance.py, stage B2): drain before it, close everything, after
    it a canary login every canary_every_minutes; the first success starts the supervisor again
Decisions are pure (tests/test_factory_guard.py).
"""
import subprocess
import sys
import time
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from provisioner import config, log, native, procs

from . import db, heartbeat, maintenance
from .maintenance import CLOSED, DRAIN

ROOT = Path(__file__).resolve().parent.parent
RUN, EXITED, STALLED, FINAL = 'run', 'exited', 'stalled', 'final'
# supervisor exit codes a restart cannot fix
FINAL_CODES = {2: '配置错误', 3: '另一个总大脑正在运行', 130: '手动停止 (Ctrl+C)'}
STOP_WAIT = 15.0        # after Ctrl+C: give the supervisor this long to exit by itself


@dataclass(frozen=True)
class GuardSettings:
    stall_seconds: float = 300.0
    check_every: float = 10.0
    max_restarts: int = 3
    restart_window: float = 3600.0
    cooldown: float = 1800.0
    kill_stations: bool = True
    kill_settle: float = 10.0


def load_guard(data):
    """[guard] of supervisor.toml -> GuardSettings."""
    g = data.get('guard', {})
    s = GuardSettings(float(g.get('stall_seconds', 300)), float(g.get('check_every', 10)),
                      int(g.get('max_restarts', 3)), float(g.get('restart_window_minutes', 60)) * 60,
                      float(g.get('cooldown_minutes', 30)) * 60, bool(g.get('kill_stations', True)),
                      float(g.get('kill_settle', 10)))
    if s.stall_seconds < 3 * heartbeat.EVERY:
        raise ValueError(f'[guard] stall_seconds ({s.stall_seconds:.0f}) 太小，至少 {3 * heartbeat.EVERY:.0f}')
    if s.max_restarts < 1:
        raise ValueError('[guard] max_restarts 至少 1')
    return s


def judge(exit_code, beat, child_pid, started, now, stall_seconds):
    """One look at the supervisor child. beat: heartbeat.read(); a beat of another pid (an old run) is ignored and
    the clock runs from the child's start instead."""
    if exit_code is not None:
        return FINAL if exit_code in FINAL_CODES else EXITED
    at = beat['at'] if beat is not None and beat['pid'] == child_pid else started
    return STALLED if now - at >= stall_seconds else RUN


def may_restart(history, now, s):
    """history: wall times of earlier restarts."""
    return sum(1 for t in history if now - t < s.restart_window) < s.max_restarts


def descendants(rows, root):
    """pids started (directly or not) by root. rows: procs.process_rows()."""
    children = {}
    for pid, ppid, _ in rows:
        if pid != ppid:
            children.setdefault(ppid, []).append(pid)
    found, todo = set(), [root]
    while todo:
        for pid in children.get(todo.pop(), ()):
            if pid not in found and pid != root:
                found.add(pid)
                todo.append(pid)
    return found


def kill_targets(rows, root, dll_pids, station_pids, kill_stations):
    """Everything the supervisor started plus every game client with our DLL; stations only with kill_stations.
    The supervisor itself (root) is killed separately, first."""
    games = {pid for pid, _, exe in rows if exe == procs.GAME_EXE}
    targets = descendants(rows, root) | (games & set(dll_pids))
    if not kill_stations:
        targets -= set(station_pids)
    return targets - {root}


def canary(sup, account, logger):
    """Log one alt account in to the role-selection screen and close it again: (ok, detail). Touches no role."""
    from provisioner.login import LaunchThrottle, login, read_session
    session = None
    try:
        session = login(sup.login, account, ROOT / 'runtime', LaunchThrottle.of(sup.login), logger,
                        kill_on_failure=True)
        _, roster = read_session(session, account.name, logger)
        return True, f'{account.name} 登录成功，选角列表 {len(roster)} 个角色'
    except Exception as e:      # noqa: BLE001 - every failure means "not yet"
        return False, f'{account.name}: {e}'
    finally:
        if session is not None:
            native.close(session, timeout=5)


def when(dt):
    return dt.strftime('%m-%d %H:%M')


class Guard:
    def __init__(self, cfg, s, db_path, logger, maint=None, canary_fn=None, now=datetime.now):
        self.cfg, self.s, self.db_path, self.log = cfg, s, db_path, logger
        self.maint, self.canary_fn, self.now = maint, canary_fn, now
        self.child = None
        self.started = 0.0
        self.drained = None         # window (start, end) drain.json was written for

    def start(self):
        self.child = subprocess.Popen([sys.executable, '-X', 'utf8', '-m', 'factory.supervisor', str(self.cfg)],
                                      cwd=ROOT)
        self.started = time.time()
        self.log.info('总大脑已启动 pid=%d', self.child.pid)

    def station_pids(self):
        try:
            conn = db.connect(self.db_path)
            try:
                return {r['pid'] for r in conn.execute('SELECT pid FROM stations WHERE pid IS NOT NULL')}
            finally:
                conn.close()
        except Exception as e:      # noqa: BLE001 - no station list: keep them all rather than guess
            self.log.error('读不到工位登记 (%s)，这次不关工位窗口', e)
            return None

    def kill_all(self, kill_stations=None):
        """The supervisor child (if any), what it started and every game client with our DLL."""
        root = self.child.pid if self.child is not None else None
        rows = procs.process_rows()
        dll = [pid for pid, _, exe in rows if exe == procs.GAME_EXE and native.has_dll(pid)]
        stations = self.station_pids()
        kill_stations = (self.s.kill_stations if kill_stations is None else kill_stations) and stations is not None
        targets = kill_targets(rows, root, dll, stations or set(), kill_stations)
        if root is not None and self.child.poll() is None:
            native.kill(root)
        killed = sum(1 for pid in sorted(targets) if native.kill(pid))
        kept = '' if kill_stations else '，工位窗口保留'
        self.log.warning('已结束总大脑%s 和 %d 个游戏/登录进程（共找到 %d 个）%s',
                         f' pid={root}' if root is not None else '', killed, len(targets), kept)
        self.child = None

    def maint_phase(self):
        return maintenance.phase(self.now(), self.maint) if self.maint else (maintenance.RUN, None)

    def drain(self, win, reason):
        if self.drained != win:
            maintenance.write_drain(maintenance.DRAIN_PATH, win[1].timestamp(), reason)
            self.drained = win

    def undrain(self):
        if self.drained is not None or maintenance.read_drain(maintenance.DRAIN_PATH) is not None:
            maintenance.clear_drain(maintenance.DRAIN_PATH)
            self.drained = None

    def wait_maintenance(self, win):
        """Everything is closed: wait for the end of the window, then canary logins until one works."""
        start, end = win
        self.drain(win, f'计划维护 {when(start)}-{end:%H:%M}')
        self.log.warning('计划维护 %s-%s：窗口已全部关闭；%s 后每 %.0f 分钟用一个小号试登，登上就重新开工',
                         when(start), f'{end:%H:%M}', f'{end:%H:%M}', self.maint.canary_every / 60)
        tries = 0
        while True:
            ph, w = self.maint_phase()
            if ph == CLOSED:                # still inside (or a later / overlapping window)
                left = (w[1] - self.now()).total_seconds()
                time.sleep(max(1.0, min(60.0, left)))
                continue
            ok, detail = self.canary_fn(tries)
            tries += 1
            if ok:
                self.log.info('试登成功（%s），维护结束，重新开工', detail)
                self.undrain()
                return
            self.log.warning('试登失败（第 %d 次）：%s；%.0f 分钟后再试', tries, detail, self.maint.canary_every / 60)
            time.sleep(self.maint.canary_every)

    def run(self):
        history = []
        while True:
            ph, win = self.maint_phase()
            if ph == CLOSED:
                self.log.warning('计划维护 %s-%s 快开始了（或已开始），关掉全部窗口', when(win[0]), f'{win[1]:%H:%M}')
                self.kill_all(kill_stations=True)
                self.wait_maintenance(win)
                history.clear()
                continue
            if ph == DRAIN:
                if self.drained != win:
                    self.log.warning('计划维护 %s-%s 前收尾：总大脑不再开新批次、不拉人、不删号', when(win[0]),
                                     f'{win[1]:%H:%M}')
                self.drain(win, f'计划维护 {when(win[0])} 前收尾')
            else:
                self.undrain()
            if self.child is None:
                self.start()
            time.sleep(self.s.check_every)
            code = self.child.poll()
            beat = heartbeat.read(heartbeat.PATH)
            now = time.time()
            verdict = judge(code, beat, self.child.pid, self.started, now, self.s.stall_seconds)
            if verdict == RUN:
                continue
            if verdict == FINAL:
                self.log.error('总大脑退出（代码 %d：%s），重启解决不了，守护也停下。处理好后再双击 一键守护.cmd',
                               code, FINAL_CODES[code])
                return code
            if verdict == EXITED:
                self.log.error('总大脑意外退出（代码 %d），全部重启', code)
            else:
                at = beat['at'] if beat and beat['pid'] == self.child.pid else self.started
                self.log.error('总大脑 %.0f 秒没有心跳（卡住了），全部重启', now - at)
            self.kill_all()
            if not may_restart(history, time.time(), self.s):
                self.log.error('%.0f 分钟内已经重启 %d 次，多半是外部问题（网络、服务器维护）；等 %.0f 分钟再试',
                               self.s.restart_window / 60, self.s.max_restarts, self.s.cooldown / 60)
                time.sleep(self.s.cooldown)
                history.clear()
            history.append(time.time())
            time.sleep(self.s.kill_settle)


def main():
    cfg = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'supervisor.toml'
    if not cfg.is_absolute():
        cfg = ROOT / cfg
    log_path = log.setup(ROOT / 'logs', prefix='guard')
    logger = log.for_account('guard')
    logger.info('日志文件: %s', log_path)
    try:
        data = config._read(cfg)
        s = load_guard(data)
        maint = maintenance.load_maintenance(data)
        from .supervisor import load_supervisor     # the same config the supervisor will load
        sup = load_supervisor(cfg)
        if maint and not sup.login.accounts:
            raise ValueError('计划维护后要用小号试登，但本机没有配置小号号段（local.toml [accounts]）')
    except Exception as e:
        logger.error('配置错误 (%s): %s', cfg, e)
        return 2
    other = heartbeat.other_running(heartbeat.read(heartbeat.PATH), None, time.time(), native.alive)
    if other:
        logger.error('已经有总大脑在运行 (pid=%d)：先关掉它（或它的一键守护），再开一键守护', other)
        return 3
    if s.kill_stations and sup.relogin is None:
        s = replace(s, kill_stations=False)
        logger.warning('工位掉线自动重登没开（%s），重启时不关工位窗口',
                       sup.relogin_error or 'supervisor.toml station_relogin = false')
    logger.info('守护开始：%.0f 秒没心跳算卡住；每 %.0f 分钟最多重启 %d 次；重启时%s关工位窗口', s.stall_seconds,
                s.restart_window / 60, s.max_restarts, '' if s.kill_stations else '不')
    if maint:
        nxt = maintenance.next_window(datetime.now(), maint)
        weekly = ', '.join(f'{maintenance.DAYS[d]} {a[0]:02d}:{a[1]:02d}-{b[0]:02d}:{b[1]:02d}'
                           for d, a, b in maint.weekly) or '无'
        logger.info('计划维护：每周 %s%s；提前 %.0f 分钟收尾、%.0f 分钟关窗%s', weekly,
                    f'，另 {len(maint.once)} 次临时' if maint.once else '', maint.drain / 60, maint.close / 60,
                    f'；下一次 {when(nxt[0])}-{nxt[1]:%H:%M}' if nxt else '')
    else:
        logger.info('计划维护：没配置（supervisor.toml [maintenance]）')
    accounts = sup.login.accounts
    guard = Guard(cfg, s, sup.factory.db_path, logger, maint,
                  lambda i: canary(sup, accounts[i % len(accounts)], log.for_account('canary')))
    try:
        return guard.run()
    except KeyboardInterrupt:
        if guard.child is not None and guard.child.poll() is None:
            try:
                guard.child.wait(STOP_WAIT)     # it got the Ctrl+C too and keeps its windows
            except subprocess.TimeoutExpired:
                native.kill(guard.child.pid)
        logger.warning('已手动停止守护和总大脑。窗口保留，重新运行会接管它们')
        return 130


if __name__ == '__main__':
    sys.exit(main())
