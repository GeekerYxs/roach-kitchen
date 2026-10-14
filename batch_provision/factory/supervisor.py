"""Stage 11 supervisor ("总大脑"): every station works at the same time, and alt windows are opened and closed by
queue shortage (FACTORY_DESIGN.md stage 11; decisions in factory/schedule.py, unit-tested).

Entry: python -m factory.supervisor [supervisor.toml]
One process, several threads:
  - one worker per station, looping the existing stage code:
      coast leaders  -> CoastRun (stage 7) with a gate: claim a team only when team_ready() (4 waiting, or the
                        oldest waited `coast_max_wait`), under one lock shared by both leaders, so two leaders never
                        split one queue into two half teams
      receiver       -> PostRun + ReceiveJob (stage 9), one trade at a time
      well leader    -> WellTeamRun + WellTrainRun (stages 4a/4b) once team_ready() on queue_well (`well_max_wait`);
                        a leader still carrying a team or outside the village finishes that batch first
      dispatcher     -> TransportRun (stage 5, gold top-up included) once team_ready() on queue_transport
                        (`transport_max_wait`); a dispatcher left on map 81 goes home first
  - chores: observe every open alt, save its phase, and run the per-alt jobs: novice exit, eat 小肉林 (stage 1),
    record 飞鞋 (stage 2), go home when lost, accept quest 78 (stage 6), hand in (stage 8), leave a team nobody
    leads for us
  - window manager (main thread): reap dead / disconnected windows, close finished / quarantined ones and ones whose
    phase has no worker yet, and pull the next role by name when a queue is short (decide_pull + pick_roles)
Stage 11c runs the whole line except delete (11d): roles waiting for delete are neither pulled nor kept open.
Stage A (factory/relogin.py): a station whose window shows no character for `station_lost_seconds` is closed, and a
station whose process is gone is logged in again from stations.toml (`station_relogin`).
Ctrl+C stops; windows stay open and the next start adopts them (roles of the configured accounts with our DLL).
"""
import logging
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path

from provisioner import config, log, native, procs
from provisioner.enter import EnterJob, enter_role, verify_in_world
from provisioner.game import Game, NotSent
from provisioner.login import LaunchThrottle, login, read_session
from provisioner.memory import ProcessMemory
from provisioner.novice import NoviceJob, NoviceSettings
from provisioner.pipeline import OwnWindows, online_elsewhere, remember_roster
from provisioner.world import read_team, read_world

from . import db
from .coast import CoastRun
from .config import load_settings
from .delete import AccountDeleteJob, DeleteSettings
from .rebuild import RebuildJob
from .relogin import (KILL_SETTLE, RELOGIN_STATUS, Watch, check_entered, decide_watch, may_kill,
                      other_login_running, probe, relogin_delay, relogin_due)
from .stations import foreign_windows
from .handin import HandinJob
from .home import HomeJob
from .meat import MeatJob
from .observe import observe
from .phase import (ACCEPT_QUEST, COAST, COAST_MAP, DELETE, DISPATCHER, EAT_MEAT, HANDIN, LEAVE_TEAM, NOVICE,
                    QUEUE_COAST, QUEUE_RECEIVER, QUEUE_TRANSPORT, QUEUE_WELL, RECEIVER, RECORD_SHOE, RETURN_HOME,
                    TRANSPORTING, UNKNOWN, VILLAGE_MAP, WAIT_DISBAND, derive_phase)
from .phase import WELL as WELL_ROLE
from .quest import QuestJob
from .receiver import PostRun, ReceiveJob
from .runner import ROLE_NAME
from .shoe import ShoeJob
from .transport import TransportRun
from .wellteam import WellTeamRun
from .welltrain import WellTrainRun
from .schedule import (COAST_WAIT, DOWNSTREAM, FARMING_SIDE, OTHER, PULL_COAST, PULL_FRESH, UPSTREAM, WELL, Known,
                       PullPolicy, close_reason, count_sides, decide_pull, has_candidate, pick_delete, pick_rebuild, pick_roles, retry_quarantined,
                       team_ready)

ROOT = Path(__file__).resolve().parent.parent
CHORE_EVERY = 2.0
MANAGE_EVERY = 3.0
STATUS_EVERY = 60.0
LOGIN_FAIL_LIMIT = 3            # a role that failed to log in / enter this often is left alone for this run
FAIL_STREAK_LIMIT = 4           # this many logins in a row failed (any roles) -> stop pulling for a while:
FAIL_STREAK_PAUSE = 300.0       # a systematic fault must not run through every role (2026-10-13: 20 roles x 3)
LEAVE_WAIT = 5.0
LOST_AFTER = 20.0               # no character readable this long (map loads take a few s) -> disconnected
POST_RANGE = 200                # the receiver farther than this from its post goes back first

# Roles in these phases are never pulled into a window: delete needs the account logged OUT (the delete worker logs
# it in on the selection screen itself), so an alt reaching phase delete has its window closed at once.
NOT_SERVED = frozenset({DELETE})
DELETE_EVERY = 5.0
QUARANTINE_CHECK_EVERY = 300.0
DELETE_RETRY = 600.0            # a delete that failed (login, server) is tried again after this long
# An alt in one of these phases but held by no station lost its leader (station crashed / restarted): leave the team.
ORPHAN_TEAM = frozenset({LEAVE_TEAM, WAIT_DISBAND, TRANSPORTING})


class Stopped(Exception):
    pass


# ---- settings -------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class SupSettings:
    login: object           # provisioner.config.PipelineSettings ([game] [batch] [novice] [accounts])
    factory: object         # factory.config.Settings
    policy: PullPolicy
    coast_max_wait: float
    parallel_logins: int
    idle_close: float
    not_served: frozenset
    well_max_wait: float = 90.0
    transport_max_wait: float = 30.0
    fresh: bool = True          # pull roles below 11 for the well
    delete: object = None       # factory.delete.DeleteSettings, None = do not delete (stage 11d off)
    launch: object = None       # factory.delete.DeleteSettings: login settings of the account worker (delete, rebuild)
    rebuild_after: float | None = None  # rebuild a deleted role's slot this long after the delete; None = off (11e)
    rebuild_retry: float = 1200.0       # slot not released yet / failed: try that account again after this long
    quarantine_retry: float = 7200.0    # release a quarantined role once, this long after; 0 = never
    relogin: object = None              # Relogin (stage A), None = stations are not logged in again
    relogin_error: str | None = None    # why relogin is off although configured on


@dataclass(frozen=True)
class Relogin:
    enter: object           # provisioner.config.EnterSettings from stations.toml (kill_on_failure forced on)
    stations: dict          # station_id -> provisioner.config.Station
    lost_after: float       # a station window showing no character this long is closed


def load_relogin(s):
    """[supervisor] station_relogin / stations / station_lost_seconds -> (Relogin or None, error or None)."""
    if not bool(s.get('station_relogin', True)):
        return None, None
    path = ROOT / s.get('stations', 'stations.toml')
    try:
        enter, stations = config.load_stations(path)
    except Exception as e:      # noqa: BLE001 - the supervisor still runs, without relogin
        return None, f'{path.name}: {e}'
    return Relogin(replace(enter, kill_on_failure=True), {x.station_id: x for x in stations},
                   float(s.get('station_lost_seconds', 30))), None


def load_supervisor(path):
    data = config._read(path)
    s = data.get('supervisor', {})
    login_settings = config.load_pipeline(path)
    factory = load_settings(ROOT / s.get('factory', 'factory.toml'))
    policy = PullPolicy(max_windows=int(s.get('max_windows', 20)), coast_buffer=int(s.get('coast_buffer', 2)),
                        well_buffer=int(s.get('well_buffer', 4)), coast_backlog=int(s.get('coast_backlog', 4)))
    if policy.coast_buffer >= policy.coast_backlog:
        raise ValueError(f'coast_buffer ({policy.coast_buffer}) 应小于 coast_backlog ({policy.coast_backlog})')
    launch = DeleteSettings(**config._launch_common(data), max_windows=1, max_roles=0,
                            reply_timeout=float(s.get('delete_reply_timeout', 15)),
                            close_settle=float(s.get('delete_close_settle', 3)),
                            close_timeout=float(s.get('delete_close_timeout', 3)), factory=factory)
    rebuild_after = float(s.get('rebuild_after_hours', 3.2)) * 3600 if bool(s.get('rebuild', True)) else None
    relogin, relogin_error = load_relogin(s)
    return SupSettings(login_settings, factory, policy, float(s.get('coast_max_wait', 90)),
                       max(1, int(s.get('parallel_logins', 4))), float(s.get('idle_close', 60)), NOT_SERVED,
                       float(s.get('well_max_wait', 90)), float(s.get('transport_max_wait', 30)),
                       bool(s.get('fresh', True)), launch if bool(s.get('delete', True)) else None, launch,
                       rebuild_after, float(s.get('rebuild_retry_minutes', 20)) * 60,
                       float(s.get('quarantine_retry_hours', 2)) * 3600, relogin, relogin_error)


# ---- the run --------------------------------------------------------------------------------------------

@dataclass
class AltWin:
    client: object          # procs.Client
    account: str
    slot: int
    phase: str = UNKNOWN
    level: int | None = None
    busy: str | None = None             # a chore is running on it
    unserved_since: float | None = None
    unreadable_since: float | None = None   # the game shows no character (disconnected -> login screen?)


@dataclass
class TeamGate:
    """One per kind of leader (coast, well): its leaders claim alts from the shared queue under this lock."""
    max_wait: float
    lock: threading.Lock = field(default_factory=threading.Lock)


class GatedWellTeamRun(WellTeamRun):
    """Stage 4a unchanged, except the claim: under the lock all well leaders share, the queue is re-checked with
    team_ready() first. With one leader this changes nothing (it only went after wait_for_team() said ready);
    with two, the second leader finds the queue taken and goes back to waiting instead of forming a half team."""

    def __init__(self, conn, station, leader, leader_mem, alts, gate, settings, logger):
        super().__init__(conn, station, leader, leader_mem, alts, settings, logger)
        self.gate = gate

    def choose(self, leader_team):
        with self.gate.lock:
            if not any(cid in self.alts for cid in leader_team.members):     # not resuming its own team
                wall = time.time()
                rows = [r for r in db.waiting(self.conn, QUEUE_WELL, wall) if r['char_id'] in self.alts]
                oldest = wall - rows[0]['phase_since'] if rows else 0.0
                if not team_ready(len(rows), self.s.well_team_size, oldest, self.gate.max_wait):
                    self.log.info('排古井队列的小号被别的队长带走了（剩 %d 个），回去等', len(rows))
                    return []
            return super().choose(leader_team)


class GatedCoastRun(CoastRun):
    """Stage 7 unchanged, except who joins: the leader waits at the rendezvous until team_ready(), and the claim
    happens under the lock both leaders share. The alt list is re-read live (windows come and go)."""

    def __init__(self, conn, station, leader, leader_mem, alts_fn, gate, settings, logger, stop):
        super().__init__(conn, station, leader, leader_mem, alts_fn(), settings, logger)
        self.alts_fn, self.gate, self.stop = alts_fn, gate, stop

    def choose(self):
        size, last = self.s.coast_team_size, None
        while True:
            if self.stop.is_set():
                raise Stopped()
            self.started = time.monotonic()           # waiting does not count against coast_farm_timeout
            lw = self.check()
            now = time.monotonic()
            self.periodic(now, 'waiting')
            if lw and lw.in_battle:
                self.step_battle(now)
                time.sleep(self.s.tick)
                continue
            self.leave_battle(now)
            self.alts = self.alts_fn()
            with self.gate.lock:
                wall = time.time()
                rows = [r for r in db.waiting(self.conn, QUEUE_COAST, wall) if r['char_id'] in self.alts]
                oldest = wall - rows[0]['phase_since'] if rows else 0.0
                if team_ready(len(rows), size, oldest, self.gate.max_wait):
                    got = []
                    for r in rows[:size]:
                        if db.claim(self.conn, self.sid(), [r['char_id']], self.s.coast_lease, wall):
                            got.append(r['char_id'])
                    if got:
                        self.started = time.monotonic()
                        return got
            note = f'等人组队：排队 {len(rows)} 个' + (f'，最久 {oldest:.0f}s' if rows else '')
            if note.split('，')[0] != last:
                self.log.info('%s', note)
            last = note.split('，')[0]
            time.sleep(2.0)


class LeaveJob:
    """An alt in a team none of our stations leads for it (e.g. its coast leader crashed): leave once."""

    def __init__(self, client, log_):
        self.c, self.log = client, log_

    def run(self):
        result = {'name': self.c.name, 'ok': False}
        with ProcessMemory(self.c.session.pid, self.c.session.base) as mem:
            game = Game(self.c.session, mem)
            try:
                team = read_team(mem)
                if team is not None and not team.members:
                    return {**result, 'ok': True, 'skipped': True}
                self.log.info('离开队伍（队长 %s）', team.leader if team else '?')
                try:
                    game.team_leave()
                except NotSent as e:
                    return {**result, 'error': f'退队请求没发出: {e}'}
                deadline = time.monotonic() + LEAVE_WAIT
                while time.monotonic() < deadline:
                    team = read_team(mem)
                    if team is not None and not team.members:
                        return {**result, 'ok': True}
                    time.sleep(0.2)
                return {**result, 'error': f'{LEAVE_WAIT:.0f}s 内没离队'}
            finally:
                game.close()


class Supervisor:
    def __init__(self, s, logger):
        self.s, self.log = s, logger
        self.conn = db.connect(s.factory.db_path)
        self.own = OwnWindows(s.policy.max_windows + s.parallel_logins + 1, logger)
        self.throttle = LaunchThrottle(s.login.launch_interval, s.login.min_free_memory_mb)
        self.accounts = {a.name: a for a in s.login.accounts}
        self.names_in_order = [(f'{a.name}r{slot}', a.name) for slot in s.login.slots for a in s.login.accounts]
        self.alts = {}              # char_id -> AltWin
        self.pending = {}           # role name -> pull kind, logins in progress
        self.login_fails = Counter()
        self.fail_streak = 0            # logins failed in a row, any role
        self.pull_paused_until = 0.0
        self.deleting = None            # account the delete worker is logged into (no pulls for it meanwhile)
        self.delete_skip = {}           # role name -> monotonic time until which the delete worker leaves it alone
        self.deleted = 0
        self.closed_at = {}             # account -> monotonic time its last window was closed
        self.rebuild_skip = {}          # account -> monotonic time until which the rebuild leaves it alone
        self.rebuilt = 0
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.coast_gate = TeamGate(s.coast_max_wait)
        self.well_gate = TeamGate(s.well_max_wait)
        # well_buffer, coast_buffer and coast_backlog are per leader of that kind: more leaders, longer queues
        wells = max(1, len(self.station_rows(WELL_ROLE)))
        coasts = max(1, len(self.station_rows(COAST)))
        self.policy = replace(s.policy, well_buffer=s.policy.well_buffer * wells,
                              coast_buffer=s.policy.coast_buffer * coasts,
                              coast_backlog=s.policy.coast_backlog * coasts)
        self.last_quarantine_check = 0.0
        self.relogin = getattr(s, 'relogin', None)
        self.watches = {}               # station_id -> relogin.Watch
        self.logins = ThreadPoolExecutor(max_workers=s.parallel_logins, thread_name_prefix='login')
        self.chores = ThreadPoolExecutor(max_workers=12, thread_name_prefix='chore')
        self.quiet = logging.LoggerAdapter(logging.getLogger('prov.scan'), {'account': 'scan'})
        logging.getLogger('prov.scan').setLevel(logging.ERROR)

    # ---- windows
    def scan(self):
        return {c.char_id: c for c in procs.discover(self.quiet)}

    def station_rows(self, role=None):
        sql, args = 'SELECT * FROM stations', ()
        if role:
            sql, args = sql + ' WHERE role=? ORDER BY station_id', (role,)
        return self.conn.execute(sql, args).fetchall()

    def adopt(self):
        stations = set(db.station_roles(self.conn))
        for c in self.scan().values():
            m = ROLE_NAME.match(c.name)
            # configured accounts only; any role number (rebuilt roles are r5, r9 ...)
            if c.char_id in stations or not m or m.group(1) not in self.accounts:
                continue
            self.own.add(c.session)
            self.add(AltWin(c, m.group(1), int(m.group(2))))
            self.log.info('接管已开的窗口 %s pid=%d 地图 %d', c.name, c.session.pid, c.map_id)

    def add(self, aw, conn=None):
        """conn: the calling thread's own connection (sqlite connections must stay in their thread);
        None = the main thread's."""
        conn = conn or self.conn
        c = aw.client
        db.register_alt(conn, c.char_id, aw.account, aw.slot, c.name, time.time())
        row = db.alt(conn, c.char_id)
        aw.phase = row['phase']
        with self.lock:
            self.alts[c.char_id] = aw

    def snapshot(self):
        """{char_id: (client, account, slot)} of the open, live alt windows (what the stage code expects)."""
        with self.lock:
            items = list(self.alts.items())
        return {cid: (a.client, a.account, a.slot) for cid, a in items
                if native.alive(a.client.session.pid) and a.unreadable_since is None}

    def close(self, aw, why):
        c = aw.client
        with self.lock:
            self.alts.pop(c.char_id, None)
        self.own.close(c.session, log.for_account(c.name))
        self.closed_at[aw.account] = time.monotonic()
        self.log.info('%s 关窗: %s', c.name, why)

    # ---- station workers
    def worker(self, st, body):
        """Keep one station working; its window missing or an error only pauses this station. Missing with its
        process gone -> log it in again (stage A); missing with the process alive -> the watcher closes it first."""
        sid = st['station_id']
        lg = log.for_account(st['name'] or sid)
        conn = db.connect(self.s.factory.db_path)
        fails, warned = 0, 0.0
        # a fresh start holds nobody: what an earlier run held is free again (the batch still carried is re-claimed)
        if freed := db.release_station(conn, sid, time.time(), '工位开工'):
            lg.info('开工：放开上次运行占着的 %d 个小号 %s', len(freed), freed)
        try:
            while not self.stop.is_set():
                st = db.station(conn, sid) or st         # pid / name change after a relogin
                me = self.scan().get(st['char_id'])
                if me is None:
                    if self.relogin and self.try_relogin(conn, st, lg):
                        continue
                    if time.monotonic() - warned > 60:
                        lg.warning('工位 %s %s (ID=%d) 不在线，这个工位暂停；%s', sid, st['name'], st['char_id'],
                                   self.offline_hint(sid))
                        warned = time.monotonic()
                    self.stop.wait(5 if self.relogin else 10)
                    continue
                try:
                    body(conn, st, me, lg)
                    fails = 0
                except Stopped:
                    break
                except Exception as e:
                    fails += 1
                    lg.error('工位出错（连续 %d 次）: %s', fails, e, exc_info=not isinstance(e, RuntimeError))
                    # the failed batch's members go back to their queues now (they used to stay held forever)
                    if freed := db.release_station(conn, sid, time.time(), f'工位出错: {e}'):
                        lg.warning('放开这一批的 %d 个小号 %s，它们按各自进度回队列', len(freed), freed)
                    # window closed (by the watcher, or crashed): straight to the relogin, no back-off
                    self.stop.wait(2 if not native.alive(me.session.pid) else min(60, 10 * fails))
        finally:
            conn.close()

    # ---- stage A: lost stations are closed (watch_stations, main thread) and logged in again (try_relogin)
    def watch(self, sid):
        with self.lock:
            return self.watches.setdefault(sid, Watch())

    def offline_hint(self, sid):
        if not self.relogin:
            err = getattr(self.s, 'relogin_error', None)
            return '用 一键登录工位.cmd 登上后自动继续' + (f'（自动重登没开：{err}）' if err else '')
        w = self.watch(sid)
        if w.blocked:
            return f'不自动重登：{w.blocked}'
        left = w.next_try - time.monotonic()
        return f'{left:.0f} 秒后再试自动重登' if left > 0 else '准备自动重登'

    def watch_stations(self):
        """A station process alive but showing no character of its own for lost_after s -> close it, so the batch
        it is running fails at once and the worker logs it in again."""
        now = time.monotonic()
        for st in self.station_rows():
            sid, w = st['station_id'], self.watch(st['station_id'])
            h, hwnd = probe(st['pid'], st['char_id'])
            d = decide_watch(h, w.lost_since, now, self.relogin.lost_after)
            lg = log.for_account(st['name'] or sid)
            if d == 'ok':
                if w.lost_since is not None:
                    lg.info('工位又能读到角色了（%.0fs）', now - w.lost_since)
                w.hwnd, w.lost_since = hwnd, None
            elif d == 'lost':
                w.lost_since = now
                lg.warning('工位 pid=%d 读不到角色（掉线回到登录界面？），%.0f 秒后仍读不到就关窗重登',
                           st['pid'], self.relogin.lost_after)
            elif d == 'kill':
                w.lost_since = None
                if sid not in self.relogin.stations:
                    lg.error('工位 pid=%d 读不到角色，但它不在工位配置里，不能自动重登，所以不关；请人工处理', st['pid'])
                    continue
                if not may_kill(w.hwnd, hwnd, self.own.owns(st['pid'])):
                    lg.error('工位 pid=%d 读不到角色，但窗口身份对不上（pid 可能被系统复用），不关；请人工看一下', st['pid'])
                    continue
                native.kill(st['pid'])
                w.next_try = max(w.next_try, now + KILL_SETTLE)
                lg.warning('工位 pid=%d %.0f 秒读不到角色，已关窗，准备自动重登', st['pid'], self.relogin.lost_after)
                db.log_event(self.conn, time.time(), 'station', f'掉线关窗 pid={st["pid"]}', station_id=sid)
            elif d in ('gone', 'foreign'):
                w.lost_since = None

    def try_relogin(self, conn, st, lg):
        """Log the station in again when its process is gone. True = a login was attempted."""
        sid, w, now = st['station_id'], self.watch(st['station_id']), time.monotonic()
        h, _ = probe(st['pid'], st['char_id'])
        if not relogin_due(h, w, now):
            return False
        cfg = self.relogin.stations.get(sid)
        if cfg is None:
            w.blocked = '不在 stations.toml / local.toml 的工位列表里（或 enabled = false）'
            return False
        name = cfg.name or st['name'] or ''
        if name and (pids := foreign_windows(name)):
            w.fails += 1
            w.next_try = now + relogin_delay(w.fails)
            lg.error('%s 开在不是本工具启动的窗口里 (pid=%s)，自动重登会把它挤下线，不登；关掉那个窗口后会自动再试',
                     name, pids)
            return False
        if other_login_running(st['status'], st['heartbeat_at'], time.time()):
            w.next_try = now + 30
            lg.info('一键登录工位.cmd 正在登录这个工位，等它登完')
            return False
        if self.stop.is_set():
            return False
        db.heartbeat(conn, sid, st['role'], st['char_id'], RELOGIN_STATUS, time.time())
        lg.warning('工位不在线，自动重登 %s 槽%d（第 %d 次）', cfg.account.name, cfg.account.slot, w.fails + 1)
        r = EnterJob(self.relogin.enter, cfg.account, self.throttle).run()
        err, permanent = check_entered(r, st['char_id'], name)
        if err is None:
            db.register_station(conn, sid, st['role'], r['char_id'], cfg.account.name, r['role'], r['pid'],
                                time.time())
            w.fails, w.next_try, w.hwnd, w.lost_since = 0, 0.0, r.get('hwnd'), None
            lg.info('工位重登成功: %s pid=%d 地图 %s，接着干活', r['role'], r['pid'], r.get('map_id'))
            return True
        if r.get('pid') and native.alive(r['pid']):
            native.kill(r['pid'])           # the window we just started; never left half-logged-in
        db.heartbeat(conn, sid, st['role'], st['char_id'], 'offline', time.time())
        if permanent:
            w.blocked = err
            lg.error('工位重登进错了角色，已关掉那个窗口，本次运行不再自动重登: %s', err)
        else:
            w.fails += 1
            w.next_try = time.monotonic() + relogin_delay(w.fails)
            lg.error('工位重登失败（连续 %d 次），%.0f 秒后再试: %s', w.fails, relogin_delay(w.fails), err)
        db.log_event(conn, time.time(), 'station', f'自动重登失败: {err}', station_id=sid)
        return True

    def coast_body(self, conn, st, leader, lg):
        with ProcessMemory(leader.session.pid, leader.session.base) as mem:
            run = GatedCoastRun(conn, st, leader, mem, self.snapshot, self.coast_gate, self.s.factory, lg, self.stop)
            try:
                results = run.run()
            finally:
                run.close()
        for r in results:
            lg.info('%-8s %s %s', r['name'], '成功' if r['ok'] else '失败', r.get('error') or '')

    def receiver_body(self, conn, st, recv, lg):
        sid, fs = st['station_id'], self.s.factory
        with ProcessMemory(recv.session.pid, recv.session.base) as rmem:
            post = PostRun(conn, st, recv, rmem, fs, lg)
            try:
                post.run()
            finally:
                post.close()
            px, py = fs.receiver_post
            rgame = Game(recv.session, rmem)
            try:
                while not self.stop.is_set():
                    if not native.alive(recv.session.pid):
                        raise RuntimeError('收货人游戏进程已退出')
                    w = read_world(rmem)
                    if w is None or w.map_id != COAST_MAP or abs(w.x - px) + abs(w.y - py) > POST_RANGE:
                        lg.info('收货人不在收货点，先回去')
                        return
                    alts = self.snapshot()
                    for r in db.waiting(conn, QUEUE_RECEIVER, time.time()):
                        cid = r['char_id']
                        if self.stop.is_set() or cid not in alts:
                            continue
                        if not db.claim(conn, sid, [cid], fs.receive_lease, time.time()):
                            continue
                        c = alts[cid][0]
                        try:
                            res = ReceiveJob(conn, sid, recv, rmem, rgame, c, fs, log.for_account(c.name)).run()
                        finally:
                            db.release(conn, sid, [cid], time.time())
                        self._failed(conn, cid, res)
                    db.heartbeat(conn, sid, RECEIVER, recv.char_id, 'receiving', time.time())
                    self.stop.wait(2.0)
            finally:
                rgame.close()

    def wait_for_team(self, conn, st, phase, size, max_wait, lg, pid):
        """Block until team_ready() for the station's queue (only the open, readable alt windows count).
        pid: the station's own process; gone (closed as lost) -> stop waiting."""
        last = None
        while not self.stop.is_set():
            if not native.alive(pid):
                raise RuntimeError(f'工位游戏进程 {pid} 已退出')
            alts, wall = self.snapshot(), time.time()
            rows = [r for r in db.waiting(conn, phase, wall) if r['char_id'] in alts]
            oldest = wall - rows[0]['phase_since'] if rows else 0.0
            if team_ready(len(rows), size, oldest, max_wait):
                return
            if len(rows) != last:
                lg.info('等人组队：排队 %d 个', len(rows))
                last = len(rows)
            db.heartbeat(conn, st['station_id'], st['role'], st['char_id'], 'waiting', wall)
            self.stop.wait(2.0)
        raise Stopped()

    def well_body(self, conn, st, leader, lg):
        fs = self.s.factory
        with ProcessMemory(leader.session.pid, leader.session.base) as mem:
            w, team = read_world(mem), read_team(mem)
            if w is None or team is None:
                raise RuntimeError('读不到古井队长的状态')
            if w.map_id == VILLAGE_MAP and len(team.members) <= 1:
                self.wait_for_team(conn, st, QUEUE_WELL, fs.well_team_size, self.s.well_max_wait, lg,
                                   leader.session.pid)
                db.heartbeat(conn, st['station_id'], WELL_ROLE, leader.char_id, 'forming', time.time())
                run = GatedWellTeamRun(conn, st, leader, mem, self.snapshot(), self.well_gate, fs, lg)
                try:
                    results = run.run()
                finally:
                    run.close()
                self._log_results(lg, results)
                if not any(r['ok'] for r in results):
                    return
            else:
                lg.info('古井队长还带着队伍或不在村里（地图 %d），先把这一批练完回村', w.map_id)
            run = WellTrainRun(conn, st, leader, mem, self.snapshot(), fs, lg)
            try:
                results = run.run()
            finally:
                run.close()
            self._log_results(lg, results)
            db.heartbeat(conn, st['station_id'], WELL_ROLE, leader.char_id, 'idle', time.time())

    def dispatcher_body(self, conn, st, disp, lg):
        fs = self.s.factory
        with ProcessMemory(disp.session.pid, disp.session.base) as mem:
            w = read_world(mem)
            if w is None:
                raise RuntimeError('读不到调度员的状态')
            if w.map_id != COAST_MAP:
                self.wait_for_team(conn, st, QUEUE_TRANSPORT, fs.transport_team_size, self.s.transport_max_wait, lg,
                                   disp.session.pid)
            db.heartbeat(conn, st['station_id'], DISPATCHER, disp.char_id, 'transporting', time.time())
            run = TransportRun(conn, st, disp, mem, self.snapshot(), fs, lg)
            try:
                results = run.run()
            finally:
                run.close()
            self._log_results(lg, results)
            db.heartbeat(conn, st['station_id'], DISPATCHER, disp.char_id, 'idle', time.time())

    @staticmethod
    def _log_results(lg, results):
        for r in results:
            lg.info('%-8s %s %s', r['name'], '成功' if r['ok'] else '失败', r.get('error') or '')

    @staticmethod
    def _failed(conn, cid, res):
        """A job that ended without ok counts as one failure (3 -> quarantine), unless it already quarantined."""
        if res.get('ok'):
            return
        row = db.alt(conn, cid)
        if row is not None and not row['quarantined']:
            db.record_failure(conn, cid, res.get('error') or '失败', time.time())

    # ---- chores
    def chores_loop(self):
        conn = db.connect(self.s.factory.db_path)
        try:
            while not self.stop.is_set():
                roles = db.station_roles(conn)
                with self.lock:
                    items = list(self.alts.items())
                for cid, aw in items:
                    if aw.busy or not native.alive(aw.client.session.pid):
                        continue
                    try:
                        self.chore(conn, roles, cid, aw)
                    except Exception as e:
                        log.for_account(aw.client.name).error('观察出错: %s', e, exc_info=True)
                self.stop.wait(CHORE_EVERY)
        finally:
            conn.close()

    def chore(self, conn, roles, cid, aw):
        c = aw.client
        with ProcessMemory(c.session.pid, c.session.base) as mem:
            obs = observe(mem, read_world(mem))
        if obs is None or obs.char_id != cid:
            # 2026-10-13 live: mw19r1 dropped back to the account/password screen with its process alive; it stayed
            # in the queue and two coast leaders each waited 120 s for it. Unreadable -> not offered to stations.
            if aw.unreadable_since is None:
                aw.unreadable_since = time.monotonic()
            return
        if aw.unreadable_since is not None:
            log.for_account(c.name).info('又能读到角色了（%.0fs）', time.monotonic() - aw.unreadable_since)
            aw.unreadable_since = None
        plan = derive_phase(obs, db.ledger(conn, cid), roles)
        db.save_observation(conn, obs, plan, time.time())
        aw.phase, aw.level = plan.phase, obs.level
        row = db.alt(conn, cid)
        held = row['station_id'] is not None and (row['lease_until'] or 0) >= time.time()
        if held:
            return
        lg, fs, n = log.for_account(c.name), self.s.factory, self.s.login
        if plan.phase == NOVICE:
            job, label = NoviceJob(c, NoviceSettings(n.escape_action, n.novice_timeout, n.tick), lg), '新手出村'
        elif plan.phase == EAT_MEAT:
            job, label = MeatJob(c, aw.account, aw.slot, fs, lg), '吃小肉林'
        elif plan.phase == RECORD_SHOE:
            job, label = ShoeJob(c, aw.account, aw.slot, fs, lg), '记录飞鞋'
        elif plan.phase == RETURN_HOME:
            job, label = HomeJob(c, fs, lg), '回村'
        elif plan.phase == ACCEPT_QUEST:
            job, label = QuestJob(c, aw.account, aw.slot, fs, lg), '接任务'
        elif plan.phase == HANDIN:
            job, label = HandinJob(c, aw.account, aw.slot, fs, lg), '交任务'
        elif plan.phase in ORPHAN_TEAM:
            job, label = LeaveJob(c, lg), '离队'
        else:
            return
        aw.busy = label
        self.chores.submit(self.run_chore, cid, aw, job)

    def run_chore(self, cid, aw, job):
        conn = db.connect(self.s.factory.db_path)
        try:
            res = job.run()
            if not res.get('ok'):
                log.for_account(aw.client.name).warning('%s 没成功: %s', aw.busy, res.get('error'))
            self._failed(conn, cid, res)
        except Exception as e:
            log.for_account(aw.client.name).error('%s 出错: %s', aw.busy, e, exc_info=True)
            self._failed(conn, cid, {'error': f'{type(e).__name__}: {e}'})
        finally:
            aw.busy = None
            conn.close()

    # ---- window manager
    def known(self):
        out = {}
        for r in self.conn.execute('SELECT * FROM alts'):
            obs = db.last_observation(self.conn, r['char_id']) if r['obs_json'] else None
            out[r['name']] = Known(r['name'], r['account'], r['phase'], obs.level if obs else None,
                                   bool(r['quarantined']), r['deleted_at'] is not None, r['phase_since'])
        return out

    def manage(self):
        if self.relogin:
            self.watch_stations()
        now = time.monotonic()
        if now - self.last_quarantine_check >= QUARANTINE_CHECK_EVERY:
            self.last_quarantine_check = now
            self.release_quarantined()
        with self.lock:
            items = list(self.alts.values())
        for aw in items:
            c = aw.client
            if not native.alive(c.session.pid):
                with self.lock:
                    self.alts.pop(c.char_id, None)
                self.own.close(c.session, log.for_account(c.name))
                self.log.warning('%s 的游戏进程已退出（掉线/被关），移出', c.name)
                continue
            if aw.busy:
                continue
            if aw.unreadable_since is not None and now - aw.unreadable_since >= LOST_AFTER:
                self.close(aw, f'掉线：{LOST_AFTER:.0f} 秒读不到角色（多半回到了登录界面），关窗；阶段保留，之后会重新拉起')
                continue
            row = db.alt(self.conn, c.char_id)
            if row['station_id'] is not None and (row['lease_until'] or 0) >= time.time():
                aw.unserved_since = None
                continue
            why = close_reason(row['phase'], bool(row['quarantined']))
            if why is None and row['phase'] == DELETE:
                why = '料理已交出，关窗等删除' if self.s.delete else '料理已交出，关窗（删除未启用）'
            if why is None and row['phase'] in self.s.not_served:
                aw.unserved_since = aw.unserved_since or now
                if now - aw.unserved_since >= self.s.idle_close:
                    why = f'阶段 {row["phase"]}（{row["reason"]}）这一步还没有工人负责'
            else:
                aw.unserved_since = None
            if why:
                self.close(aw, why)
        self.pull()

    def release_quarantined(self):
        """One automatic second chance per quarantined role (schedule.retry_quarantined)."""
        rows = [(r['char_id'], r['phase_since'], r['releases']) for r in self.conn.execute(
            "SELECT a.char_id, a.phase_since, (SELECT COUNT(*) FROM events e WHERE e.kind='release' "
            'AND e.char_id=a.char_id) AS releases FROM alts a WHERE a.quarantined=1')]
        for cid in retry_quarantined(rows, time.time(), self.s.quarantine_retry):
            row = db.alt(self.conn, cid)
            db.release_quarantine(self.conn, cid, time.time())
            self.log.info('%s 隔离已满 %.0f 小时，自动解除一次（原因: %s）；再被隔离就不再管它', row['name'],
                          self.s.quarantine_retry / 3600, row['last_error'])

    def pull(self):
        if time.monotonic() < self.pull_paused_until:
            return
        known = self.known()
        while True:
            with self.lock:
                alts = list(self.alts.values())
                pending = dict(self.pending)
                deleting = self.deleting
            sides = [(a.phase, a.level) for a in alts]
            sides += [((ACCEPT_QUEST, 11) if k == PULL_COAST else (QUEUE_WELL, 1)) for k in pending.values()]
            counts = count_sides(sides)
            open_accounts = {a.account for a in alts} | {known[n].account if n in known else ROLE_NAME.match(n)[1]
                                                         for n in pending}
            if deleting:
                open_accounts.add(deleting)
            skip = ({n for n, k in self.login_fails.items() if k >= LOGIN_FAIL_LIMIT} | set(pending)
                    | {n for n, k in known.items() if k.phase in self.s.not_served})
            have_coast = has_candidate(PULL_COAST, known, self.names_in_order, open_accounts, skip)
            have_fresh = self.s.fresh and has_candidate(PULL_FRESH, known, self.names_in_order,
                                                              open_accounts, skip)
            d = decide_pull(counts, len(alts) + len(pending), self.policy, have_coast, have_fresh)
            if d.kind is None or len(pending) >= self.s.parallel_logins:
                return
            name = pick_roles(d.kind, known, self.names_in_order, open_accounts, skip, 1)[0]
            with self.lock:
                if self.deleting == ROLE_NAME.match(name)[1]:
                    return                  # the delete worker took this account meanwhile
                self.pending[name] = d.kind
            self.log.info('%s -> 登录 %s', d.reason, name)
            self.logins.submit(self.open_role, name)

    def open_role(self, name):
        account = self.accounts[ROLE_NAME.match(name)[1]]
        lg = log.for_account(name)
        session = None
        try:
            elsewhere = online_elsewhere(account.name, self.own)
            if elsewhere:
                raise RuntimeError(f'该账号的角色正在其他窗口在线（{elsewhere}），为避免挤号，跳过')
            session = login(self.s.login, account, ROOT / 'runtime', self.throttle, lg, kill_on_failure=True)
            self.own.add(session)
            _, roster = read_session(session, account.name, lg)
            remember_roster(account.name, roster)
            index = next((i for i, (_, _, n) in enumerate(roster) if n == name), None)
            if index is None:
                raise RuntimeError(f'选角列表里没有 {name}（有 {[n for _, _, n in roster]}）')
            char_id = roster[index][0]
            enter_role(session, index + 1, self.s.login.enter_timeout, lg)
            world = verify_in_world(session, char_id, name, lg)
            client = procs.Client(session, char_id, name, world.map_id, world.x, world.y)
            conn = db.connect(self.s.factory.db_path)
            try:
                self.add(AltWin(client, account.name, int(ROLE_NAME.match(name)[2])), conn)
            finally:
                conn.close()
            self.login_fails.pop(name, None)
            self.fail_streak = 0
            lg.info('已上线 地图 %d (%.0f,%.0f)', world.map_id, world.x, world.y)
        except Exception as e:
            self.login_fails[name] += 1
            self.fail_streak += 1
            lg.error('登录/进入失败（第 %d 次）: %s', self.login_fails[name], e, exc_info=not isinstance(e, RuntimeError))
            if session:
                self.own.close(session, lg)
            if self.fail_streak >= FAIL_STREAK_LIMIT:
                self.pull_paused_until = time.monotonic() + FAIL_STREAK_PAUSE
                self.log.error('连续 %d 次登录/进入失败，暂停拉人 %.0f 秒（服务器、网络或程序问题？请看日志）',
                               self.fail_streak, FAIL_STREAK_PAUSE)
        finally:
            with self.lock:
                self.pending.pop(name, None)

    # ---- account worker: delete (stage 11d) and rebuild (stage 11e), one account login at a time
    def account_loop(self):
        conn = db.connect(self.s.factory.db_path)
        try:
            while not self.stop.is_set():
                name = self.next_delete(conn) if self.s.delete else None
                account = None if name or not self.s.rebuild_after else self.next_rebuild(conn)
                if name is None and account is None:
                    self.stop.wait(DELETE_EVERY)
                    continue
                try:
                    if name:
                        self.delete_one(conn, name)
                    else:
                        self.rebuild_one(conn, account)
                except Exception as e:
                    self.log.error('%s %s 出错: %s', '删除' if name else '重建', name or account, e, exc_info=True)
                    if name:
                        self.delete_skip[name] = time.monotonic() + DELETE_RETRY
                    else:
                        self.rebuild_skip[account] = time.monotonic() + self.s.rebuild_retry
                finally:
                    with self.lock:
                        self.deleting = None
        finally:
            conn.close()

    def _busy_accounts(self, now):
        """Accounts a selection-screen login must not touch: a window open, a login on its way, or a window
        closed a moment ago (the server needs a moment to take it offline). Call under self.lock."""
        settle = self.s.launch.close_settle
        return ({a.account for a in self.alts.values()} | {ROLE_NAME.match(n)[1] for n in self.pending}
                | {a for a, t in self.closed_at.items() if now - t < settle})

    def next_delete(self, conn):
        """Pick the next role to delete and reserve its account (under the lock the pulls also take)."""
        rows = [(r['name'], r['account']) for r in conn.execute(
            'SELECT name, account FROM alts WHERE phase=? AND quarantined=0 ORDER BY phase_since, char_id', (DELETE,))
            if r['account'] in self.accounts]
        now = time.monotonic()
        skip = {n for n, until in self.delete_skip.items() if until > now}
        with self.lock:
            # one window on top of the cap is the account worker's own (the cap is full most of the time; ~10 s each)
            name = pick_delete(rows, self._busy_accounts(now), skip, len(self.alts) + len(self.pending),
                               self.s.policy.max_windows + 1)
            if name is not None:
                self.deleting = ROLE_NAME.match(name)[1]
        return name

    def deleted_rows(self, conn):
        return [(r['name'], r['account'], r['deleted_at']) for r in conn.execute(
            "SELECT name, account, deleted_at FROM alts WHERE phase='deleted' ORDER BY deleted_at, char_id")
            if r['account'] in self.accounts and ROLE_NAME.match(r['name'])]

    def next_rebuild(self, conn):
        """The account of the oldest deleted role whose slot should be free now; reserved like a delete."""
        rows = self.deleted_rows(conn)
        known = {r['name'] for r in conn.execute('SELECT name FROM alts')}
        now = time.monotonic()
        skip = {a for a, until in self.rebuild_skip.items() if until > now}
        with self.lock:
            account = pick_rebuild(rows, known, self._busy_accounts(now), skip, time.time(), self.s.rebuild_after,
                                   len(self.alts) + len(self.pending), self.s.policy.max_windows + 1)
            if account is not None:
                self.deleting = account
        return account

    def rebuild_one(self, conn, account):
        deleted = [name for name, acct, _ in self.deleted_rows(conn) if acct == account]
        known = {r['name'] for r in conn.execute('SELECT name FROM alts')}
        res = RebuildJob(self.s.launch, self.accounts[account], deleted, known, self.own, self.throttle,
                         self.s.factory.db_path).run()
        if res['created']:
            self.rebuilt += len(res['created'])
            self.log.info('%s 重建了 %s，本次共重建 %d 个；它们会作为新角色排进古井', account, ', '.join(res['created']),
                          self.rebuilt)
        if res['error'] or res['not_released'] or not res['created']:
            self.rebuild_skip[account] = time.monotonic() + self.s.rebuild_retry
            why = res['error'] or ('删除的槽位还没释放' if res['not_released'] else '没有要建的')
            self.log.info('%s 暂不重建: %s（%.0f 分钟后再看）', account, why, self.s.rebuild_retry / 60)

    def delete_one(self, conn, name):
        row = conn.execute('SELECT * FROM alts WHERE name=?', (name,)).fetchone()
        account = self.accounts[row['account']]
        res = AccountDeleteJob(self.s.delete, account, [row], {}, self.own, self.throttle,
                               self.s.factory.db_path).run()[0]
        if res['ok']:
            self.deleted += 1
            self.log.info('%s 已删除（%s），本次共删 %d 个', name, '之前已删' if res.get('skipped') else
                          f'服务器 {res.get("reply_ms")}ms 回复', self.deleted)
            return
        err = res.get('error') or '失败'
        # '不删: ...' = a check refused (nothing sent): leave it for this run, a human looks at it. Other errors
        # (login, server) are retried later; AccountDeleteJob counts them (3 -> quarantine).
        refused = err.startswith('不删')
        self.delete_skip[name] = float('inf') if refused else time.monotonic() + DELETE_RETRY
        self.log.warning('%s 没删: %s%s', name, err, '（本次运行不再试）' if refused else
                         f'（{DELETE_RETRY / 60:.0f} 分钟后再试）')

    def status(self):
        with self.lock:
            alts = list(self.alts.values())
            pending = len(self.pending)
        c = count_sides((a.phase, a.level) for a in alts)
        sides = ' '.join(f'{label} {c.get(k, 0)}' for k, label in ((UPSTREAM, '上游'), (WELL, '古井'), (COAST_WAIT, '海岸等'),
                                                                   (FARMING_SIDE, '刷怪'), (DOWNSTREAM, '下游'), (OTHER, '其他')))
        st = ', '.join(f'{r["station_id"]}={r["status"]}' for r in self.station_rows())
        dishes = self.conn.execute("SELECT COUNT(*) FROM events WHERE kind='receive' AND at>=?", (self.started_at,)
                                   ).fetchone()[0]
        waiting = self.conn.execute('SELECT COUNT(*) FROM alts WHERE phase=? AND quarantined=0', (DELETE,)).fetchone()[0]
        self.log.info('窗口 %d/%d（登录中 %d）| %s | 本次收料理 %d | 待删 %d 本次删 %d%s | 本次重建 %d%s | 工位: %s',
                      len(alts), self.s.policy.max_windows, pending, sides, dishes, waiting, self.deleted,
                      '' if self.s.delete else '（删除未启用）', self.rebuilt,
                      '' if self.s.rebuild_after else '（重建未启用）', st)

    # ---- main
    def run(self):
        self.started_at = time.time()
        self.adopt()
        threads = []
        for st in self.station_rows(COAST):
            threads.append(threading.Thread(target=self.worker, args=(st, self.coast_body), name=st['station_id'],
                                             daemon=True))
        for st in self.station_rows(RECEIVER):
            threads.append(threading.Thread(target=self.worker, args=(st, self.receiver_body), name=st['station_id'],
                                             daemon=True))
        for st in self.station_rows(WELL_ROLE):
            threads.append(threading.Thread(target=self.worker, args=(st, self.well_body), name=st['station_id'],
                                             daemon=True))
        for st in self.station_rows(DISPATCHER):
            threads.append(threading.Thread(target=self.worker, args=(st, self.dispatcher_body),
                                             name=st['station_id'], daemon=True))
        if self.s.delete or self.s.rebuild_after:
            threads.append(threading.Thread(target=self.account_loop, name='account', daemon=True))
        threads.append(threading.Thread(target=self.chores_loop, name='chores', daemon=True))
        self.log.info('工人: %s；小号窗口上限 %d，同时登录 %d 个', ', '.join(t.name for t in threads),
                      self.s.policy.max_windows, self.s.parallel_logins)
        if self.relogin:
            self.log.info('工位掉线自动重登: 开（读不到角色 %.0f 秒就关窗重登；配置里的工位 %s）', self.relogin.lost_after,
                          ', '.join(self.relogin.stations))
        elif getattr(self.s, 'relogin_error', None):
            self.log.error('工位掉线自动重登没开: %s', self.s.relogin_error)
        else:
            self.log.info('工位掉线自动重登: 关（supervisor.toml station_relogin = false）')
        for t in threads:
            t.start()
        last_status = 0.0
        while True:
            try:
                self.manage()
            except Exception as e:
                self.log.error('窗口管理出错: %s', e, exc_info=True)
            if time.monotonic() - last_status >= STATUS_EVERY:
                self.status()
                last_status = time.monotonic()
            time.sleep(MANAGE_EVERY)


def main():
    cfg = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'supervisor.toml'
    log_path = log.setup(ROOT / 'logs', prefix='supervisor')
    logger = log.for_account('main')
    logger.info('日志文件: %s', log_path)
    try:
        s = load_supervisor(cfg)
    except Exception as e:
        logger.error('配置错误 (%s): %s', cfg, e)
        return 2
    sup = Supervisor(s, logger)
    try:
        return sup.run()
    except KeyboardInterrupt:
        sup.stop.set()
        logger.warning('已手动停止。窗口保留，重新运行会接管它们接着做')
        return 130


if __name__ == '__main__':
    sys.exit(main())
