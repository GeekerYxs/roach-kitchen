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
  - mass login failure ([outage], factory/outage.py, stage B3): the supervisor exits 4 -> close everything; this PC
    offline -> recheck every net_check_minutes, canary as soon as it is back; online -> wait wait_minutes, then a
    canary every canary_every_minutes. The game exe changed (launcher exit 3; supervisor exits 5, or a canary sees it)
    -> close everything and stop: a human updates the program
  - output floor (stage B4b, last resort behind B4a): the supervisor running >= output_after_minutes, fewer than
    output_floor_per_hour 料理 received in the last hour while >= output_min_waiting alts wait at the coast /
    receiver, receiver bag not full, no maintenance drain -> restart like a stall (counts toward max_restarts)
Decisions are pure (tests/test_factory_guard.py).
"""
import os
import subprocess
import sys
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path

from provisioner import config, log, native, procs

from . import db, heartbeat, maintenance, outage
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
    output_floor: int = 10          # 料理 per hour; 0 = no output floor
    output_after: float = 5400.0    # seconds the supervisor must have run first (ramp-up makes nothing for ~40 min)
    output_waiting: int = 4         # alts waiting downstream: low output with nobody waiting is not "stuck"


def load_guard(data):
    """[guard] of supervisor.toml -> GuardSettings."""
    g = data.get('guard', {})
    s = GuardSettings(float(g.get('stall_seconds', 300)), float(g.get('check_every', 10)),
                      int(g.get('max_restarts', 3)), float(g.get('restart_window_minutes', 60)) * 60,
                      float(g.get('cooldown_minutes', 30)) * 60, bool(g.get('kill_stations', True)),
                      float(g.get('kill_settle', 10)), int(g.get('output_floor_per_hour', 10)),
                      float(g.get('output_after_minutes', 90)) * 60, int(g.get('output_min_waiting', 4)))
    if s.output_floor > 0 and s.output_after < 3600:
        raise ValueError('[guard] output_after_minutes 至少 60（要有满一小时的产量才能比）')
    if s.stall_seconds < 3 * heartbeat.EVERY:
        raise ValueError(f'[guard] stall_seconds ({s.stall_seconds:.0f}) 太小，至少 {3 * heartbeat.EVERY:.0f}')
    if s.max_restarts < 1:
        raise ValueError('[guard] max_restarts 至少 1')
    return s


def judge(exit_code, beat, child_pid, started, now, stall_seconds):
    """One look at the supervisor child. beat: heartbeat.read(); a beat of another pid (an old run) is ignored and
    the clock runs from the child's start instead."""
    if exit_code is not None:
        if exit_code == outage.EXIT_OUTAGE:
            return outage.OUTAGE
        if exit_code == outage.EXIT_VERSION:
            return outage.VERSION
        return FINAL if exit_code in FINAL_CODES else EXITED
    at = beat['at'] if beat is not None and beat['pid'] == child_pid else started
    return STALLED if now - at >= stall_seconds else RUN


def output_low(beat, child_pid, started, now, s):
    """Why the line looks stuck by its output (stage B4b), or None. beat: heartbeat.read() of this child."""
    if s.output_floor <= 0 or beat is None or beat['pid'] != child_pid or now - started < s.output_after:
        return None
    info = beat.get('info')
    if not isinstance(info, dict) or info.get('bag_full'):
        return None                 # nothing to judge by / the receiver stopped on purpose (a restart cannot help)
    dishes, waiting = info.get('dishes_hour'), info.get('waiting')
    if not isinstance(dishes, int) or not isinstance(waiting, int):
        return None
    if dishes >= s.output_floor or waiting < s.output_waiting:
        return None
    return f'最近 1 小时只收到 {dishes} 个料理（下限 {s.output_floor}），同时有 {waiting} 个小号在海岸 / 收货排队'


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
    """Log one alt account in to the role-selection screen and close it again: (ok, detail, version changed).
    Touches no role."""
    from provisioner.login import LaunchThrottle, LoginFailed, login, read_session
    session = None
    try:
        session = login(sup.login, account, ROOT / 'runtime', LaunchThrottle.of(sup.login), logger,
                        kill_on_failure=True)
        _, roster = read_session(session, account.name, logger)
        return True, f'{account.name} 登录成功，选角列表 {len(roster)} 个角色', False
    except LoginFailed as e:
        return False, f'{account.name}: {e}', e.code == outage.VERSION_EXIT
    except Exception as e:      # noqa: BLE001 - every other failure means "not yet"
        return False, f'{account.name}: {e}', False
    finally:
        if session is not None:
            native.close(session, timeout=5)


def when(dt):
    return dt.strftime('%m-%d %H:%M')


class Guard:
    def __init__(self, cfg, s, db_path, logger, maint=None, canary_fn=None, now=datetime.now, outage_s=None,
                 net_ok=None):
        self.cfg, self.s, self.db_path, self.log = cfg, s, db_path, logger
        self.maint, self.canary_fn, self.now = maint, canary_fn, now
        self.outage, self.net_ok = outage_s, net_ok
        self.child = None
        self.started = 0.0
        self.drained = None         # window (start, end) drain.json was written for

    def start(self):
        self.child = subprocess.Popen([sys.executable, '-X', 'utf8', '-m', 'factory.supervisor', str(self.cfg)],
                                      cwd=ROOT, env={**os.environ, outage.GUARD_ENV: '1'})
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
            ok, detail, version = self.canary_fn(tries)
            tries += 1
            if version:
                return outage.VERSION
            if ok:
                self.log.info('试登成功（%s），维护结束，重新开工', detail)
                self.undrain()
                return None
            self.log.warning('试登失败（第 %d 次）：%s；%.0f 分钟后再试', tries, detail, self.maint.canary_every / 60)
            time.sleep(self.maint.canary_every)

    def wait_outage(self):
        """Everything is closed after a mass login failure: find out whether this PC or the server is down, wait,
        canary. None = a canary got in; VERSION = the game exe changed; CLOSED = planned maintenance took over."""
        o, tries, offline, due = self.outage, 0, False, None
        while True:
            if self.maint_phase()[0] == CLOSED:
                return CLOSED
            if not self.net_ok():
                if not offline:
                    self.log.error('本机连不上外网（%s），是这台电脑 / 云电脑的网络问题；每 %.0f 分钟查一次，通了马上试登',
                                   ', '.join(f'{h}:{p}' for h, p in o.net_hosts), o.net_check / 60)
                offline, due = True, None
                time.sleep(o.net_check)
                continue
            now = self.now()
            if due is None:
                if offline:
                    self.log.info('外网通了，马上试登')
                    due = now
                else:
                    self.log.error('外网正常，多半是游戏服务器的问题（临时维护？）；%.0f 分钟后开始用小号试登，之后每 %.0f 分钟一次',
                                   o.wait / 60, o.canary_every / 60)
                    due = now + timedelta(seconds=o.wait)
                offline = False
            if now < due:
                time.sleep(max(1.0, min(60.0, (due - now).total_seconds())))
                continue
            ok, detail, version = self.canary_fn(tries)
            tries += 1
            if version:
                return outage.VERSION
            if ok:
                self.log.info('试登成功（%s），重新开工', detail)
                return None
            self.log.warning('试登失败（第 %d 次）：%s；%.0f 分钟后再试', tries, detail, o.canary_every / 60)
            due = self.now() + timedelta(seconds=o.canary_every)

    def version_stop(self):
        self.undrain()
        self.log.error('！！游戏版本变了（登录器校验游戏 EXE 的 SHA256 不通过，多半是维护后客户端更新）。已关掉全部窗口，'
                       '守护停下：请更新程序（重新定位地址、编译 DLL）后再双击 一键守护.cmd')
        return outage.EXIT_VERSION

    def run(self):
        history = []
        while True:
            ph, win = self.maint_phase()
            if ph == CLOSED:
                self.log.warning('计划维护 %s-%s 快开始了（或已开始），关掉全部窗口', when(win[0]), f'{win[1]:%H:%M}')
                self.kill_all(kill_stations=True)
                if self.wait_maintenance(win) == outage.VERSION:
                    return self.version_stop()
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
            low = output_low(beat, self.child.pid, self.started, now, self.s) if verdict == RUN and ph != DRAIN else None
            if verdict == RUN and low is None:
                continue
            if verdict == outage.VERSION:
                self.kill_all(kill_stations=True)
                return self.version_stop()
            if verdict == outage.OUTAGE:
                self.log.error('总大脑报告大面积登录失败，停工：关掉全部窗口，不再反复登录')
                self.kill_all(kill_stations=True)
                if not self.outage:
                    self.log.error('[outage] 没开，按普通退出处理：%.0f 秒后重启', self.s.kill_settle)
                    time.sleep(self.s.kill_settle)
                    continue
                got = self.wait_outage()
                if got == outage.VERSION:
                    return self.version_stop()
                history.clear()
                continue
            if verdict == FINAL:
                self.log.error('总大脑退出（代码 %d：%s），重启解决不了，守护也停下。处理好后再双击 一键守护.cmd',
                               code, FINAL_CODES[code])
                return code
            if low is not None:
                self.log.error('产量太低：%s。总大脑还活着但产线像是卡住了，全部重启', low)
            elif verdict == EXITED:
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
        outage_s = outage.load_outage(data)
        from .supervisor import load_supervisor     # the same config the supervisor will load
        sup = load_supervisor(cfg)
        if (maint or outage_s) and not sup.login.accounts:
            raise ValueError('维护 / 停工后要用小号试登，但本机没有配置小号号段（local.toml [accounts]）')
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
    if s.output_floor > 0:
        logger.info('产量兜底：总大脑跑满 %.0f 分钟后，最近 1 小时料理少于 %d 个、同时 %d 个以上小号在排队，就全部重启',
                    s.output_after / 60, s.output_floor, s.output_waiting)
    else:
        logger.info('产量兜底：关（[guard] output_floor_per_hour = 0）')
    if maint:
        nxt = maintenance.next_window(datetime.now(), maint)
        weekly = ', '.join(f'{maintenance.DAYS[d]} {a[0]:02d}:{a[1]:02d}-{b[0]:02d}:{b[1]:02d}'
                           for d, a, b in maint.weekly) or '无'
        logger.info('计划维护：每周 %s%s；提前 %.0f 分钟收尾、%.0f 分钟关窗%s', weekly,
                    f'，另 {len(maint.once)} 次临时' if maint.once else '', maint.drain / 60, maint.close / 60,
                    f'；下一次 {when(nxt[0])}-{nxt[1]:%H:%M}' if nxt else '')
    else:
        logger.info('计划维护：没配置（supervisor.toml [maintenance]）')
    if outage_s:
        logger.info('大面积登录失败自动停工：%.0f 分钟内 %d 个以上账号登不上就停；外网通则等 %.0f 分钟再试登，之后每 %.0f 分钟',
                    outage_s.window / 60, outage_s.min_accounts, outage_s.wait / 60, outage_s.canary_every / 60)
    else:
        logger.info('大面积登录失败自动停工：关（supervisor.toml [outage] enabled = false）')
    accounts = sup.login.accounts
    hosts = outage_s.net_hosts if outage_s else ()
    guard = Guard(cfg, s, sup.factory.db_path, logger, maint,
                  lambda i: canary(sup, accounts[i % len(accounts)], log.for_account('canary')),
                  outage_s=outage_s, net_ok=lambda: outage.internet_ok(hosts))
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
