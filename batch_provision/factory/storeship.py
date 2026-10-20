"""料理仓库号 stage 2b: the dispatcher gives every store role its gold and ferries it to the receiver's post.

Entry: python -m factory.storeship [store.toml]   (一键仓库号就位.cmd)
Starts from the factory.db stores rows with status village_ready (stage 2a, factory/store.py): roles standing at the
village spawn (1266,1174) with 35 empty bag slots. Per role (one window each, provisioner AccountRun, closed after):
  village (map 1):  board the ferry -> the dispatcher (stations.toml / local.toml [[station]] role dispatcher; logged
                    in by this tool when it is not online) walks to the spawn, gives [ship] gold (factory/gold.py
                    trade, verified by the role's gold), forms a team, takes it to 平静海岸2区 through PP鸡 and goes
                    home by 回城卷, which disbands the team (factory/transport.py TransportRun, the stage-5 code)
  coast (map 81):   walk to factory.toml receiver_post (1780,1370), stand still, check the position
  then the window closes (= logged out there) and the stores row becomes ready (就绪) with map, x, y, gold.
Roles of one account cannot be online together, so one ferry trip takes up to 4 roles of different accounts; roles
are taken slot-major (box07仓1, box08仓1, ..). Every step starts from what the client shows, so the .cmd can be
stopped anywhere and double-clicked again: ready rows are skipped, a role already on the coast just walks.
Refuses to start while the supervisor is driving the dispatcher. Stage 2c (the supervisor using the stores) is not here.
Pure parts: load_ship, ship_order, supervisor_busy, should_sail, decide_spawn, decide_park (tests/test_factory_storeship.py).
"""
import dataclasses
import json
import math
import sys
import threading
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from provisioner import config, log, native, procs
from provisioner.game import Game
from provisioner.login import LaunchThrottle
from provisioner.memory import ProcessMemory
from provisioner.pipeline import AccountRun, OwnWindows
from provisioner.procs import Client, game_pids
from provisioner.world import read_gold, read_world

from . import db
from .coast import Walk, decide_goto
from .config import ROOT, load_settings
from .gold import GoldJob
from .phase import COAST_MAP, DISPATCHER, VILLAGE_MAP
from .stations import login_stations
from .store import store_names
from .transport import TransportRun
from .wellteam import SPAWN

SPAWN_NEAR = 150         # a role this close to the spawn can trade (200) and be invited (300) by the dispatcher there
NAV_RETRY = 3.0
STALL = 6.0
# Dispatcher heartbeats the supervisor writes while it works ('waiting' every 2 s, the others once per batch)
SUPERVISOR_STATUS = {'waiting': 60.0, 'transporting': 600.0, 'supplying': 600.0}
SHIP_STATUS = 'store_ship'


@dataclass(frozen=True)
class ShipSettings:
    gold: int = 1000            # each store role gets this much from the dispatcher (verified: role gold >= gold)
    timeout: float = 600.0      # one role: login waits for the ferry, then the walk to the post
    gather: float = 20.0        # the ferry waits this long for more riders still logging in (max 4 per trip)
    post_range: float = 40.0    # standing this close to receiver_post counts as parked
    settle: float = 2.0         # stand still this long at the post before logging out (server position catches up)
    tick: float = 0.2


def load_ship(data):
    s = data.get('ship', {})
    out = ShipSettings(gold=int(s.get('gold', 1000)), timeout=float(s.get('timeout', 600)),
                       gather=float(s.get('gather', 20)), post_range=float(s.get('post_range', 40)),
                       settle=float(s.get('settle', 2.0)), tick=float(s.get('tick', 0.2)))
    if out.gold < 190:
        raise ValueError(f'[ship] gold = {out.gold} 不够 PP鸡 传送费 190')
    return out


# ---- pure decisions ---------------------------------------------------------------------------------------

def ship_order(rows, names_of):
    """[(account, slot, name)] of the stores rows still to ship (status village_ready, name as configured),
    slot-major so that the roles next to each other belong to different accounts (one ferry trip = up to 4)."""
    todo = [(r['account'], r['slot'], r['name']) for r in rows
            if r['status'] == db.STORE_VILLAGE_READY and r['account'] in names_of
            and r['slot'] <= len(names_of[r['account']]) and names_of[r['account']][r['slot'] - 1] == r['name']]
    return sorted(todo, key=lambda t: (t[1], t[0]))


def supervisor_busy(status, heartbeat_at, now):
    """The dispatcher's stations row says the supervisor is using it right now (fresh working heartbeat)."""
    fresh = SUPERVISOR_STATUS.get(status or '')
    return fresh is not None and now - (heartbeat_at or 0) < fresh


def should_sail(waiting, size, oldest_wait, gather, coming):
    """Ferry: leave with the riders waiting now? coming = riders still logging in that could join this trip."""
    if waiting <= 0:
        return False
    return waiting >= size or coming <= 0 or oldest_wait >= gather


@dataclass(frozen=True)
class Decision:
    kind: str
    reason: str
    arg: object = None


def decide_spawn(world, last_nav, now):
    """A store role in the village before boarding: next to the spawn (where the dispatcher trades and invites)?
    'near' | 'walk' | 'wait' | 'fail'."""
    if world is None:
        return Decision('wait', '加载中')
    if world.map_id != VILLAGE_MAP:
        return Decision('fail', f'不在逍遥村西区（地图 {world.map_id}）')
    distance = math.dist((world.x, world.y), SPAWN)
    if distance <= SPAWN_NEAR and not world.moving:
        return Decision('near', f'在出生点旁（距离 {distance:.0f}）')
    if world.in_battle or world.busy or world.verification or world.nav_active or world.moving:
        return Decision('wait', f'走向出生点（距离 {distance:.0f}）或忙')
    if now - last_nav < NAV_RETRY:
        return Decision('wait', '等寻路开始')
    return Decision('walk', f'离出生点 {distance:.0f}，走过去', (VILLAGE_MAP, *SPAWN))


def decide_park(world, post, post_range, settle):
    """At the receiver's post? 'parked' (stood still `settle` s within post_range) | 'wait' | 'off'."""
    if world is None:
        return Decision('wait', '加载中')
    distance = math.dist((world.x, world.y), post)
    if world.map_id != COAST_MAP or distance > post_range:
        return Decision('off', f'不在收货点（地图 {world.map_id}，距离 {distance:.0f}）')
    if world.moving or world.nav_active or world.still_for < settle:
        return Decision('wait', f'在收货点站稳（距离 {distance:.0f}）')
    return Decision('parked', f'停在收货点 ({world.x:.0f},{world.y:.0f})，距离 {distance:.0f}')


# ---- the ferry (dispatcher) -------------------------------------------------------------------------------

class StoreGoldJob(GoldJob):
    """The stage-3 gold trade for a store role: no alts row, failures counted here (3 tries)."""

    def __init__(self, *args):
        super().__init__(*args)
        self.tries = 0

    def register(self):
        pass

    def quarantined(self):
        return False

    def failed(self, reason):
        self.tries += 1
        return self.tries >= db.MAX_RETRIES


class StoreTransport(TransportRun):
    """The stage-5 trip for store roles: alts = the riders of this trip, no leases / pending actions / quarantine."""

    def __init__(self, *args):
        super().__init__(*args)
        self.tries = {}

    def claim(self, cids):
        return list(cids)

    def renew(self, cids):
        pass

    def release(self, cids):
        pass

    def note_invite(self, m):
        pass

    def note_invite_unsent(self, m, error):
        pass

    def note_joined(self, m):
        pass

    def failed(self, m, reason):
        self.tries[m.c.char_id] = self.tries.get(m.c.char_id, 0) + 1
        return self.tries[m.c.char_id] >= db.MAX_RETRIES

    def gold_job(self, m):
        return StoreGoldJob(self.conn, self.disp, self.dmem, self.dgame, m.c, m.account, m.slot, self.s, m.log)

    def sail(self):
        """-> {char_id: error or None}. Raises when the dispatcher itself fails."""
        w = read_world(self.dmem)
        if w is None:
            raise RuntimeError('读不到调度员的状态')
        if w.map_id == COAST_MAP:
            self.log.info('调度员在平静海岸2区（上次中断），先回城')
            self.disband_and_return()
            self.trip, self.started = type(self.trip)(), time.monotonic()
            self.home = type(self.home)()
        team = self.to_rendezvous()
        self.add_members(self.claim(list(self.alts)))
        self.log.info('本趟 %d 人: %s（队里原有 %d 人）', len(self.members),
                      ', '.join(m.c.name for m in self.members.values()), len(team.members))
        self.fund()
        self.form()
        if not [m for m in self.active() if m.state == 'ready']:
            raise RuntimeError('没有仓库号入队，不传送')
        self.travel()
        self.disband_and_return()
        out = {}
        for cid, m in self.members.items():
            mw = read_world(m.mem)
            if m.state == 'done' and mw is not None and mw.map_id == COAST_MAP:
                out[cid] = None
            else:
                out[cid] = m.error or f'没到平静海岸2区（地图 {mw.map_id if mw else "?"}，{m.state}）'
        self.log.info('调度员金币 %s，本趟用时 %.1fs', read_gold(self.dmem), time.monotonic() - self.started)
        return out


class Rider:
    def __init__(self, client, account, slot, logger):
        self.c, self.account, self.slot, self.log = client, account, slot, logger
        self.boarded_at = time.monotonic()
        self.done = threading.Event()
        self.error = 'ferry not run'


class Ferry:
    """One thread drives the dispatcher; role threads board() and block until their trip is over."""

    def __init__(self, station, disp, fsettings, ship, logger):
        self.station, self.disp, self.log = station, disp, logger
        self.s = dataclasses.replace(fsettings, gold_amount=ship.gold, gold_topup_below=ship.gold)
        self.ship = ship
        self.cond = threading.Condition()
        self.queue, self.coming = [], set()
        self.closed, self.broken = False, None
        self.trips = 0
        self.thread = threading.Thread(target=self._loop, name='ferry', daemon=True)

    def start(self):
        self.thread.start()

    def arrive(self, key):
        with self.cond:
            self.coming.add(key)

    def gone(self, key):
        with self.cond:
            self.coming.discard(key)
            self.cond.notify_all()

    def board(self, key, rider):
        """-> None when the rider is on the coast, else the error."""
        with self.cond:
            self.coming.discard(key)
            if self.broken:
                return f'调度员出错，本次不再摆渡: {self.broken}'
            self.queue.append(rider)
            self.cond.notify_all()
        if not rider.done.wait(self.ship.timeout):
            return f'{self.ship.timeout:.0f}s 内没轮到调度员摆渡'
        return rider.error

    def close(self):
        with self.cond:
            self.closed = True
            self.cond.notify_all()
        self.thread.join()

    def _next_batch(self):
        size = self.s.transport_team_size
        with self.cond:
            while True:
                now = time.monotonic()
                oldest = now - self.queue[0].boarded_at if self.queue else 0.0
                if should_sail(len(self.queue), size, oldest, self.ship.gather, len(self.coming)):
                    batch, self.queue = self.queue[:size], self.queue[size:]
                    return batch
                if self.closed and not self.queue:
                    return None
                self.cond.wait(0.5)

    def _loop(self):
        conn = db.connect(self.s.db_path)
        try:
            with ProcessMemory(self.disp.session.pid, self.disp.session.base) as dmem:
                while (batch := self._next_batch()) is not None:
                    self._sail(conn, dmem, batch)
        except Exception as e:      # noqa: BLE001 - every waiting rider must be released
            self.log.error('调度员线程出错: %s', e, exc_info=True)
            self._break(f'{type(e).__name__}: {e}', [])
        finally:
            conn.close()

    def _sail(self, conn, dmem, batch):
        self.trips += 1
        riders = {r.c.char_id: (r.c, r.account, r.slot) for r in batch}
        self.log.info('== 第 %d 趟摆渡: %s ==', self.trips, ', '.join(r.c.name for r in batch))
        db.heartbeat(conn, self.station['station_id'], DISPATCHER, self.disp.char_id, SHIP_STATUS, time.time())
        run = StoreTransport(conn, self.station, self.disp, dmem, riders, self.s, self.log)
        try:
            out = run.sail()
            for r in batch:
                r.error = out.get(r.c.char_id, '不在本趟队伍里')
        except Exception as e:      # noqa: BLE001 - the dispatcher failed: stop ferrying, the .cmd can be rerun
            self.log.error('第 %d 趟失败: %s', self.trips, e, exc_info=not isinstance(e, RuntimeError))
            self._break(f'{type(e).__name__}: {e}', batch)
        finally:
            run.close()
            for r in batch:
                r.done.set()
            db.heartbeat(conn, self.station['station_id'], DISPATCHER, self.disp.char_id, 'idle', time.time())

    def _break(self, error, batch):
        with self.cond:
            self.broken = error
            waiting, self.queue = self.queue, []
        for r in batch + waiting:
            r.error = f'调度员出错: {error}'
            r.done.set()


# ---- one store role ---------------------------------------------------------------------------------------

class ShipRun(AccountRun):
    """provisioner pipeline for one store role (login -> enter), then ferry + walk to the post; stores row after."""

    def __init__(self, s, account, slot, expected, throttle, own, account_lock, run_id, ship, fsettings, ferry):
        super().__init__(s, account, slot, throttle, own, account_lock, run_id)
        self.expected, self.ship, self.fs, self.ferry = expected, ship, fsettings, ferry
        self.key = (account.name, slot)

    def before_enter(self, char_id, name):
        if name != self.expected:
            raise RuntimeError(f'槽{self.slot} 是 {name}，不是 {self.expected}；不处理（请检查这个账号的角色）')

    def in_world(self, session, char_id, name, world, r):
        client = Client(session, char_id, name, world.map_id, world.x, world.y)
        with ProcessMemory(session.pid, session.base) as mem:
            game = Game(session, mem)
            try:
                if world.map_id == VILLAGE_MAP:
                    self._step('出生点等调度员')
                    self._to_spawn(session, mem, game, char_id)
                    self.log.info('金币 %s，上船', read_gold(mem))
                    self._step('调度员发金币 + PP鸡')
                    error = self.ferry.board(self.key, Rider(client, self.account.name, self.slot, self.log))
                    if error:
                        raise RuntimeError(error)
                elif world.map_id != COAST_MAP:
                    raise RuntimeError(f'角色在地图 {world.map_id}，既不是逍遥村西区也不是平静海岸2区，不处理')
                else:
                    self.ferry.gone(self.key)
                    self.log.info('已在平静海岸2区（上次传送过来了），直接走去收货点')
                self._step('走到收货点')
                r.update(self._park(session, mem, game, char_id))
            finally:
                game.close()

    def _to_spawn(self, session, mem, game, char_id):
        started, last_nav, last = time.monotonic(), -1e9, None
        while True:
            if time.monotonic() - started > 60:
                raise RuntimeError('60s 内没走到出生点')
            if not native.alive(session.pid):
                raise RuntimeError('游戏进程已退出')
            w = read_world(mem)
            if w and w.char_id != char_id:
                raise RuntimeError(f'角色变了 {char_id} -> {w.char_id}')
            now = time.monotonic()
            d = decide_spawn(w, last_nav, now)
            if d.reason != last:
                self.log.info('%s', d.reason)
            last = d.reason
            if d.kind == 'near':
                if w.nav_active:
                    game.cancel_navigation()
                return
            if d.kind == 'fail':
                raise RuntimeError(d.reason)
            if d.kind == 'walk':
                game.navigate(*d.arg)
                last_nav = now
            time.sleep(self.ship.tick)

    def _park(self, session, mem, game, char_id):
        """Walk to receiver_post on map 81 and stand still there. -> dict(map_id, x, y, gold)."""
        post = self.fs.receiver_post
        started, walk, last = time.monotonic(), Walk(), None
        while True:
            now = time.monotonic()
            if now - started > self.ship.timeout:
                raise RuntimeError(f'{self.ship.timeout:.0f}s 内没走到收货点 {post}')
            if not native.alive(session.pid):
                raise RuntimeError('游戏进程已退出')
            w = read_world(mem)
            if w and w.char_id != char_id:
                raise RuntimeError(f'角色变了 {char_id} -> {w.char_id}')
            p = decide_park(w, post, self.ship.post_range, self.ship.settle)
            if p.kind == 'parked':
                gold = read_gold(mem)
                self.log.info('%s，金币 %s', p.reason, gold)
                return {'map_id': w.map_id, 'x': round(w.x), 'y': round(w.y), 'gold': gold}
            walk.observe(w, now)
            d = decide_goto(w, post, walk, now, '去收货点') if p.kind == 'off' else p
            if d.reason != last:
                self.log.info('%s', d.reason)
            last = d.reason
            if d.kind == 'lost':
                raise RuntimeError(d.reason)
            if d.kind == 'navigate':
                game.navigate(*d.arg[:3])
            elif d.kind == 'cancel_nav':
                game.cancel_navigation()
            if d.kind in ('navigate', 'cancel_nav'):
                walk.record(d, w, now)
            time.sleep(self.ship.tick)

    def run(self):
        with self.account_lock:
            self.ferry.arrive(self.key)
            try:
                r = self._run()
            finally:
                self.ferry.gone(self.key)
        conn = db.connect(self.fs.db_path)
        try:
            old = db.store(conn, self.account.name, self.slot)
            status = db.STORE_READY if r['ok'] else (old['status'] if old else db.STORE_VILLAGE_READY)
            db.save_store(conn, self.account.name, self.slot, self.expected, status, time.time(),
                          char_id=r.get('char_id'), map_id=r.get('map_id'), x=r.get('x'), y=r.get('y'),
                          gold=r.get('gold'), error=r.get('error'))
            db.log_event(conn, time.time(), 'store', f'{self.expected} {status} 地图 {r.get("map_id")} '
                         f'({r.get("x")},{r.get("y")}) 金币 {r.get("gold")}'
                         f'{" " + r["error"] if r.get("error") else ""}', char_id=r.get('char_id'))
        finally:
            conn.close()
        return r


# ---- the dispatcher ----------------------------------------------------------------------------------------

def dispatcher_online(conn, logger):
    """Log the dispatcher station in (or adopt its open window). -> (stations row, procs.Client) or raises."""
    enter_settings, stations = config.load_stations(ROOT / 'stations.toml')
    disp = [s for s in stations if s.role == DISPATCHER]
    if len(disp) != 1:
        raise RuntimeError(f'stations.toml / local.toml 里启用的调度员应正好 1 个，实际 {len(disp)} 个')
    st = disp[0]
    row = db.station(conn, st.station_id)
    if row and supervisor_busy(row['status'], row['heartbeat_at'], time.time()):
        raise RuntimeError(f'总大脑正在使用调度员（状态 {row["status"]}，{time.time() - row["heartbeat_at"]:.0f}s 前）；'
                           '先停总大脑再运行')
    clients = procs.discover(logger)
    c = next((c for c in clients if st.name and c.name == st.name), None)
    if c is not None and not (row and row['char_id'] == c.char_id):
        db.register_station(conn, st.station_id, st.role, c.char_id, st.account.name, c.name, c.session.pid,
                            time.time())
        logger.info('调度员 %s 已在本工具窗口在线 pid=%d，登记', c.name, c.session.pid)
    if c is None:
        results = login_stations(conn, logger, enter_settings, [st])
        if not results or not results[0]['ok']:
            raise RuntimeError(f'调度员登录失败: {results[0].get("error") if results else "?"}')
    row = db.station(conn, st.station_id)
    c = next((c for c in procs.discover(logger) if c.char_id == row['char_id']), None)
    if c is None:
        raise RuntimeError(f'调度员 {row["name"]} 登记了但找不到它的窗口')
    return row, c


def main():
    cfg_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'store.toml'
    log_path = log.setup(ROOT / 'logs', prefix='storeship')
    logger = log.for_account('main')
    logger.info('日志文件: %s', log_path)
    try:
        create = config.load(cfg_path)
        pipe = config.load_pipeline(cfg_path)
        ship = load_ship(tomllib.loads(cfg_path.read_text('utf-8')))
        names = {a.name: store_names(create, a.name) for a in create.accounts}
        fs = load_settings(ROOT / 'factory.toml')
    except Exception as e:
        logger.error('配置错误 (%s): %s', cfg_path, e)
        return 2
    if not native.LAUNCHER.is_file():
        logger.error('缺少 %s，请先运行 native\\build.ps1', native.LAUNCHER)
        return 2
    conn = db.connect(fs.db_path)
    rows = db.stores(conn)
    todo = ship_order(rows, names)
    ready = [r['name'] for r in rows if r['status'] == db.STORE_READY and r['account'] in names]
    logger.info('仓库账号 %s；数据库 %s；已就绪 %d 个，待送到收货点 %d 个: %s', ', '.join(names), fs.db_path,
                len(ready), len(todo), ', '.join(t[2] for t in todo))
    if not todo:
        logger.info('没有村里已腾格（village_ready）的仓库号要送；先运行 一键建仓库号.cmd')
        conn.close()
        return 0
    try:
        station, disp = dispatcher_online(conn, logger)
    except Exception as e:
        logger.error('%s', e, exc_info=not isinstance(e, (RuntimeError, ValueError)))
        conn.close()
        return 2
    with ProcessMemory(disp.session.pid, disp.session.base) as dmem:
        disp_gold = read_gold(dmem)
    logger.info('调度员: %s pid=%d 地图 %d (%.0f,%.0f) 金币 %s；每个仓库号给 %d', disp.name, disp.session.pid,
                disp.map_id, disp.x, disp.y, disp_gold, ship.gold)
    db.heartbeat(conn, station['station_id'], DISPATCHER, disp.char_id, SHIP_STATUS, time.time())
    conn.close()
    logger.info('启动前已有游戏进程（不会被关闭）: %s', game_pids())

    accounts = {a.name: a for a in create.accounts}
    throttle = LaunchThrottle(pipe.launch_interval, pipe.min_free_memory_mb)
    run_id = time.strftime('%Y%m%d_%H%M%S')
    started = time.monotonic()
    ferry = Ferry(station, disp, fs, ship, log.for_account('调度员'))
    ferry.start()
    own = OwnWindows(pipe.max_windows, logger)
    locks = {a: threading.Lock() for a in accounts}
    try:
        with ThreadPoolExecutor(max_workers=pipe.max_windows, thread_name_prefix='ship') as pool:
            results = list(pool.map(lambda t: ShipRun(pipe, accounts[t[0]], t[1], t[2], throttle, own, locks[t[0]],
                                                      run_id, ship, fs, ferry).run(), todo))
    finally:
        ferry.close()
    seconds = time.monotonic() - started
    out = ROOT / 'logs' / f'{log_path.stem.replace("storeship_", "storeship_summary_")}.json'
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), 'utf-8')
    logger.info('=' * 60)
    for r in results:
        logger.info('%-10s %s 地图=%s 坐标=(%s,%s) 金币=%s%s', r.get('role') or f"{r['account']}#{r['slot']}",
                    '就绪' if r['ok'] else '失败', r.get('map_id'), r.get('x'), r.get('y'), r.get('gold'),
                    f" | {r['step']} {r['error']}" if r.get('error') else '')
    ok = sum(r['ok'] for r in results)
    logger.info('完成 %d/%d，摆渡 %d 趟，总用时 %.0fs，本工具残留窗口 %d。汇总: %s', ok, len(results), ferry.trips,
                seconds, own.count(), out)
    return 0 if ok == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
