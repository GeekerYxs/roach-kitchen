"""料理仓库号 stage 2b: store roles get trained to level 10, get their gold, and are ferried to the receiver's post.

Entry: python -m factory.storeship [store.toml]   (一键仓库号就位.cmd)
Starts from the factory.db stores rows with status village_ready (stage 2a, factory/store.py): roles standing at the
village spawn (1266,1174) with 35 empty bag slots. Per role (one window each, provisioner AccountRun, closed after):
  village, level < [ship] min_level (PP鸡 needs level 10, live 2026-10-21; 11 like the alts):
                    eat ONE 地瓜 (stores.potato_at, never twice), board the well boat -> a well leader (the first
                    enabled [[station]] role well) forms a team at the spawn (stage-5 invite code), trains it in 阴森古井
                    until everyone is min_level (factory/welltrain.py WellTrainRun, the stage-4b code), members go home
                    by their 回城卷 (lands next to 小美), the leader by its own
  village:          sell the well drops at 小美 with the alt rule (factory/items.py; factory/store.py VillagePrep), check
                    [store] free_min empty slots, then board the ferry (twice at most) -> the dispatcher ([[station]] role dispatcher) walks to the spawn, gives [ship] gold
                    (factory/gold.py trade, verified by the role's gold), forms a team, takes it to 平静海岸2区 through
                    PP鸡 and goes home by 回城卷, which disbands the team (factory/transport.py TransportRun, stage 5)
  coast (map 81):   walk to factory.toml receiver_post (1780,1370), stand still, check the position
  then the window closes (= logged out there) and the stores row becomes ready (就绪) with map, x, y, gold.
The two leaders are logged in (or their open windows adopted) only when a role first needs them. Roles of one account
cannot be online together, so a trip takes up to 4 roles of different accounts; roles are taken slot-major (box07仓1,
box08仓1, ..), [ship] slots limits which slots this run handles. Every step starts from what the client shows, so the
.cmd can be stopped anywhere and double-clicked again: ready rows are skipped, a role already at min_level skips the
well, a role already on the coast just walks. Refuses a leader the supervisor is driving. Stage 2c (the supervisor using
the stores) is not here.
Pure parts: load_ship, ship_order, supervisor_busy, should_sail, decide_spawn, decide_park (tests/test_factory_storeship.py).
"""
import dataclasses
import json
import math
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from provisioner import config, log, native, procs
from provisioner.game import Game
from provisioner.login import LaunchThrottle
from provisioner.memory import ProcessMemory
from provisioner.pipeline import AccountRun, OwnWindows
from provisioner.procs import Client, game_pids
from provisioner.game import NotSent
from provisioner.world import item_count, read_bag, read_dialog, read_gold, read_level, read_team, read_world

from . import db
from . import items
from .coast import Walk, decide_goto
from .config import ROOT, load_settings
from .gold import GoldJob
from .phase import COAST_MAP, DISPATCHER, POTATO_ITEM, VILLAGE_MAP, WELL
from .stations import login_stations
from .store import VillagePrep, load_store, store_names
from .transport import TransportRun
from .welltrain import WellTrainRun
from .wellteam import SPAWN

SPAWN_NEAR = 150         # a role this close to the spawn can trade (200) and be invited (300) by a leader there
NAV_RETRY = 3.0
STALL = 6.0
# Station heartbeats the supervisor writes while it works ('waiting' every 2 s, 'training' every 10 s, the others once
# per batch): such a fresh status means the supervisor is driving that leader now
SUPERVISOR_STATUS = {'waiting': 60.0, 'training': 60.0, 'forming': 600.0, 'transporting': 600.0, 'supplying': 600.0}
SHIP_STATUS, TRAIN_STATUS = 'store_ship', 'store_train'
EAT_WAIT = 5.0           # the 地瓜 count must drop this long after the 0x49
BAG_SETTLE = 0.5         # right after entering the world the bag reads empty (box08仓2 2026-10-21: read 2 ms after
BAG_WAIT = 5.0           # entering, its 2 地瓜 not loaded yet): the same non-empty reading twice this far apart counts
GOLD_RETRY_PAUSE = 2.0   # after a gold trade that did not arrive: close the role's dialog, wait, try again


@dataclass(frozen=True)
class ShipSettings:
    gold: int = 1000            # each store role gets this much from the dispatcher (verified: role gold >= gold)
    min_level: int = 11         # PP鸡 refuses roles below 10: a well leader trains them first (11 like the alts)
    gold_tries: int = 5         # gold trades per ferry trip before the role waits for the next trip
    ferry_tries: int = 2        # trips a role boards before giving up for this run
    slots: tuple = (1, 2, 3, 4)  # which slots of each store account this run handles
    timeout: float = 600.0      # one role: waiting for the ferry, then the walk to the post
    train_timeout: float = 2400.0   # one role: waiting for the well boat and the training
    gather: float = 20.0        # a boat waits this long for more riders still logging in (max 4 per trip)
    post_range: float = 40.0    # standing this close to receiver_post counts as parked
    settle: float = 2.0         # stand still this long at the post before logging out (server position catches up)
    tick: float = 0.2


def load_ship(data):
    s = data.get('ship', {})
    out = ShipSettings(gold=int(s.get('gold', 1000)), min_level=int(s.get('min_level', 11)),
                       gold_tries=int(s.get('gold_tries', 5)), ferry_tries=int(s.get('ferry_tries', 2)),
                       slots=tuple(int(x) for x in s.get('slots', (1, 2, 3, 4))),
                       timeout=float(s.get('timeout', 600)), train_timeout=float(s.get('train_timeout', 2400)),
                       gather=float(s.get('gather', 20)), post_range=float(s.get('post_range', 40)),
                       settle=float(s.get('settle', 2.0)), tick=float(s.get('tick', 0.2)))
    if out.gold < 190:
        raise ValueError(f'[ship] gold = {out.gold} 不够 PP鸡 传送费 190')
    if not out.slots or any(not 1 <= x <= 4 for x in out.slots):
        raise ValueError(f'[ship] slots 应是 1..4 里的槽号，实际 {list(out.slots)}')
    return out


# ---- pure decisions ---------------------------------------------------------------------------------------

def ship_order(rows, names_of, slots=(1, 2, 3, 4)):
    """[(account, slot, name)] of the stores rows still to ship (status village_ready, name as configured, slot in
    `slots`), slot-major so that the roles next to each other belong to different accounts (a trip = up to 4)."""
    todo = [(r['account'], r['slot'], r['name']) for r in rows
            if r['status'] == db.STORE_VILLAGE_READY and r['account'] in names_of and r['slot'] in slots
            and r['slot'] <= len(names_of[r['account']]) and names_of[r['account']][r['slot'] - 1] == r['name']]
    return sorted(todo, key=lambda t: (t[1], t[0]))


def supervisor_busy(status, heartbeat_at, now):
    """A station row says the supervisor is using that leader right now (fresh working heartbeat)."""
    fresh = SUPERVISOR_STATUS.get(status or '')
    return fresh is not None and now - (heartbeat_at or 0) < fresh


def should_sail(waiting, size, oldest_wait, gather, coming):
    """Boat: leave with the riders waiting now? coming = riders still logging in that could join this trip."""
    if waiting <= 0:
        return False
    return waiting >= size or coming <= 0 or oldest_wait >= gather


@dataclass(frozen=True)
class Decision:
    kind: str
    reason: str
    arg: object = None


def decide_spawn(world, last_nav, now):
    """A store role in the village before boarding: next to the spawn (where the leaders trade and invite)?
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


def bag_settled(previous, current):
    """Two bag readings BAG_SETTLE apart: loaded? (a store role always carries something after stage 2a)"""
    return bool(current) and previous == current


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


# ---- the leaders' runs for store roles (no alts rows: no leases, pending actions or quarantine) -------------

class StoreGoldJob(GoldJob):
    """The stage-3 gold trade for a store role: tries counted here; after a trade whose gold did not arrive, log
    what both sides show (box09仓1 2026-10-21: 3 trades, gold stayed 65, cause unknown) and close the role's dialog."""

    def __init__(self, *args, max_tries=5):
        super().__init__(*args)
        self.tries, self.max_tries = 0, max_tries

    def register(self):
        pass

    def quarantined(self):
        return False

    def unconfirmed(self, alt_w, disp_w, game):
        alt_d, disp_d = read_dialog(game.mem), read_dialog(self.disp_mem)
        alt_t, disp_t = read_team(game.mem), read_team(self.disp_mem)
        self.log.warning('金币没到账，现场: 仓库号 %s 对话框=%s 队伍=%s；调度员 %s 对话框=%s 队伍=%s',
                         describe_world(alt_w), alt_d, alt_t, describe_world(disp_w), disp_d, disp_t)
        if alt_d is not None:
            self.log.info('仓库号有对话框开着，先关掉')
            try:
                game.select_dialog(0)
            except NotSent as e:
                self.log.warning('关对话框没发出: %s', e)
        time.sleep(GOLD_RETRY_PAUSE)

    def failed(self, reason):
        self.tries += 1
        if self.tries >= self.max_tries:
            raise RuntimeError(f'交易 {self.tries} 次金币都没到账（{reason}）')
        return False


def describe_world(w):
    if w is None:
        return '读不到'
    return (f'地图 {w.map_id} ({w.x:.0f},{w.y:.0f}) flags={w.flags:#x} 忙={w.busy} 战斗={w.in_battle} '
            f'寻路={w.nav_active} 验证={w.verification}')


class StoreTransport(TransportRun):
    """The stage-5 team + trip for store roles: alts = the riders of this trip."""
    gold_tries = 5

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
        return StoreGoldJob(self.conn, self.disp, self.dmem, self.dgame, m.c, m.account, m.slot, self.s, m.log,
                            max_tries=self.gold_tries)

    def board(self):
        """Leader to the spawn, riders into its team. -> the members that joined."""
        team = self.to_rendezvous()
        self.add_members(self.claim(list(self.alts)))
        self.log.info('本趟 %d 人: %s（队里原有 %d 人）', len(self.members),
                      ', '.join(m.c.name for m in self.members.values()), len(team.members))

    def errors(self, want_map):
        out = {}
        for cid, m in self.members.items():
            mw = read_world(m.mem)
            ok = m.state == 'done' and mw is not None and mw.map_id == want_map
            out[cid] = None if ok else m.error or f'没到地图 {want_map}（现在 {mw.map_id if mw else "?"}，{m.state}）'
        return out

    def sail(self):
        """Dispatcher: gold, team, PP鸡, home. -> {char_id: error or None}. Raises when the dispatcher fails."""
        w = read_world(self.dmem)
        if w is None:
            raise RuntimeError('读不到调度员的状态')
        if w.map_id == COAST_MAP:
            self.log.info('调度员在平静海岸2区（上次中断），先回城')
            self.disband_and_return()
            self.trip, self.home, self.started = type(self.trip)(), type(self.home)(), time.monotonic()
        self.board()
        self.fund()
        self.form()
        if not [m for m in self.active() if m.state == 'ready']:
            raise RuntimeError('没有仓库号入队，不传送')
        self.travel()
        self.disband_and_return()
        self.log.info('调度员金币 %s，本趟用时 %.1fs', read_gold(self.dmem), time.monotonic() - self.started)
        return self.errors(COAST_MAP)


class StoreTrainRun(WellTrainRun):
    """The stage-4b training for store roles: to [ship] min_level, home by 回城卷 (they have no 飞鞋 point)."""

    def release(self, m):
        pass

    def claim(self, cids):
        return list(cids)

    def bookkeep(self, wall):
        db.heartbeat(self.conn, self.station['station_id'], WELL, self.leader.char_id, TRAIN_STATUS, wall)

    def shoe_ok(self, m, w, wall):
        return False

    def note_home(self, m, wall):
        pass

    def note_return(self, m, action, wall):
        pass

    def note_return_failed(self, m, reason, wall):
        pass

    def note_stuck(self, m, reason, wall):
        pass


class StoreTrain:
    """Well leader: form a team of riders at the spawn (stage-5 invite code), train it (stage 4b), all go home."""

    def __init__(self, conn, station, leader, lmem, riders, fs, ship, logger):
        self.conn, self.station, self.leader, self.lmem = conn, station, leader, lmem
        self.riders, self.fs, self.ship, self.log = riders, fs, ship, logger
        self.crew = None

    def close(self):
        if self.crew:
            self.crew.close()

    def train(self, alts):
        run = StoreTrainRun(self.conn, self.station, self.leader, self.lmem, alts, self.fs, self.log)
        run.target = self.ship.min_level
        try:
            return {r['char_id']: r for r in run.run()}
        finally:
            run.close()

    def sail(self):
        w = read_world(self.lmem)
        if w is None:
            raise RuntimeError('读不到古井队长的状态')
        if w.map_id != VILLAGE_MAP:
            self.log.info('古井队长不在逍遥村西区（地图 %d，上次中断），先回村', w.map_id)
            self.train({})
        self.crew = StoreTransport(self.conn, self.station, self.leader, self.lmem, self.riders, self.fs, self.log)
        self.crew.who = '古井队长'
        self.crew.board()
        self.crew.form()
        joined = {m.c.char_id for m in self.crew.active() if m.state == 'ready'}
        out = {cid: m.error or '没有入队' for cid, m in self.crew.members.items() if cid not in joined}
        self.crew.close()
        self.crew = None
        if not joined:
            raise RuntimeError('没有仓库号入队，不去古井')
        results = self.train({cid: self.riders[cid] for cid in joined})
        for cid in joined:
            r = results.get(cid)
            if r is None:
                out[cid] = '不在古井队长的队里'
            elif not r['ok'] or (r['level'] or 0) < self.ship.min_level:
                out[cid] = r['error'] or f'没练到 {self.ship.min_level} 级（{r["level"]} 级，地图 {r["map"]}）'
            else:
                out[cid] = None
        return out


class Rider:
    def __init__(self, client, account, slot, logger):
        self.c, self.account, self.slot, self.log = client, account, slot, logger
        self.boarded_at = time.monotonic()
        self.done = threading.Event()
        self.error = 'ferry not run'


class Ferry:
    """A boat: one thread drives a leader; role threads board() and block until their trip is over.
    connect(conn) -> (stations row, procs.Client) is called at the first trip; make_run(conn, station, client,
    leader_mem, riders) -> object with sail() -> {char_id: error or None} and close()."""

    def __init__(self, name, connect, make_run, size, ship, timeout, db_path, logger):
        self.name, self.connect, self.make_run, self.size = name, connect, make_run, size
        self.ship, self.timeout, self.db_path, self.log = ship, timeout, db_path, logger
        self.cond = threading.Condition()
        self.queue, self.coming = [], set()
        self.closed, self.broken = False, None
        self.trips = 0
        self.thread = threading.Thread(target=self._loop, name=name, daemon=True)

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
        """-> None when the trip worked for this rider, else the error."""
        with self.cond:
            self.coming.discard(key)
            if self.broken:
                return f'{self.name}出错，本次不再带人: {self.broken}'
            self.queue.append(rider)
            self.cond.notify_all()
        if not rider.done.wait(self.timeout):
            return f'{self.timeout:.0f}s 内没轮到{self.name}'
        return rider.error

    def close(self):
        with self.cond:
            self.closed = True
            self.cond.notify_all()
        self.thread.join()

    def _next_batch(self):
        with self.cond:
            while True:
                now = time.monotonic()
                oldest = now - self.queue[0].boarded_at if self.queue else 0.0
                if should_sail(len(self.queue), self.size, oldest, self.ship.gather, len(self.coming)):
                    batch, self.queue = self.queue[:self.size], self.queue[self.size:]
                    return batch
                if self.closed and not self.queue:
                    return None
                self.cond.wait(0.5)

    def _loop(self):
        conn, batch = None, []
        try:
            batch = self._next_batch()
            if batch is None:
                return
            conn = db.connect(self.db_path)
            station, client = self.connect(conn)
            with ProcessMemory(client.session.pid, client.session.base) as lmem:
                while batch is not None:
                    self._sail(conn, station, client, lmem, batch)
                    batch = self._next_batch()
        except Exception as e:      # noqa: BLE001 - every waiting rider must be released
            self.log.error('%s线程出错: %s', self.name, e, exc_info=not isinstance(e, RuntimeError))
            self._break(f'{type(e).__name__}: {e}', batch or [])
        finally:
            if conn is not None:
                conn.close()

    def _sail(self, conn, station, client, lmem, batch):
        self.trips += 1
        riders = {r.c.char_id: (r.c, r.account, r.slot) for r in batch}
        self.log.info('== %s第 %d 趟: %s ==', self.name, self.trips, ', '.join(r.c.name for r in batch))
        run = self.make_run(conn, station, client, lmem, riders)
        try:
            out = run.sail()
            for r in batch:
                r.error = out.get(r.c.char_id, '不在本趟队伍里')
        except Exception as e:      # noqa: BLE001 - the leader failed: stop this boat, the .cmd can be rerun
            self.log.error('%s第 %d 趟失败: %s', self.name, self.trips, e, exc_info=not isinstance(e, RuntimeError))
            self._break(f'{type(e).__name__}: {e}', batch)
        finally:
            run.close()
            for r in batch:
                r.done.set()
            db.heartbeat(conn, station['station_id'], station['role'], client.char_id, 'idle', time.time())

    def _break(self, error, batch):
        with self.cond:
            self.broken = error
            waiting, self.queue = self.queue, []
        for r in batch + waiting:
            r.error = f'{self.name}出错: {error}'
            r.done.set()


# ---- one store role ---------------------------------------------------------------------------------------

class ShipRun(AccountRun):
    """provisioner pipeline for one store role (login -> enter), then well + ferry + walk to the post; stores row."""

    def __init__(self, s, account, slot, expected, throttle, own, account_lock, run_id, ship, fsettings, store_s,
                 well, ferry):
        super().__init__(s, account, slot, throttle, own, account_lock, run_id)
        self.expected, self.ship, self.fs, self.store_s = expected, ship, fsettings, store_s
        self.well, self.ferry = well, ferry
        self.key = (account.name, slot)

    def before_enter(self, char_id, name):
        if name != self.expected:
            raise RuntimeError(f'槽{self.slot} 是 {name}，不是 {self.expected}；不处理（请检查这个账号的角色）')

    def in_world(self, session, char_id, name, world, r):
        client = Client(session, char_id, name, world.map_id, world.x, world.y)
        with ProcessMemory(session.pid, session.base) as mem:
            game = Game(session, mem)
            try:
                level = read_level(mem)
                r['level'] = level
                if world.map_id == VILLAGE_MAP and level is not None and level < self.ship.min_level:
                    self._step(f'古井队长带练到 {self.ship.min_level} 级（现在 {level} 级）')
                    self._potato(mem, game)
                    self._to_spawn(session, mem, game, char_id)
                    error = self.well.board(self.key, Rider(client, self.account.name, self.slot, self.log))
                    if error:
                        raise RuntimeError(error)
                    level = r['level'] = read_level(mem)
                    self.log.info('带练完成: %s 级', level)
                else:
                    self.well.gone(self.key)
                if world.map_id == VILLAGE_MAP:
                    self._step('在小美卖杂物')
                    sold = VillagePrep(session, char_id, self.store_s, self.log, rule=junk_slots).run()
                    r.update(free=sold['free'], sold=sold['sold'])
                    self._ride(session, mem, game, client, char_id, level)
                elif world.map_id != COAST_MAP:
                    raise RuntimeError(f'角色在地图 {world.map_id}，既不是逍遥村西区也不是平静海岸2区，不处理')
                else:
                    self.ferry.gone(self.key)
                    self.log.info('已在平静海岸2区（上次传送过来了），直接走去收货点')
                self._step('走到收货点')
                r.update(self._park(session, mem, game, char_id))
            finally:
                game.close()

    def _ride(self, session, mem, game, client, char_id, level):
        """Board the dispatcher's ferry; a role it could not take (e.g. gold not arrived) boards the next trip."""
        for attempt in range(1, self.ship.ferry_tries + 1):
            self._step('出生点等调度员' + (f'（第 {attempt} 次）' if attempt > 1 else ''))
            self._to_spawn(session, mem, game, char_id)
            self.log.info('%s 级，金币 %s，上船', level, read_gold(mem))
            self._step('调度员发金币 + PP鸡')
            error = self.ferry.board(self.key, Rider(client, self.account.name, self.slot, self.log))
            if not error:
                return
            w = read_world(mem)
            if w is None or w.map_id != VILLAGE_MAP or attempt == self.ship.ferry_tries:
                raise RuntimeError(error)
            self.log.warning('这趟没送成（%s），等下一趟', error)

    def _potato(self, mem, game):
        """Eat ONE 地瓜 (double exp for an hour) before the well, like the alts; stores.potato_at keeps it to one."""
        conn = db.connect(self.fs.db_path)
        try:
            row = db.store(conn, self.account.name, self.slot)
            if row is not None and row['potato_at'] is not None:
                self.log.info('地瓜已经吃过（%s），不再吃', time.strftime('%m-%d %H:%M', time.localtime(row['potato_at'])))
                return
            bag = self._loaded_bag(mem)
            slot = next((s for s in bag or () if s.item_id == POTATO_ITEM), None)
            if slot is None:
                self.log.info('背包里没有地瓜，不吃（背包 %d 格）', len(bag or ()))
                return
            db.mark_store_potato(conn, self.account.name, self.slot, time.time())   # before sending: never twice
        finally:
            conn.close()
        before = item_count(read_bag(mem) or (), POTATO_ITEM)
        try:
            game.use_item(slot.slot)
        except NotSent as e:
            self.log.warning('吃地瓜没发出去: %s', e)
            return
        end = time.monotonic() + EAT_WAIT
        while time.monotonic() < end:
            time.sleep(0.2)
            if item_count(read_bag(mem) or (), POTATO_ITEM) < before:
                self.log.info('吃地瓜 %d -> %d', before, before - 1)
                return
        self.log.warning('地瓜 %.0fs 内数量没变（%d），按已吃处理，不再吃', EAT_WAIT, before)

    def _loaded_bag(self, mem):
        """The bag once the client has loaded it (same non-empty reading twice), or the last reading after BAG_WAIT."""
        end, previous = time.monotonic() + BAG_WAIT, None
        while True:
            current = read_bag(mem)
            if bag_settled(previous, current) or time.monotonic() >= end:
                return current
            previous = current
            time.sleep(BAG_SETTLE)

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
            self.well.arrive(self.key)
            self.ferry.arrive(self.key)
            try:
                r = self._run()
            finally:
                self.well.gone(self.key)
                self.ferry.gone(self.key)
        conn = db.connect(self.fs.db_path)
        try:
            old = db.store(conn, self.account.name, self.slot)
            status = db.STORE_READY if r['ok'] else (old['status'] if old else db.STORE_VILLAGE_READY)
            db.save_store(conn, self.account.name, self.slot, self.expected, status, time.time(),
                          char_id=r.get('char_id'), free_slots=r.get('free'), map_id=r.get('map_id'), x=r.get('x'),
                          y=r.get('y'), gold=r.get('gold'), error=r.get('error'))
            db.log_event(conn, time.time(), 'store', f'{self.expected} {status} {r.get("level")} 级 地图 '
                         f'{r.get("map_id")} ({r.get("x")},{r.get("y")}) 金币 {r.get("gold")}'
                         f'{" " + r["error"] if r.get("error") else ""}', char_id=r.get('char_id'))
        finally:
            conn.close()
        return r


def junk_slots(bag, table):
    """After the well: everything the alt rule sells (factory/items.py), the drops included."""
    return items.sell_slots(bag, table)


def make_ferry_run(conn, station, client, lmem, riders, fs, ship):
    run = StoreTransport(conn, station, client, lmem, riders, fs, log.for_account('调度员'))
    run.gold_tries = ship.gold_tries
    return run


# ---- the leaders --------------------------------------------------------------------------------------------

def station_online(conn, logger, role, status):
    """Log the first enabled station of `role` in (or adopt its open window); mark it with `status`.
    -> (stations row, procs.Client) or raises."""
    enter_settings, stations = config.load_stations(ROOT / 'stations.toml')
    found = [s for s in stations if s.role == role]
    if not found:
        raise RuntimeError(f'stations.toml / local.toml 里没有启用的 {role} 工位')
    st = found[0]
    row = db.station(conn, st.station_id)
    if row and supervisor_busy(row['status'], row['heartbeat_at'], time.time()):
        raise RuntimeError(f'总大脑正在使用 {st.station_id}（状态 {row["status"]}，'
                           f'{time.time() - row["heartbeat_at"]:.0f}s 前）；先停总大脑再运行')
    c = next((c for c in procs.discover(logger) if st.name and c.name == st.name), None)
    if c is not None and not (row and row['char_id'] == c.char_id):
        db.register_station(conn, st.station_id, st.role, c.char_id, st.account.name, c.name, c.session.pid,
                            time.time())
        logger.info('%s %s 已在本工具窗口在线 pid=%d，登记', st.station_id, c.name, c.session.pid)
    if c is None:
        results = login_stations(conn, logger, enter_settings, [st])
        if not results or not results[0]['ok']:
            raise RuntimeError(f'{st.station_id} 登录失败: {results[0].get("error") if results else "?"}')
    row = db.station(conn, st.station_id)
    c = next((c for c in procs.discover(logger) if c.char_id == row['char_id']), None)
    if c is None:
        raise RuntimeError(f'{st.station_id} {row["name"]} 登记了但找不到它的窗口')
    with ProcessMemory(c.session.pid, c.session.base) as mem:
        logger.info('%s: %s pid=%d 地图 %d (%.0f,%.0f) %s 级 金币 %s', st.station_id, c.name, c.session.pid, c.map_id,
                    c.x, c.y, read_level(mem), read_gold(mem))
    db.heartbeat(conn, st.station_id, role, c.char_id, status, time.time())
    return row, c


def main():
    cfg_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'store.toml'
    log_path = log.setup(ROOT / 'logs', prefix='storeship')
    logger = log.for_account('main')
    logger.info('日志文件: %s', log_path)
    try:
        create = config.load(cfg_path)
        pipe = config.load_pipeline(cfg_path)
        data = config._read(cfg_path)
        ship, store_s = load_ship(data), load_store(data)
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
    conn.close()
    todo = ship_order(rows, names, ship.slots)
    ready = [r['name'] for r in rows if r['status'] == db.STORE_READY and r['account'] in names]
    logger.info('仓库账号 %s，槽 %s；数据库 %s；已就绪 %d 个，待处理 %d 个: %s', ', '.join(names), list(ship.slots),
                fs.db_path, len(ready), len(todo), ', '.join(t[2] for t in todo))
    if not todo:
        logger.info('没有村里已腾格（village_ready）的仓库号要送；先运行 一键建仓库号.cmd')
        return 0
    logger.info('启动前已有游戏进程（不会被关闭）: %s', game_pids())

    gold_fs = dataclasses.replace(fs, gold_amount=ship.gold, gold_topup_below=ship.gold)
    well = Ferry('古井队长', lambda c: station_online(c, logger, WELL, TRAIN_STATUS),
                 lambda c, st, cl, mem, riders: StoreTrain(c, st, cl, mem, riders, fs, ship, log.for_account('古井队长')),
                 fs.well_team_size, ship, ship.train_timeout, fs.db_path, log.for_account('古井队长'))
    ferry = Ferry('调度员', lambda c: station_online(c, logger, DISPATCHER, SHIP_STATUS),
                  lambda c, st, cl, mem, riders: make_ferry_run(c, st, cl, mem, riders, gold_fs, ship),
                  fs.transport_team_size, ship, ship.timeout, fs.db_path, log.for_account('调度员'))
    accounts = {a.name: a for a in create.accounts}
    throttle = LaunchThrottle(pipe.launch_interval, pipe.min_free_memory_mb)
    run_id = time.strftime('%Y%m%d_%H%M%S')
    started = time.monotonic()
    well.start()
    ferry.start()
    own = OwnWindows(pipe.max_windows, logger)
    locks = {a: threading.Lock() for a in accounts}
    try:
        with ThreadPoolExecutor(max_workers=pipe.max_windows, thread_name_prefix='ship') as pool:
            results = list(pool.map(lambda t: ShipRun(pipe, accounts[t[0]], t[1], t[2], throttle, own, locks[t[0]],
                                                      run_id, ship, fs, store_s, well, ferry).run(), todo))
    finally:
        well.close()
        ferry.close()
    seconds = time.monotonic() - started
    out = ROOT / 'logs' / f'{log_path.stem.replace("storeship_", "storeship_summary_")}.json'
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), 'utf-8')
    logger.info('=' * 60)
    for r in results:
        logger.info('%-10s %s %s级 地图=%s 坐标=(%s,%s) 金币=%s%s', r.get('role') or f"{r['account']}#{r['slot']}",
                    '就绪' if r['ok'] else '失败', r.get('level'), r.get('map_id'), r.get('x'), r.get('y'),
                    r.get('gold'), f" | {r['step']} {r['error']}" if r.get('error') else '')
    ok = sum(r['ok'] for r in results)
    logger.info('完成 %d/%d，带练 %d 趟，摆渡 %d 趟，总用时 %.0fs，本工具残留窗口 %d。汇总: %s', ok, len(results),
                well.trips, ferry.trips, seconds, own.count(), out)
    return 0 if ok == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
