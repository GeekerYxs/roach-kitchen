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
Decisions are pure (tests/test_factory_guard.py).
"""
import subprocess
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path

from provisioner import config, log, native, procs

from . import db, heartbeat

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


class Guard:
    def __init__(self, cfg, s, db_path, logger):
        self.cfg, self.s, self.db_path, self.log = cfg, s, db_path, logger
        self.child = None
        self.started = 0.0

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

    def kill_all(self):
        root = self.child.pid
        rows = procs.process_rows()
        dll = [pid for pid, _, exe in rows if exe == procs.GAME_EXE and native.has_dll(pid)]
        stations = self.station_pids()
        kill_stations = self.s.kill_stations and stations is not None
        targets = kill_targets(rows, root, dll, stations or set(), kill_stations)
        if self.child.poll() is None:
            native.kill(root)
        killed = sum(1 for pid in sorted(targets) if native.kill(pid))
        kept = '' if kill_stations else '，工位窗口保留'
        self.log.warning('已结束总大脑 pid=%d 和 %d 个游戏/登录进程（共找到 %d 个）%s', root, killed, len(targets), kept)

    def run(self):
        history = []
        self.start()
        while True:
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
            self.start()


def main():
    cfg = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'supervisor.toml'
    if not cfg.is_absolute():
        cfg = ROOT / cfg
    log_path = log.setup(ROOT / 'logs', prefix='guard')
    logger = log.for_account('guard')
    logger.info('日志文件: %s', log_path)
    try:
        s = load_guard(config._read(cfg))
        from .supervisor import load_supervisor     # the same config the supervisor will load
        sup = load_supervisor(cfg)
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
    guard = Guard(cfg, s, sup.factory.db_path, logger)
    try:
        return guard.run()
    except KeyboardInterrupt:
        if guard.child is not None:
            try:
                guard.child.wait(STOP_WAIT)     # it got the Ctrl+C too and keeps its windows
            except subprocess.TimeoutExpired:
                native.kill(guard.child.pid)
        logger.warning('已手动停止守护和总大脑。窗口保留，重新运行会接管它们')
        return 130


if __name__ == '__main__':
    sys.exit(main())
