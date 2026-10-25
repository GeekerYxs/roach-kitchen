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
    record 飞鞋 (stage 2), go home when lost, accept quest 78 (stage 6), hand in (stage 8), sell junk at 花袭人
    (factory/sell.py), leave a team nobody
    leads for us
  - window manager (main thread): reap dead / disconnected windows, close finished / quarantined ones and ones whose
    phase has no worker yet, and pull the next role by name when a queue is short (decide_pull + pick_roles)
Stage 11c runs the whole line except delete (11d): roles waiting for delete are neither pulled nor kept open.
Stage A (factory/relogin.py): a station whose window shows no character for `station_lost_seconds` is closed, and a
station whose process is gone is logged in again from stations.toml (`station_relogin`).
Ctrl+C stops; windows stay open and the next start adopts them (roles of the configured accounts with our DLL).
"""
import contextlib
import logging
import os
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path

from provisioner import config, layout, log, native, procs
from provisioner import enter as enter_mod
from provisioner import login as login_mod
from provisioner.enter import EnterJob, enter_role, verify_in_world
from provisioner.game import Game, NotSent
from provisioner.login import LaunchThrottle, login, read_session
from provisioner.memory import ProcessMemory
from provisioner.minimize import Minimizer
from provisioner.novice import NoviceJob, NoviceSettings
from provisioner.pipeline import OwnWindows, last_rosters, online_elsewhere, remember_roster
from provisioner.world import read_bag, read_bag_capacity, read_team, read_world

from . import db, heartbeat, maintenance, outage, progress
from .coast import CoastRun
from .config import load_settings
from .delete import AccountDeleteJob, DeleteSettings
from .rebuild import RebuildJob
from .relogin import (KILL_SETTLE, Watch, check_entered, decide_watch, may_kill, other_login_running, probe,
                      relogin_delay, relogin_due, relogin_mark)
from .stations import foreign_windows
from .items import table as item_table
from .supply import Gate as SupplyGate, load_supply_file, run_supply
from .treasury import Treasury, load_treasury_file
from .handin import HandinJob
from .home import HomeJob
from .meat import MeatJob
from .observe import observe
from .phase import (ACCEPT_QUEST, COAST, COAST_MAP, DELETE, DISPATCHER, EAT_MEAT, HANDIN, LEAVE_TEAM, NOVICE,
                    QUEUE_COAST, QUEUE_RECEIVER, QUEUE_TRANSPORT, QUEUE_WELL, RECEIVER, RECORD_SHOE, RETURN_HOME,
                    SELL_JUNK, TRANSPORTING, UNKNOWN, VILLAGE_MAP, WAIT_DISBAND, derive_phase)
from .phase import WELL as WELL_ROLE
from .quest import QuestJob
from .receiver import PostRun, ReceiveJob, bag_alarm, bag_text, dish_count, hours_left, read_room
from .storeuse import StoreUnload, load_unload, read_local, should_unload, stores_text, validate as validate_stores
from .runner import ROLE_NAME
from .shoe import ShoeJob
from .transport import TransportRun
from .wellteam import LeaderUnheard, WellTeamRun
from .welltrain import WellTrainRun
from .sell import SellJob
from .schedule import (COAST_WAIT, DOWNSTREAM, FARMING_SIDE, OTHER, PULL_COAST, PULL_FRESH, UPSTREAM, WELL, Known,
                       PullPolicy, alt_window_cap, close_reason, count_sides, decide_pull, has_candidate, pick_delete, pick_rebuild, pick_roles, retry_quarantined,
                       team_ready)

ROOT = Path(__file__).resolve().parent.parent
CHORE_EVERY = 2.0
MANAGE_EVERY = 3.0
STATUS_EVERY = 60.0
LOGIN_FAIL_LIMIT = 3            # a role that failed to log in / enter this often is left alone for this run
FAIL_STREAK_LIMIT = 4           # this many logins in a row failed (any roles) -> stop pulling for a while:
FAIL_STREAK_PAUSE = 300.0       # a systematic fault must not run through every role (2026-10-13: 20 roles x 3)
LEAVE_WAIT = 5.0
UNHEARD_RESTART = 2             # batches in a row whose invitations reached nobody -> close + relogin the station
DRAIN_EVERY = 5.0               # state/drain.json (planned maintenance, factory/maintenance.py) re-read this often
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


class NotOnRoster(RuntimeError):
    """The login worked but the account has no role of that name: not a system fault, never try it again."""


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
    minimize: bool = False              # [batch] minimize: minimize this tool's alt windows once (provisioner/minimize)
    arrange: bool = True                # [batch] arrange: lay the station windows out (provisioner/layout)
    supply: object = None               # factory.supply.SupplySettings ([supply] in factory.toml), None = off
    treasury: object = None             # factory.treasury.TreasurySettings ([treasury] in factory.toml), None = off
    unload: object = None               # factory.storeuse.UnloadSettings ([receiver] stores), None = no store roles
    window_budget: str = ''             # how policy.max_windows was cut to the per-IP window limit (logged at start)
    outage: object = None               # factory.outage.OutageSettings ([outage]), None = off
    stall: dict = None                  # station role -> seconds without progress before close + relogin (B4a)


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


def configured_stations(s, relogin, db_path):
    """How many stations this machine runs: the enabled [[station]] entries (offline ones included: their window
    must stay free); if the stations config cannot be read, the stations in factory.db."""
    if relogin:
        return len(relogin.stations)
    try:
        return len(config.load_stations(ROOT / s.get('stations', 'stations.toml'))[1])
    except Exception:           # noqa: BLE001 - fall back to what the stations tool registered
        if not Path(db_path).is_file():
            return 0
        conn = db.connect(db_path)
        try:
            return conn.execute('SELECT COUNT(*) FROM stations').fetchone()[0]
        finally:
            conn.close()


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
    game = data.get('game', {})
    cap, budget = alt_window_cap(policy.max_windows, config.ip_max_clients(game),
                                 configured_stations(s, relogin, factory.db_path), config.ip_reserve(game))
    policy = replace(policy, max_windows=cap)
    return SupSettings(login_settings, factory, policy, float(s.get('coast_max_wait', 90)),
                       max(1, int(s.get('parallel_logins', 4))), float(s.get('idle_close', 60)), NOT_SERVED,
                       float(s.get('well_max_wait', 90)), float(s.get('transport_max_wait', 30)),
                       bool(s.get('fresh', True)), launch if bool(s.get('delete', True)) else None, launch,
                       rebuild_after, float(s.get('rebuild_retry_minutes', 20)) * 60,
                       float(s.get('quarantine_retry_hours', 2)) * 3600, relogin, relogin_error,
                       bool(data.get('batch', {}).get('minimize', False)),
                       bool(data.get('batch', {}).get('arrange', True)),
                       load_supply_file(ROOT / s.get('factory', 'factory.toml')),
                       load_treasury_file(ROOT / s.get('factory', 'factory.toml')),
                       load_unload(data, read_local(path)), budget, outage.load_outage(data),
                       progress.load_limits(s, factory))


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
        self.throttle = LaunchThrottle.of(s.login)
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
        self.supply = getattr(s, 'supply', None)
        self.supply_gate = SupplyGate(self.supply.retry_after) if self.supply else None
        self.sellable = item_table() if self.supply else {}
        ts = getattr(s, 'treasury', None)
        self.treasury = Treasury(ts, self.receiver_client) if ts and ts.enabled else None
        self.well_gate = TeamGate(s.well_max_wait)
        # well_buffer, coast_buffer and coast_backlog are per leader of that kind: more leaders, longer queues
        wells = max(1, len(self.station_rows(WELL_ROLE)))
        coasts = max(1, len(self.station_rows(COAST)))
        self.policy = replace(s.policy, well_buffer=s.policy.well_buffer * wells,
                              coast_buffer=s.policy.coast_buffer * coasts,
                              coast_backlog=s.policy.coast_backlog * coasts)
        self.last_quarantine_check = 0.0
        self.recv_room = (None, 0.0)    # (receiver_body's last BagRoom, monotonic time it was read)
        self.full_warned = -1e9         # last 'receiver bag full' error, monotonic
        us = getattr(s, 'unload', None)
        self.unloader = StoreUnload(us, s.factory, s.login, self.throttle, self.own, logger) if us else None
        self.unload_after = 0.0         # monotonic: no unload before (after a failed one)
        self.bag_blocked = {}           # station_id -> alarm text: bag still short of room after selling (supply)
        self.relogin = getattr(s, 'relogin', None)
        self.station_pids = frozenset()     # read by the minimizer thread: never minimize a station window
        self.watches = {}               # station_id -> relogin.Watch
        self._drain = (-DRAIN_EVERY, None)    # (monotonic read time, reason) of state/drain.json
        self.login_log = outage.LoginLog()    # every login's result (provisioner.login.RESULT_HOOK), stage B3
        self.enter_log = outage.LoginLog()    # every enter-world result (provisioner.enter.RESULT_HOOK)
        self.guarded = False                  # started by the guard: a mass login failure ends this process
        self.outage_warned = 0.0
        self.tracks = {}                      # station_id -> progress.Track (stage B4a)
        self.progress_checked = 0.0
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

    def arrange_stations(self, conn, lg, only=None):
        """Lay the station windows out ([batch] arrange); only = pids to move, the others keep where the user put
        them."""
        if not getattr(self.s, 'arrange', True):
            return
        rows = layout.order(conn.execute('SELECT station_id, role, pid FROM stations').fetchall())
        try:
            moved = layout.arrange([r['pid'] if native.has_dll(r['pid']) else None for r in rows], only)
        except Exception as e:      # noqa: BLE001 - never take the run down for a window chore
            lg.warning('排列工位窗口出错: %s', e)
            return
        if moved:
            lg.info('排列工位窗口: %s', ', '.join(f'pid={p} ({x},{y})' for p, x, y in moved))

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
    def draining(self):
        """Reason the guard asked for no new work (maintenance coming), or None. Logins, pulls, deletes, rebuilds
        and new leader batches wait; running batches, chores and the receiver go on."""
        at, reason = self._drain
        if time.monotonic() - at >= DRAIN_EVERY:
            reason = maintenance.drain_reason(maintenance.read_drain(maintenance.DRAIN_PATH))
            if reason != self._drain[1]:
                self.log.warning('%s', f'{reason}：不再开新批次、不拉人、不删号' if reason else '收尾结束，恢复正常')
            self._drain = (time.monotonic(), reason)
        return reason

    def worker(self, st, body):
        """Keep one station working; its window missing or an error only pauses this station. Missing with its
        process gone -> log it in again (stage A); missing with the process alive -> the watcher closes it first."""
        sid = st['station_id']
        lg = log.for_account(st['name'] or sid)
        conn = db.connect(self.s.factory.db_path)
        fails, unheard, warned = 0, 0, 0.0
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
                if body != self.receiver_body and self.draining():
                    self.stop.wait(10)
                    continue
                try:
                    body(conn, st, me, lg)
                    fails = unheard = 0
                except Stopped:
                    break
                except Exception as e:
                    fails += 1
                    lg.error('工位出错（连续 %d 次）: %s', fails, e, exc_info=not isinstance(e, RuntimeError))
                    # the failed batch's members go back to their queues now (they used to stay held forever)
                    if freed := db.release_station(conn, sid, time.time(), f'工位出错: {e}'):
                        lg.warning('放开这一批的 %d 个小号 %s，它们按各自进度回队列', len(freed), freed)
                    unheard = unheard + 1 if isinstance(e, LeaderUnheard) else 0
                    if unheard >= UNHEARD_RESTART and self.restart_station(conn, st, lg, unheard):
                        unheard = 0
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

    def restart_station(self, conn, st, lg, batches):
        """The station's invitations reached nobody `batches` batches in a row: close its window so the worker logs
        it in again (the same checks as watch_stations). True = closed."""
        sid = st['station_id']
        if not self.relogin or sid not in self.relogin.stations:
            lg.error('工位连续 %d 批邀请都没人收到，但它不能自动重登，所以不关；请人工重开这个工位', batches)
            return False
        w = self.watch(sid)
        h, hwnd = probe(st['pid'], st['char_id'])
        if h != 'ok' or not may_kill(w.hwnd, hwnd, self.own.owns(st['pid'])):
            lg.error('工位连续 %d 批邀请都没人收到，但窗口身份对不上，不关；请人工看一下', batches)
            return False
        native.kill(st['pid'])
        w.next_try = max(w.next_try, time.monotonic() + KILL_SETTLE)
        lg.warning('工位 pid=%d 连续 %d 批邀请都没人收到，已关窗，准备自动重登', st['pid'], batches)
        db.log_event(conn, time.time(), 'station', f'邀请没人收到，关窗重登 pid={st["pid"]}', station_id=sid)
        return True

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

    def watch_progress(self):
        """Stage B4a: a leader finishing no batch for too long while alts wait for it -> close its window; the
        worker's relogin (stage A) brings it back."""
        now = time.time()
        draining = self.draining() is not None
        for st in self.station_rows():
            role, sid = st['role'], st['station_id']
            limit = self.s.stall.get(role)
            if role not in progress.QUEUES:
                continue
            track = self.tracks.setdefault(sid, progress.Track(since=now))
            alive = bool(st['pid']) and native.alive(st['pid'])
            waiting = len(db.waiting(self.conn, progress.QUEUES[role], now)) if alive and not draining else 0
            progress.observe(track, now, alive, draining, waiting)
            kinds = progress.KINDS[role]
            last_done = self.conn.execute(
                f'SELECT MAX(at) FROM events WHERE station_id=? AND kind IN ({",".join("?" * len(kinds))})',
                (sid, *kinds)).fetchone()[0]
            idle = progress.stalled(track, last_done, now, limit)
            if idle is None:
                continue
            lg = log.for_account(st['name'] or sid)
            track.since, track.waiting_since = now, None       # one action per limit, whatever happens next
            text = f'{idle / 60:.0f} 分钟没完成一批，期间一直有小号在排队'
            if not self.relogin or sid not in self.relogin.stations:
                lg.error('工位 %s（pid=%d）%s；自动重登没开 / 不在工位配置里，不关窗，请人工看一下', sid, st['pid'], text)
                continue
            _, hwnd = probe(st['pid'], st['char_id'])
            if not may_kill(self.watch(sid).hwnd, hwnd, self.own.owns(st['pid'])):
                lg.error('工位 %s（pid=%d）%s，但窗口身份对不上（pid 可能被系统复用），不关；请人工看一下', sid, st['pid'], text)
                continue
            native.kill(st['pid'])
            w = self.watch(sid)
            w.next_try = max(w.next_try, time.monotonic() + KILL_SETTLE)
            lg.warning('工位 %s（pid=%d）%s：卡住了，已关窗，准备自动重登', sid, st['pid'], text)
            db.log_event(self.conn, now, 'station', f'无进展关窗 pid={st["pid"]}：{text}', station_id=sid)

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
        db.heartbeat(conn, sid, st['role'], st['char_id'], relogin_mark(os.getpid()), time.time())
        lg.warning('工位不在线，自动重登 %s 槽%d（第 %d 次）', cfg.account.name, cfg.account.slot, w.fails + 1)
        r = EnterJob(self.relogin.enter, cfg.account, self.throttle.uncapped()).run()   # its window is budgeted
        err, permanent = check_entered(r, st['char_id'], name)
        if err is None:
            db.register_station(conn, sid, st['role'], r['char_id'], cfg.account.name, r['role'], r['pid'],
                                time.time())
            w.fails, w.next_try, w.hwnd, w.lost_since = 0, 0.0, r.get('hwnd'), None
            lg.info('工位重登成功: %s pid=%d 地图 %s，接着干活', r['role'], r['pid'], r.get('map_id'))
            self.station_pids = self.station_pids | {r['pid']}
            self.arrange_stations(conn, lg, only={r['pid']})     # back into its slot (and out of the minimizer's)
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
            team = read_team(mem)
            if team is not None and len(team.members) <= 1:
                self.supply_errand(conn, st, leader, mem, lg, village=False)
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
                    if self.unload_due(rmem):
                        self.unload(conn, recv, rmem, rgame, lg)
                        continue
                    if self.bag_full(rmem, lg):
                        db.heartbeat(conn, sid, RECEIVER, recv.char_id, 'bag_full', time.time())
                        self.stop.wait(10.0)
                        continue
                    alts = self.snapshot()
                    for r in db.waiting(conn, QUEUE_RECEIVER, time.time()):
                        cid = r['char_id']
                        if self.stop.is_set() or cid not in alts:
                            continue
                        if self.bag_full(rmem, lg):     # the 料理 just received may have filled the last slot
                            break
                        if not db.claim(conn, sid, [cid], fs.receive_lease, time.time()):
                            continue
                        c = alts[cid][0]
                        try:
                            with self.receiver_lock():      # a treasury top-up uses the receiver too
                                res = ReceiveJob(conn, sid, recv, rmem, rgame, c, fs, log.for_account(c.name)).run()
                        finally:
                            db.release(conn, sid, [cid], time.time())
                        self._failed(conn, cid, res)
                    db.heartbeat(conn, sid, RECEIVER, recv.char_id, 'receiving', time.time())
                    self.stop.wait(2.0)
            finally:
                rgame.close()

    def unload_due(self, rmem):
        """Stage 2c: the receiver is at receiver_bag_warn empty slots or fewer and has 料理 for the store roles."""
        if self.unloader is None or not self.s.factory.dish_trade or time.monotonic() < self.unload_after:
            return False
        return should_unload(read_room(rmem), dish_count(read_bag(rmem)), self.s.factory.receiver_bag_warn)

    def unload(self, conn, recv, rmem, rgame, lg):
        """Hand the receiver's 料理 to the store roles (factory/storeuse.py); the alts wait in their queue meanwhile."""
        lg.info('%s，到报警线（%d 格）：先把料理交给仓库号，小号排队等着', bag_text(read_room(rmem)),
                self.s.factory.receiver_bag_warn)
        with self.receiver_lock():      # a treasury top-up uses the receiver too
            res = self.unloader.run(conn, recv, rmem, rgame, self.stop)
        lg.info('交给仓库号 %d 个料理（%s）；%s', res['moved'], ', '.join(r['name'] for r in res['stores']) or '无',
                bag_text(read_room(rmem)))
        if not res['ok'] and not self.stop.is_set():
            self.unload_after = time.monotonic() + self.unloader.us.retry_minutes * 60
            lg.error('交料理给仓库号没做完（%s），%.0f 分钟后再试；这期间照常收货，满了就停收', res.get('error'),
                     self.unloader.us.retry_minutes)

    def bag_full(self, rmem, lg):
        """Read the receiver's bag for status(); True when not one more 料理 fits. Then no alt is claimed: a trade
        into a full bag fails and would quarantine the alt (db.MAX_RETRIES), so the alts wait in their queue.
        Without the 料理 trade (dish_trade = false) only gold comes in: never full, no bag figures."""
        if not self.s.factory.dish_trade:
            return False
        room = read_room(rmem)
        self.recv_room = (room, time.monotonic())
        if bag_alarm(room, self.s.factory.receiver_bag_warn) != 'full':
            return False
        if time.monotonic() - self.full_warned >= STATUS_EVERY:
            self.full_warned = time.monotonic()
            lg.error('%s，停止收货（小号留在队列里等着，不隔离）；请换收货人（docs/DEPLOY.md 第 10 节）或把料理转走',
                     bag_text(room))
        return True

    def receiver_client(self, conn):
        """The treasury = the receiver station's window (procs.Client), or None when it is not online."""
        row = conn.execute('SELECT char_id FROM stations WHERE role=? ORDER BY station_id', (RECEIVER,)).fetchone()
        return self.scan().get(row['char_id']) if row else None

    def supply_errand(self, conn, st, client, mem, lg, village):
        """Between two batches: buy what runs low, sell junk (factory/supply.py), get gold from the treasury when
        short (factory/treasury.py). Never raises."""
        if self.supply is None or (not self.supply.enabled and self.treasury is None):
            return
        db.heartbeat(conn, st['station_id'], st['role'], st['char_id'], 'supplying', time.time())
        res = run_supply(conn, st, client, mem, self.s.factory, self.supply, self.sellable, self.supply_gate, lg,
                         village, self.treasury)
        self.note_blocked(st['station_id'], res, read_bag(mem), read_bag_capacity(mem))

    def note_blocked(self, sid, res, bag, cap):
        """Keep status()'s alarm for a leader whose bag selling could not clear: set / cleared by a supply run's
        result; without a run (nothing due, failed, paused) cleared only once the bag has room again."""
        with self.lock:
            if res is not None:
                text = res.get('blocked')
            elif bag is not None and cap is not None and cap - len(bag) >= self.supply.sell_below_free:
                text = None
            else:
                return
            if text:
                self.bag_blocked[sid] = text
            else:
                self.bag_blocked.pop(sid, None)

    def receiver_lock(self):
        return self.treasury.lock if self.treasury else contextlib.nullcontext()

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
                self.supply_errand(conn, st, leader, mem, lg, village=True)
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
                self.supply_errand(conn, st, disp, mem, lg, village=True)
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
        elif plan.phase == SELL_JUNK:
            job, label = SellJob(c, aw.account, aw.slot, fs, lg), '卖杂物'
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
        """factory.db roles of the CONFIGURED accounts only: after switching this machine to another range
        (e.g. mw301..380 -> mw201..280) the old range's rows stay in the db, and pulling one would fail (no password)."""
        out = {}
        for r in self.conn.execute('SELECT * FROM alts'):
            if r['account'] not in self.accounts:
                continue
            obs = db.last_observation(self.conn, r['char_id']) if r['obs_json'] else None
            out[r['name']] = Known(r['name'], r['account'], r['phase'], obs.level if obs else None,
                                   bool(r['quarantined']), r['deleted_at'] is not None, r['phase_since'])
        return out

    def manage(self):
        self.station_pids = frozenset(r['pid'] for r in self.station_rows())
        if self.relogin:
            self.watch_stations()
        if self.s.stall and time.monotonic() - self.progress_checked >= progress.CHECK_EVERY:
            self.progress_checked = time.monotonic()
            self.watch_progress()
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
        if time.monotonic() < self.pull_paused_until or self.draining():
            return
        known = self.known()
        rosters = last_rosters()
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
                                                              open_accounts, skip, rosters)
            d = decide_pull(counts, len(alts) + len(pending), self.policy, have_coast, have_fresh)
            if d.kind is None or len(pending) >= self.s.parallel_logins:
                return
            name = pick_roles(d.kind, known, self.names_in_order, open_accounts, skip, 1, rosters)[0]
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
                raise NotOnRoster(f'选角列表里没有 {name}（有 {[n for _, _, n in roster]}）')
            char_id = roster[index][0]
            enter_role(session, index + 1, self.s.login.enter_timeout, lg, account.name)
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
        except NotOnRoster as e:
            self.login_fails[name] = LOGIN_FAIL_LIMIT       # never again this run; rosters.json skips it next run
            self.fail_streak = 0                            # the login itself worked
            lg.warning('%s，本次运行不再拉它（不算系统故障）', e)
            if session:
                self.own.close(session, lg)
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
                if self.draining():
                    self.stop.wait(DELETE_EVERY)
                    continue
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
        room, read_at = self.recv_room
        if time.monotonic() - read_at > 2 * STATUS_EVERY:      # receiver offline or busy: do not show old numbers
            room = None
        bag = bag_text(room, self.bag_hours(room)) if self.s.factory.dish_trade else '料理不交易（收货人只收金币）'
        if self.unloader and self.s.factory.dish_trade:
            bag += ' | ' + stores_text(db.stores(self.conn), self.unloader.names)
        self.log.info('窗口 %d/%d（登录中 %d）| %s | 本次%s %d | %s | 待删 %d 本次删 %d%s | 本次重建 %d%s | 工位: %s',
                      len(alts), self.s.policy.max_windows, pending, sides,
                      '收料理' if self.s.factory.dish_trade else '交完（任务+金币）', dishes, bag, waiting, self.deleted,
                      '' if self.s.delete else '（删除未启用）', self.rebuilt,
                      '' if self.s.rebuild_after else '（重建未启用）', st)
        with self.lock:
            stuck = list(self.bag_blocked.values())
        for text in stuck:
            self.log.warning('%s', text)
        alarm = bag_alarm(room, self.s.factory.receiver_bag_warn)
        if alarm == 'full':
            self.log.error('！！%s：收货已停，请换收货人（docs/DEPLOY.md 第 10 节）', bag)
        elif alarm == 'low':
            self.log.warning('！%s，快满了（报警线 %d 格）：%s', bag, self.s.factory.receiver_bag_warn,
                             '会交给仓库号' if self.unloader else '请准备换收货人，或在 local.toml [receiver] stores 写仓库账号')

    def production(self):
        """Output figures for the guard's output floor (stage B4b): 料理 received in the last hour, alts waiting
        downstream (coast + receiver queues), receiver bag full. None when they cannot be read (no restart then)."""
        try:
            now = time.time()
            dishes = self.conn.execute("SELECT COUNT(*) FROM events WHERE kind='receive' AND at>=?",
                                       (now - 3600,)).fetchone()[0]
            waiting = len(db.waiting(self.conn, QUEUE_COAST, now)) + len(db.waiting(self.conn, QUEUE_RECEIVER, now))
            room, read_at = self.recv_room
            full = room is not None and time.monotonic() - read_at <= 2 * STATUS_EVERY and                 bag_alarm(room, self.s.factory.receiver_bag_warn) == 'full'
            return {'dishes_hour': dishes, 'waiting': waiting, 'bag_full': full}
        except Exception as e:      # noqa: BLE001 - the heartbeat itself must go out
            self.log.debug('产量数字读不到: %s', e)
            return None

    def check_outage(self):
        """Many accounts failing to log in (stage B3): under the guard, exit with a code it acts on; alone, warn."""
        if not self.s.outage:
            return None
        now = time.time()
        v = (outage.verdict(self.login_log.rows(), now, self.s.outage)
             or outage.enter_verdict(self.enter_log.rows(), now, self.s.outage))
        if v is None:
            return None
        if v == outage.VERSION:
            text = '登录器报游戏版本不对（游戏客户端更新了？），重试没用，要人工更新程序'
        elif v == outage.ENTER:
            text = (f'{self.s.outage.window / 60:.0f} 分钟内 {self.s.outage.min_accounts} 个以上账号能登录、但进不了游戏，'
                    '一个都没进去（服务器拒绝？维护后多半是客户端要更新）')
        else:
            text = (f'{self.s.outage.window / 60:.0f} 分钟内 {self.s.outage.min_accounts} 个以上账号登录失败、'
                    '一个都没登上（服务器维护 / 断网？）')
        if self.guarded:
            self.stop.set()
            self.log.error('%s：总大脑退出，交给守护处理', text)
            return {outage.VERSION: outage.EXIT_VERSION, outage.ENTER: outage.EXIT_ENTER}.get(v, outage.EXIT_OUTAGE)
        if time.monotonic() - self.outage_warned >= 600:
            self.log.error('%s（没用一键守护，不会自动停工）', text)
            self.outage_warned = time.monotonic()
        return None

    def bag_hours(self, room):
        """Hours until the receiver's bag is full at this run's 料理 rate over the last hour."""
        seconds = min(3600.0, time.time() - self.started_at)
        received = self.conn.execute("SELECT COUNT(*) FROM events WHERE kind='receive' AND at>=?",
                                     (time.time() - seconds,)).fetchone()[0]
        return hours_left(room, received, seconds)

    # ---- main
    def run(self):
        self.started_at = time.time()
        heartbeat.write(heartbeat.PATH, os.getpid(), self.started_at)
        if self.unloader and not validate_stores(self.conn, self.unloader.us, self.log):
            self.log.error('[receiver] stores 名单有问题（见上面），总大脑不启动')
            return 2
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
        if self.s.window_budget:
            self.log.info('%s', self.s.window_budget)
        if self.relogin:
            self.log.info('工位掉线自动重登: 开（读不到角色 %.0f 秒就关窗重登；配置里的工位 %s）', self.relogin.lost_after,
                          ', '.join(self.relogin.stations))
        elif getattr(self.s, 'relogin_error', None):
            self.log.error('工位掉线自动重登没开: %s', self.s.relogin_error)
        else:
            self.log.info('工位掉线自动重登: 关（supervisor.toml station_relogin = false）')
        self.station_pids = frozenset(r['pid'] for r in self.station_rows())
        self.arrange_stations(self.conn, self.log)
        if self.s.minimize:
            Minimizer(self.log, self.stop, skip=lambda: self.station_pids).start()
        for t in threads:
            t.start()
        last_status = last_beat = 0.0
        while True:
            if time.monotonic() - last_beat >= heartbeat.EVERY:
                heartbeat.write(heartbeat.PATH, os.getpid(), self.started_at, info=self.production())
                last_beat = time.monotonic()
            if (code := self.check_outage()) is not None:
                return code
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
    other = heartbeat.other_running(heartbeat.read(heartbeat.PATH), os.getpid(), time.time(), native.alive)
    if other:
        logger.error('另一个总大脑 (pid=%d) 正在运行，不能同时开两个；要重开请先关掉它（或它的一键守护）', other)
        return 3
    try:
        s = load_supervisor(cfg)
    except Exception as e:
        logger.error('配置错误 (%s): %s', cfg, e)
        return 2
    sup = Supervisor(s, logger)
    sup.guarded = os.environ.get(outage.GUARD_ENV) == '1'
    login_mod.RESULT_HOOK = sup.login_log.add
    enter_mod.RESULT_HOOK = sup.enter_log.add
    try:
        return sup.run()
    except KeyboardInterrupt:
        sup.stop.set()
        logger.warning('已手动停止。窗口保留，重新运行会接管它们接着做')
        return 130


if __name__ == '__main__':
    sys.exit(main())
