"""料理仓库号 stage 2c: the receiver hands its 美味小强料理 27002 to the store roles, one bag slot (99) per trade.

Entry: python -m factory.storeuse [supervisor.toml]   (一键仓库号收料理.cmd; the supervisor runs the same StoreUnload)
Which store accounts to use: [receiver] stores = ["box07", "box08"] (local.toml), passwords from local.toml
[store_accounts]. Only stores rows with status ready (stage 2b, factory/storeship.py: logged out at receiver_post)
are used; an account of the list with no ready (or full) role at all refuses the start.
  1. trigger (supervisor): the receiver's bag has receiver_bag_warn empty slots or fewer (factory/receiver.py bag_room)
     -> the receiver stops taking alts (they wait in their queue) and unloads
  2. the next ready role of the list (account order, then slot) is logged in, or its open window adopted (an unload
     stopped halfway); it already stands at the post, farther than TRADE_RANGE it walks to the receiver
  3. one trade per 料理 stack, the biggest first, same request order as the gold trades (factory/gold.py): the
     RECEIVER invites (the leftover invite dialog lands on the store role, which logs out), the store role accepts,
     the receiver offers the stack 0x63 <IqIII>(0, 0, 1, slot, qty) and confirms, the store role offers nothing and
     confirms. Verified when the receiver has exactly qty less AND the store role qty more; CONFIRM_WAIT without
     a change -> trade again ([receiver] unload_tries, then the unload stops); a change that does not add up -> stop.
     A store role gets a stack only while it has an empty bag slot (never relies on stacking).
  4. the store role is full (no empty slot) or the receiver has no 料理 left -> it stands still, logs out (window
     closed); its stores row gets dishes + free_slots, status full when no empty slot is left
Every step starts from what the clients show (the db is only the record), so stopping anywhere and running again goes on.
Pure parts: load_unload, check_list, store_order, next_store, should_unload, biggest_stack, decide_give, rest_status,
stores_text (tests/test_factory_storeuse.py).
"""
import json
import math
import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

from provisioner import config, log, native, procs
from provisioner.enter import enter_role, verify_in_world
from provisioner.game import Game, NotSent
from provisioner.login import LaunchThrottle, login, read_session
from provisioner.memory import ProcessMemory
from provisioner.pipeline import OwnWindows, online_elsewhere, remember_roster
from provisioner.world import read_bag, read_bag_capacity, read_team, read_world

from . import db
from .config import ROOT, load_settings
from .gold import TRADE_RANGE, _idle
from .phase import COAST_MAP, DISH_ITEM, RECEIVER
from .receiver import DISH_STACK, PostRun, bag_room, dish_count
from .storeship import bag_settled

UNLOADING = 'unloading'         # receiver station status while it hands 料理 to a store role
BUSY_STATUS = {'receiving', 'bag_full', UNLOADING}   # fresh receiver heartbeat with one of these = supervisor running
BUSY_FRESH = 60.0
NAV_RETRY = 2.0
BAG_SETTLE = 0.5
BAG_WAIT = 5.0


@dataclass(frozen=True)
class UnloadSettings:
    accounts: tuple             # provisioner.config.Account of [receiver] stores, in list order
    max_stacks: int = 0         # stacks per unload; 0 = no limit (1 for the first live test)
    tries: int = 3              # trades of one stack without the 料理 moving, then the unload stops
    confirm_wait: float = 5.0
    timeout: float = 900.0      # one store role: login + walk + all its trades
    settle: float = 2.0         # stand still this long before logging out (server position catches up)
    relogin_gap: float = 10.0   # after a logout, before the next login (the next role is often the same account)
    retry_minutes: float = 10.0  # supervisor: after a failed unload, wait this long before the next one
    tick: float = 0.2


def load_unload(data, local):
    """[receiver] of the tool's config (local.toml laid over) + local.toml [store_accounts] -> UnloadSettings,
    or None when [receiver] stores is empty (stage 2c off)."""
    r = data.get('receiver', {})
    names = [str(x) for x in r.get('stores', [])]
    if not names:
        return None
    if len(set(names)) != len(names):
        raise ValueError(f'[receiver] stores 里有重复的账号: {names}')
    section = local.get('store_accounts')
    if not isinstance(section, dict):
        raise ValueError('[receiver] stores 要用仓库账号，但 local.toml 里没有 [store_accounts]（模板见 local.example.toml）')
    known = {a.name: a for a in config._accounts(section)}
    missing = [n for n in names if n not in known]
    if missing:
        raise ValueError(f'[receiver] stores 里的 {missing} 不在 local.toml [store_accounts] 的号段里')
    out = UnloadSettings(accounts=tuple(known[n] for n in names), max_stacks=int(r.get('unload_max_stacks', 0)),
                         tries=int(r.get('unload_tries', 3)), confirm_wait=float(r.get('unload_confirm_wait', 5)),
                         timeout=float(r.get('unload_timeout', 900)), settle=float(r.get('unload_settle', 2)),
                         relogin_gap=float(r.get('unload_relogin_gap', 10)),
                         retry_minutes=float(r.get('unload_retry_minutes', 10)))
    if out.max_stacks < 0 or out.tries < 1:
        raise ValueError('[receiver] unload_max_stacks 应 >= 0、unload_tries 应 >= 1')
    return out


def read_local(cfg_path):
    path = Path(cfg_path).with_name(config.LOCAL_NAME)
    return tomllib.loads(path.read_text('utf-8')) if path.is_file() else {}


# ---- pure decisions ---------------------------------------------------------------------------------------

def check_list(rows, accounts):
    """The [receiver] stores list against the stores rows. -> (errors, notes): an account with no ready or full role
    is an error (the start is refused); roles of a listed account that are not ready are notes (skipped)."""
    errors, notes = [], []
    for account in accounts:
        mine = [r for r in rows if r['account'] == account]
        usable = [r for r in mine if r['status'] in (db.STORE_READY, db.STORE_FULL)]
        if not usable:
            seen = '，'.join(f'{r["name"]} {r["status"]}' for r in mine) or '数据库里没有它的角色'
            errors.append(f'{account} 没有就绪的仓库角色（{seen}）；先运行 一键仓库号就位.cmd，或从 [receiver] stores 去掉')
            continue
        if all(r['status'] == db.STORE_FULL for r in usable) and len(usable) == len(mine):
            notes.append(f'{account} 的角色都已装满，可以从 [receiver] stores 去掉')
        for r in mine:
            if r['status'] not in (db.STORE_READY, db.STORE_FULL):
                notes.append(f'{r["name"]} 状态 {r["status"]}，不用')
    return errors, notes


def store_order(rows, accounts):
    """Rows of the listed accounts, list order then slot."""
    rank = {a: i for i, a in enumerate(accounts)}
    return sorted((r for r in rows if r['account'] in rank), key=lambda r: (rank[r['account']], r['slot']))


def next_store(rows, accounts, skip=frozenset()):
    """The first ready role of the list not in skip ((account, slot) pairs), or None."""
    return next((r for r in store_order(rows, accounts)
                 if r['status'] == db.STORE_READY and (r['account'], r['slot']) not in skip), None)


def should_unload(room, dishes, warn_slots):
    """Receiver: hand 料理 to a store role now? room: receiver.BagRoom | None; dishes: its 料理 count | None."""
    return room is not None and bool(dishes) and room.free_slots <= warn_slots


def biggest_stack(bag):
    """(bag slot, quantity) of the receiver's biggest 料理 stack, or None."""
    stacks = [(s.quantity, -s.slot) for s in bag or () if s.item_id == DISH_ITEM and s.quantity > 0]
    if not stacks:
        return None
    qty, neg = max(stacks)
    return -neg, qty


@dataclass(frozen=True)
class Decision:
    kind: str       # verified wait unconfirmed fail empty full navigate trade
    reason: str
    arg: object = None


@dataclass
class Memo:
    sent_at: float | None = None
    qty: int = 0
    store_before: int | None = None
    recv_before: int | None = None
    last_nav: float = -1e9


def decide_give(store, store_team, store_dishes, store_free, recv, recv_dishes, stack, memo, now, confirm_wait=5.0):
    """store / recv: WorldState | None; store_team: Team | None; *_dishes: int | None; store_free: empty bag slots of
    the store role | None; stack: the receiver's (bag slot, qty) | None."""
    if memo.sent_at is not None:
        if store_dishes is not None and recv_dishes is not None:
            if store_dishes == memo.store_before + memo.qty and recv_dishes == memo.recv_before - memo.qty:
                return Decision('verified', f'料理 收货人 {memo.recv_before} -> {recv_dishes}，'
                                            f'仓库号 {memo.store_before} -> {store_dishes}')
        if now - memo.sent_at < confirm_wait:
            return Decision('wait', '等料理到仓库号背包')
        if store_dishes == memo.store_before and recv_dishes == memo.recv_before:
            return Decision('unconfirmed', f'{confirm_wait:.0f}s 内料理没过去（收货人 {recv_dishes}，仓库号 {store_dishes}）')
        return Decision('fail', f'料理数对不上：收货人 {memo.recv_before} -> {recv_dishes}，仓库号 {memo.store_before} -> '
                                f'{store_dishes}，应各 -/+{memo.qty}；停下来请人工核对')
    if store is None or recv is None or store_team is None or store_dishes is None or recv_dishes is None \
            or store_free is None:
        return Decision('wait', '加载中')
    if recv_dishes == 0 or stack is None:
        return Decision('empty', '收货人身上没有料理了')
    if store_free <= 0:
        return Decision('full', f'仓库号背包没有空格了（料理 {store_dishes} 个）')
    if store.map_id != COAST_MAP or recv.map_id != COAST_MAP:
        return Decision('fail', f'不都在平静海岸2区（仓库号地图 {store.map_id}，收货人地图 {recv.map_id}）')
    if store_team.members:
        return Decision('fail', f'仓库号在队伍里（队长 {store_team.leader}）')
    distance = math.dist((store.x, store.y), (recv.x, recv.y))
    if distance > TRADE_RANGE:
        if store.nav_active or store.moving or store.in_battle or now - memo.last_nav < NAV_RETRY:
            return Decision('wait', f'仓库号走向收货人（距离 {distance:.0f}）')
        return Decision('navigate', f'离收货人 {distance:.0f}，仓库号走过去', (COAST_MAP, round(recv.x), round(recv.y)))
    if not _idle(store) or not _idle(recv):
        return Decision('wait', '仓库号或收货人忙/战斗/移动/验证中')
    return Decision('trade', f'交料理 ×{stack[1]}（收货人背包第 {stack[0]} 格；仓库号空 {store_free} 格）', stack)


def rest_status(free_slots):
    """stores status after an unload: full when no empty slot is left."""
    return db.STORE_FULL if free_slots is not None and free_slots <= 0 else db.STORE_READY


def stores_text(rows, accounts):
    """Status line part: the room left in the listed ready roles (free_slots as last recorded)."""
    ready = [r for r in store_order(rows, accounts) if r['status'] == db.STORE_READY]
    slots = sum(r['free_slots'] or 0 for r in ready)
    return f'仓库号 可用 {len(ready)} 个 空 {slots} 格（约 {slots * DISH_STACK} 个料理）'


def give_dish(recv_game, recv_id, store_game, store_id, slot, quantity, gap):
    """The six requests of one trade receiver -> store role, each from the side that owns it, `gap` seconds apart."""
    steps = ((recv_game.trade_invite, (store_id,)), (store_game.trade_accept, (recv_id,)),
             (recv_game.trade_offer_item, (slot, quantity)), (recv_game.trade_confirm, ()),
             (store_game.trade_offer_gold, (0,)), (store_game.trade_confirm, ()))
    for i, (step, args) in enumerate(steps):
        if i:
            time.sleep(gap)
        step(*args)


# ---- the unload -------------------------------------------------------------------------------------------

class StoreFailed(RuntimeError):
    """This store role cannot be used (wrong map, in a team): marked failed, the unload goes on with the next one."""


class StoreUnload:
    """Receiver -> store roles until the receiver has no 料理 or no listed role is left. The caller holds the
    receiver (supervisor: receiver_lock, alts not served meanwhile)."""

    def __init__(self, us, fs, login_settings, throttle, own, logger):
        self.us, self.fs, self.login_s, self.throttle, self.own, self.log = us, fs, login_settings, throttle, own, logger
        self.names = [a.name for a in us.accounts]
        self.by_name = {a.name: a for a in us.accounts}
        self.skip = set()           # (account, slot) that failed to log in this run

    def run(self, conn, recv, rmem, rgame, stop=None):
        """-> {'ok', 'moved', 'stores': [...], 'error'?}. ok = the receiver has no 料理 left, or max_stacks moved."""
        out = {'ok': False, 'moved': 0, 'stores': []}
        db.heartbeat(conn, self._sid(conn), RECEIVER, recv.char_id, UNLOADING, time.time())
        left = self.us.max_stacks or None
        while True:
            if stop is not None and stop.is_set():
                out['error'] = '已停止'
                return out
            if not dish_count(read_bag(rmem)):
                out['ok'] = True
                return out
            if left is not None and left <= 0:
                self.log.info('本次最多交 %d 格（[receiver] unload_max_stacks），到数了', self.us.max_stacks)
                out['ok'] = True
                return out
            row = next_store(db.stores(conn), self.names, self.skip)
            if row is None:
                out['error'] = '名单里没有还能装的仓库号了；在 local.toml [receiver] stores 里加账号'
                self.log.error('%s', out['error'])
                return out
            r = self.one(conn, row, recv, rmem, rgame, left, stop)
            out['stores'].append(r)
            out['moved'] += r.get('moved', 0)
            if left is not None:
                left -= r.get('stacks', 0)
            if r.get('stop'):
                out['error'] = r['error']
                return out

    def _sid(self, conn):
        row = conn.execute('SELECT station_id FROM stations WHERE role=? ORDER BY station_id', (RECEIVER,)).fetchone()
        return row['station_id'] if row else 'receiver'

    def one(self, conn, row, recv, rmem, rgame, left, stop):
        """One store role: in, trades, out. -> dict(name, moved, stacks, dishes, free, status, error?, stop?)."""
        name, account = row['name'], self.by_name[row['account']]
        lg = log.for_account(name)
        r = {'name': name, 'moved': 0, 'stacks': 0}
        session = None
        try:
            session, client = self.enter(account, name, lg)
        except Exception as e:      # noqa: BLE001 - this role is skipped for this run, the next one is tried
            self.skip.add((row['account'], row['slot']))
            r['error'] = f'登录/进入失败: {e}'
            lg.error('%s；本次跳过它', r['error'], exc_info=not isinstance(e, RuntimeError))
            db.save_store(conn, row['account'], row['slot'], name, row['status'], time.time(), error=r['error'])
            return r
        status, error = row['status'], None
        try:
            with ProcessMemory(session.pid, session.base) as mem:
                game = Game(session, mem)
                try:
                    self.trades(conn, client, mem, game, recv, rmem, rgame, r, left, stop, lg)
                    self.stand_still(mem)
                finally:
                    game.close()
                    seen = self.read_store(mem)
                    if seen:
                        r.update(seen)
                status = rest_status(r.get('free'))
        except StoreFailed as e:
            status, error = db.STORE_FAILED, str(e)
            lg.error('这个仓库号不能用: %s（标记 failed，换下一个）', e)
        except Exception as e:      # noqa: BLE001 - trade not adding up / no movement: stop the whole unload
            error = f'{type(e).__name__}: {e}'
            r['stop'] = True
            lg.error('交料理出错，停止这次卸货: %s', e, exc_info=not isinstance(e, RuntimeError))
        finally:
            self.own.close(session, lg)
            time.sleep(self.us.relogin_gap)
        r['status'], r['error'] = status, error
        db.save_store(conn, row['account'], row['slot'], name, status, time.time(), char_id=client.char_id,
                      free_slots=r.get('free'), capacity=r.get('capacity'), map_id=r.get('map_id'), x=r.get('x'),
                      y=r.get('y'), dishes=r.get('dishes'), error=error)
        db.log_event(conn, time.time(), 'store_unload', f'{name} 收 {r["moved"]} 个（{r["stacks"]} 格），存量 '
                     f'{r.get("dishes")} 空 {r.get("free")} 格 {status}{" " + error if error else ""}',
                     char_id=client.char_id)
        lg.info('下线：本次收 %d 个（%d 格），存量 %s 个，空 %s 格，状态 %s', r['moved'], r['stacks'], r.get('dishes'),
                r.get('free'), status)
        return r

    def enter(self, account, name, lg):
        """The store role's open window (adopted), or log it in. -> (session, procs.Client)."""
        c = next((c for c in procs.discover(lg) if c.name == name), None)
        if c is not None:
            self.own.add(c.session)
            lg.info('接管已开的窗口 pid=%d 地图 %d (%.0f,%.0f)', c.session.pid, c.map_id, c.x, c.y)
            return c.session, c
        elsewhere = online_elsewhere(account.name, self.own)
        if elsewhere:
            raise RuntimeError(f'该账号的角色正在其他窗口在线（{elsewhere}），为避免挤号，跳过')
        session = login(self.login_s, account, ROOT / 'runtime', self.throttle, lg, kill_on_failure=True)
        self.own.add(session)
        try:
            _, roster = read_session(session, account.name, lg)
            remember_roster(account.name, roster)
            index = next((i for i, (_, _, n) in enumerate(roster) if n == name), None)
            if index is None:
                raise RuntimeError(f'选角列表里没有 {name}（有 {[n for _, _, n in roster]}）')
            char_id = roster[index][0]
            enter_role(session, index + 1, self.login_s.enter_timeout, lg)
            world = verify_in_world(session, char_id, name, lg)
        except Exception:
            self.own.close(session, lg)
            raise
        lg.info('已上线 地图 %d (%.0f,%.0f)', world.map_id, world.x, world.y)
        return session, procs.Client(session, char_id, name, world.map_id, world.x, world.y)

    def loaded_bag(self, mem):
        """Right after entering the bag reads empty (stage 2b): the same non-empty reading twice, or the last one."""
        end, previous = time.monotonic() + BAG_WAIT, None
        while True:
            current = read_bag(mem)
            if bag_settled(previous, current) or time.monotonic() >= end:
                return current
            previous = current
            time.sleep(BAG_SETTLE)

    def read_store(self, mem):
        bag, cap, w = read_bag(mem), read_bag_capacity(mem), read_world(mem)
        room = bag_room(bag, cap)
        if room is None:
            return {}
        out = {'free': room.free_slots, 'capacity': room.capacity, 'dishes': dish_count(bag)}
        if w is not None:
            out.update(map_id=w.map_id, x=round(w.x), y=round(w.y))
        return out

    def trades(self, conn, client, mem, game, recv, rmem, rgame, r, left, stop, lg):
        cid, started = client.char_id, time.monotonic()
        self.loaded_bag(mem)
        memo, last, tries = Memo(), None, 0
        while True:
            now = time.monotonic()
            if now - started > self.us.timeout:
                raise RuntimeError(f'{self.us.timeout:.0f}s 内没交完')
            if stop is not None and stop.is_set() and memo.sent_at is None:
                return
            for pid in (client.session.pid, recv.session.pid):
                if not native.alive(pid):
                    raise RuntimeError(f'游戏进程 {pid} 已退出')
            sw, rw = read_world(mem), read_world(rmem)
            if sw and sw.char_id != cid:
                raise RuntimeError(f'角色变了 {cid} -> {sw.char_id}')
            bag, rbag = read_bag(mem), read_bag(rmem)
            room = bag_room(bag, read_bag_capacity(mem))
            d = decide_give(sw, read_team(mem), dish_count(bag), room.free_slots if room else None, rw,
                            dish_count(rbag), biggest_stack(rbag), memo, now, self.us.confirm_wait)
            if d.reason != last:
                lg.info('%s', d.reason)
            last = d.reason
            if d.kind == 'verified':
                r['moved'] += memo.qty
                r['stacks'] += 1
                db.log_event(conn, time.time(), 'store_dish', d.reason, char_id=cid)
                memo, tries = Memo(), 0
                time.sleep(0.3)         # quiet time after a finished trade (user rule: >= 0.2 s)
                if left is not None and r['stacks'] >= left:
                    return
                continue
            if d.kind in ('empty', 'full'):
                return
            if d.kind == 'fail':
                if memo.sent_at is None:
                    raise StoreFailed(d.reason)
                raise RuntimeError(d.reason)
            if d.kind == 'unconfirmed':
                memo, tries = Memo(), tries + 1
                if tries >= self.us.tries:
                    raise RuntimeError(f'同一格交易 {tries} 次料理都没过去')
                time.sleep(1.0)         # let a half-open trade time out before inviting again
            elif d.kind == 'navigate':
                game.navigate(*d.arg)
                memo.last_nav = now
            elif d.kind == 'trade':
                slot, qty = d.arg
                memo = Memo(qty=qty, store_before=dish_count(bag), recv_before=dish_count(rbag))
                try:
                    give_dish(rgame, recv.char_id, game, cid, slot, qty, self.fs.trade_step_gap)
                except NotSent as e:
                    raise RuntimeError(f'交易请求没发出: {e}') from e
                memo.sent_at = time.monotonic()
            time.sleep(self.us.tick)

    def stand_still(self, mem):
        end = time.monotonic() + 10.0
        while time.monotonic() < end:
            w = read_world(mem)
            if w is not None and not w.moving and not w.nav_active and w.still_for >= self.us.settle:
                return
            time.sleep(self.us.tick)


def validate(conn, us, logger):
    """Startup check of the list. -> True when it may run (errors logged)."""
    rows, names = db.stores(conn), [a.name for a in us.accounts]
    errors, notes = check_list(rows, names)
    for n in notes:
        logger.info('仓库号: %s', n)
    for e in errors:
        logger.error('仓库号: %s', e)
    if not errors:
        order = [f'{r["name"]}({r["status"]}，空 {r["free_slots"]} 格)' for r in store_order(rows, names)
                 if r['status'] in (db.STORE_READY, db.STORE_FULL)]
        logger.info('仓库号名单（按顺序用）: %s；%s', ', '.join(order), stores_text(rows, names))
    return not errors


def receiver_busy(row, now):
    return row is not None and row['status'] in BUSY_STATUS and now - (row['heartbeat_at'] or 0) < BUSY_FRESH


def main():
    cfg = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'supervisor.toml'
    log_path = log.setup(ROOT / 'logs', prefix='storeuse')
    logger = log.for_account('main')
    logger.info('日志文件: %s', log_path)
    try:
        data = config._read(cfg)
        local = read_local(cfg)
        us = load_unload(data, local)
        # this tool logs in store roles only: no alt range needed
        login_s = config.pipeline_from({**data, 'accounts': local.get('store_accounts') or data.get('accounts')})
        fs = load_settings(ROOT / data.get('supervisor', {}).get('factory', 'factory.toml'))
    except Exception as e:
        logger.error('配置错误 (%s): %s', cfg, e)
        return 2
    if us is None:
        logger.error('local.toml 里 [receiver] stores 是空的：写上要用的仓库账号，例如 stores = ["box07"]')
        return 2
    conn = db.connect(fs.db_path)
    if not validate(conn, us, logger):
        return 2
    stations = conn.execute('SELECT * FROM stations WHERE role=?', (RECEIVER,)).fetchall()
    if len(stations) != 1:
        logger.error('数据库里的收货人应正好 1 个，实际 %d 个；先运行 一键登录工位.cmd', len(stations))
        return 2
    st = stations[0]
    if receiver_busy(st, time.time()):
        logger.error('总大脑正在使用收货人（状态 %s，%.0fs 前）；先停总大脑，1 分钟后再运行', st['status'],
                     time.time() - st['heartbeat_at'])
        return 2
    recv = next((c for c in procs.discover(logger) if c.char_id == st['char_id']), None)
    if recv is None:
        logger.error('收货人 %s (ID=%d) 不在本工具的窗口里在线；先运行 一键登录工位.cmd', st['name'], st['char_id'])
        return 2
    logger.info('收货人: %s pid=%d 地图 %d (%.0f,%.0f)', recv.name, recv.session.pid, recv.map_id, recv.x, recv.y)
    own = OwnWindows(2, logger)
    unload = StoreUnload(us, fs, login_s, LaunchThrottle(login_s.launch_interval, login_s.min_free_memory_mb), own,
                         logger)
    with ProcessMemory(recv.session.pid, recv.session.base) as rmem:
        post = PostRun(conn, st, recv, rmem, fs, log.for_account(recv.name))
        try:
            post.run()
        except Exception as e:
            logger.error('收货人没能回到收货点: %s', e, exc_info=not isinstance(e, RuntimeError))
            return 1
        finally:
            post.close()
        before = dish_count(read_bag(rmem))
        logger.info('收货人背包料理 %s 个；本次最多交 %s 格', before, us.max_stacks or '不限')
        rgame = Game(recv.session, rmem)
        try:
            result = unload.run(conn, recv, rmem, rgame)
        finally:
            rgame.close()
        after = dish_count(read_bag(rmem))
    db.heartbeat(conn, st['station_id'], RECEIVER, recv.char_id, 'idle', time.time())
    out = ROOT / 'logs' / (log_path.stem.replace('storeuse_', 'storeuse_summary_') + '.json')
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
    logger.info('=' * 60)
    for r in result['stores']:
        logger.info('%-10s 收 %d 个（%d 格）存量 %s 空 %s 格 %s %s', r['name'], r['moved'], r['stacks'], r.get('dishes'),
                    r.get('free'), r.get('status'), r.get('error') or '')
    logger.info('%s：收货人料理 %s -> %s，交出 %d 个；%s。汇总: %s', '完成' if result['ok'] else '没做完', before, after,
                result['moved'], stores_text(db.stores(conn), [a.name for a in us.accounts]), out)
    conn.close()
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
