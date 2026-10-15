"""Stage 9: the receiver station collects one 美味小强料理 27002 from every alt that handed in quest 78.

Entry: python -m factory.receiver [factory.toml]
The receiver is the station registered with role 'receiver' (一键登录工位.cmd). Its post (user, 2026-10-12) is
where the alts already stand after the hand-in: map 81 next to 海子, factory.toml receiver_post (1780,1370).
  1. back to the post (reuses the coast leaders' return, factory/coast.py): map 81 -> walk; map 1 -> PP鸡 (190
     gold, the receiver has the permission) -> walk; other map -> 飞鞋 (its point is at the post) -> 回城卷 -> PP鸡
  2. standing at the post with a 飞鞋 point that is not there: record it there (once), so a restart from anywhere
     is one 飞鞋 away
  3. every alt on map 81 in phase queue_receiver, one at a time (user rule: trades strictly serial): claim it;
     farther than 200 from the receiver -> the alt walks over; then the six trade requests, the RECEIVER invites
     (the leftover invite dialog lands on the disposable alt), the ALT offers first (the order the dispatcher's
     gold trades verified: the giving side offers and confirms, then the other side offers nothing and confirms)
  4. verified when the alt has one 料理 less AND the receiver one more; 5 s without it -> re-read and trade again
     (3 tries, then quarantine).
  5. then all the alt's gold (user, 2026-10-15: ~1100-1700 after quest 78, collected before the delete) in a trade
     of its own, same order: the alt offers <IqI>(0, all its gold, 0) and confirms, the receiver offers nothing and
     confirms (live 2026-10-15, 2.98: 1753 gold arrived exactly, no fee, 3.2 s). Verified when the alt has 0 AND
     the receiver exactly that much more; 5 s without it -> re-read and trade again (3 tries, then quarantine).
     The alt is then phase delete (stage 10). phase.derive_phase keeps an alt with quest 78 done and gold left in
     queue_receiver, so a crash between the two trades comes back here, not to the delete.
decide() / decide_gold() are pure (tests/test_factory_receiver.py).

Item offer 0x63 <IqIII>(0, 0, 1, bag slot, quantity) comes from the old runtime's UI capture (Gemini mwxqll_game
reference_runtime/item_trade.py); the step order with the receiver inviting is new.
"""
import json
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from provisioner import log, native, procs
from provisioner.game import Game, NotSent
from provisioner.memory import ProcessMemory
from provisioner.world import read_bag, read_gold, read_team, read_world

from . import db
from .coast import CoastRun
from .config import ROOT, load_settings
from .gold import SETTLE_GAP, TRADE_RANGE, _idle
from .observe import observe
from .phase import COAST_MAP, DISH_ITEM, QUEUE_RECEIVER, RECEIVER, derive_phase
from .runner import ROLE_NAME

ACTION = 'receive_dish'
GOLD_ACTION = 'receive_gold'
POST_NEAR = 30                  # the 飞鞋 point counts as at the post this close (record exact after ~1 s still)
CONFIRM_WAIT = 5.0
NAV_RETRY = 2.0


@dataclass(frozen=True)
class Decision:
    kind: str      # done verified fail wait navigate trade unconfirmed
    reason: str
    arg: object = None


@dataclass
class Memo:
    sent_at: float | None = None
    alt_before: int | None = None       # 料理 or gold, whichever this trade moves
    recv_before: int | None = None
    last_nav: float = -1e9


def dish_slot(bag):
    """(bag slot, quantity) of the first 料理 stack, or None."""
    return next(((s.slot, s.quantity) for s in bag or () if s.item_id == DISH_ITEM), None)


def dish_count(bag):
    return None if bag is None else sum(s.quantity for s in bag if s.item_id == DISH_ITEM)


def decide(alt, alt_team, alt_dishes, slot, recv, recv_dishes, memo, now):
    """alt / recv: WorldState | None; alt_team: Team | None; *_dishes: int | None; slot: (bag slot, qty) | None."""
    if memo.sent_at is not None:
        if alt_dishes is not None and recv_dishes is not None and alt_dishes < memo.alt_before \
                and recv_dishes > memo.recv_before:
            return Decision('verified', f'料理 小号 {memo.alt_before} -> {alt_dishes}，'
                                        f'收货人 {memo.recv_before} -> {recv_dishes}')
        if now - memo.sent_at < CONFIRM_WAIT:
            return Decision('wait', '等料理到收货人背包')
        return Decision('unconfirmed', f'{CONFIRM_WAIT:.0f}s 内料理没过去（小号 {alt_dishes}，收货人 {recv_dishes}）')
    if alt is None or recv is None or alt_team is None or alt_dishes is None or recv_dishes is None:
        return Decision('wait', '加载中')
    if alt_dishes == 0:
        return Decision('done', '背包里没有料理')
    return _ready(alt, alt_team, recv, memo, now) or Decision('trade', f'收料理 ×{slot[1]}（背包第 {slot[0]} 格）', slot)


def decide_gold(alt, alt_team, alt_gold, recv, recv_gold, memo, now):
    """Step 5, after the 料理: all the alt's gold. *_gold: int | None."""
    if memo.sent_at is not None:
        expect = memo.recv_before + memo.alt_before
        if alt_gold == 0 and recv_gold == expect:
            return Decision('verified', f'金币 小号 {memo.alt_before} -> 0，收货人 {memo.recv_before} -> {recv_gold}')
        if now - memo.sent_at < CONFIRM_WAIT:
            return Decision('wait', '等金币到收货人')
        if alt_gold == 0:       # gone from the alt but not the exact amount at the receiver: do not trade again
            return Decision('fail', f'小号金币已清零，但收货人 {memo.recv_before} -> {recv_gold}，'
                                    f'不等于 +{memo.alt_before}')
        return Decision('unconfirmed', f'{CONFIRM_WAIT:.0f}s 内金币没过去（小号 {alt_gold}，收货人 {recv_gold}）')
    if alt is None or recv is None or alt_team is None or alt_gold is None or recv_gold is None:
        return Decision('wait', '加载中')
    if alt_gold == 0:
        return Decision('done', '身上没有金币')
    return _ready(alt, alt_team, recv, memo, now) or Decision('trade', f'收金币 {alt_gold}', alt_gold)


def _ready(alt, alt_team, recv, memo, now):
    """None when both stand idle next to each other on map 81; otherwise what to do first."""
    if alt.map_id != COAST_MAP or recv.map_id != COAST_MAP:
        return Decision('fail', f'不都在平静海岸2区（小号地图 {alt.map_id}，收货人地图 {recv.map_id}）')
    if alt_team.members:
        return Decision('fail', f'小号在队伍里（队长 {alt_team.leader}）')
    distance = math.dist((alt.x, alt.y), (recv.x, recv.y))
    if distance > TRADE_RANGE:
        if alt.nav_active or alt.moving or alt.in_battle or now - memo.last_nav < NAV_RETRY:
            return Decision('wait', f'小号走向收货人（距离 {distance:.0f}）')
        return Decision('navigate', f'离收货人 {distance:.0f}，小号走过去', (COAST_MAP, round(recv.x), round(recv.y)))
    if not _idle(alt) or not _idle(recv):
        return Decision('wait', '小号或收货人忙/战斗/移动/验证中')
    return None


def trade_dish(recv_game, recv_id, alt_game, alt_id, slot, quantity, gap):
    _trade(recv_game, recv_id, alt_game, alt_id, (alt_game.trade_offer_item, (slot, quantity)), gap)


def trade_all_gold(recv_game, recv_id, alt_game, alt_id, amount, gap):
    _trade(recv_game, recv_id, alt_game, alt_id, (alt_game.trade_offer_gold, (amount,)), gap)


def _trade(recv_game, recv_id, alt_game, alt_id, alt_offer, gap):
    """The six requests of one trade alt -> receiver, each from the side that owns it, `gap` seconds apart."""
    steps = ((recv_game.trade_invite, (alt_id,)), (alt_game.trade_accept, (recv_id,)),
             alt_offer, (alt_game.trade_confirm, ()),
             (recv_game.trade_offer_gold, (0,)), (recv_game.trade_confirm, ()))
    for i, (step, args) in enumerate(steps):
        if i:
            time.sleep(gap)
        step(*args)


# ---- 1 + 2: the receiver at its post ---------------------------------------------------------------------------

class PostRun(CoastRun):
    """The coast leaders' way back to map 81 + 飞鞋 record, for a station without a team."""

    def __init__(self, conn, station, client, mem, settings, logger):
        super().__init__(conn, station, client, mem, {}, settings, logger)
        self.shoe_point = (settings.receiver_post, POST_NEAR)

    def check(self):
        if time.monotonic() - self.started > self.s.receive_post_timeout:
            raise RuntimeError(f'{self.s.receive_post_timeout:.0f}s 内没回到收货点')
        if not native.alive(self.leader.session.pid):
            raise RuntimeError(f'收货人游戏进程 {self.leader.session.pid} 已退出')
        w = read_world(self.lmem)
        if w and w.char_id != self.leader.char_id:
            raise RuntimeError('收货人角色变了')
        return w

    def periodic(self, now, status):
        if now - self.last_observe >= 10.0:
            self.last_observe = now
            db.heartbeat(self.conn, self.sid(), RECEIVER, self.leader.char_id, status, time.time())

    def run(self):
        self.to_coast()
        w = self.goto(self.s.receiver_post, '去收货点', 'to_post')
        self.record_shoe()
        db.heartbeat(self.conn, self.sid(), RECEIVER, self.leader.char_id, 'receiving', time.time())
        return w


# ---- 3 + 4: one alt --------------------------------------------------------------------------------------------

class ReceiveJob:
    def __init__(self, conn, station_id, recv, recv_mem, recv_game, alt, settings, log_):
        self.conn, self.sid, self.recv, self.rmem, self.rgame = conn, station_id, recv, recv_mem, recv_game
        self.alt, self.s, self.log = alt, settings, log_

    def run(self):
        started = time.monotonic()
        cid = self.alt.char_id
        result = {'name': self.alt.name, 'char_id': cid, 'ok': False}
        memo, last_reason, gold_step = Memo(), None, False     # 料理 first, then the gold
        try:
            with ProcessMemory(self.alt.session.pid, self.alt.session.base) as mem:
                game = Game(self.alt.session, mem)
                try:
                    while True:
                        now = time.monotonic()
                        if now - started > self.s.receive_timeout:
                            raise RuntimeError(f'{self.s.receive_timeout:.0f}s 内没有完成')
                        for pid in (self.alt.session.pid, self.recv.session.pid):
                            if not native.alive(pid):
                                raise RuntimeError(f'游戏进程 {pid} 已退出')
                        alt_w, recv_w = read_world(mem), read_world(self.rmem)
                        if alt_w and alt_w.char_id != cid:
                            raise RuntimeError(f'角色变了 {cid} -> {alt_w.char_id}')
                        row = db.alt(self.conn, cid)
                        if row['quarantined']:
                            raise RuntimeError(f'已隔离: {row["last_error"]}')
                        if not gold_step:
                            bag, rbag = read_bag(mem), read_bag(self.rmem)
                            alt_has, recv_has = dish_count(bag), dish_count(rbag)
                            d = decide(alt_w, read_team(mem), alt_has, dish_slot(bag), recv_w, recv_has, memo, now)
                        else:
                            alt_has, recv_has = read_gold(mem), read_gold(self.rmem)
                            d = decide_gold(alt_w, read_team(mem), alt_has, recv_w, recv_has, memo, now)
                        if d.reason != last_reason:
                            self.log.info('%s', d.reason)
                        last_reason = d.reason
                        action, key = (GOLD_ACTION, 'gold') if gold_step else (ACTION, 'dish')
                        if d.kind in ('done', 'verified'):
                            if d.kind == 'verified':
                                db.complete_action(self.conn, cid, time.time())
                                db.log_event(self.conn, time.time(), 'receive_gold' if gold_step else 'receive',
                                             d.reason, char_id=cid, station_id=self.sid)
                                result[key] = {'moved': memo.alt_before, 'receiver': recv_has,
                                               'seconds_to_verify': round(now - memo.sent_at, 2)}
                                time.sleep(SETTLE_GAP)
                            else:
                                if row['pending_action'] == action:
                                    db.complete_action(self.conn, cid, time.time())
                                result[key] = {'skipped': True, 'receiver': recv_has}
                            if gold_step:
                                result['ok'] = True
                                break
                            gold_step, memo = True, Memo()
                            continue
                        if d.kind == 'fail':
                            raise RuntimeError(d.reason)
                        if d.kind == 'unconfirmed':
                            memo = Memo()
                            if db.record_failure(self.conn, cid, d.reason, time.time()):
                                raise RuntimeError(f'连续失败 {db.MAX_RETRIES} 次，已隔离')
                            time.sleep(1.0)     # let a half-open trade time out before inviting again
                        elif d.kind == 'navigate':
                            game.navigate(*d.arg)
                            memo.last_nav = now
                        elif d.kind == 'trade':
                            memo = Memo(alt_before=alt_has, recv_before=recv_has)
                            db.mark_pending(self.conn, cid, action, time.time())
                            trade = trade_all_gold if gold_step else trade_dish
                            args = (d.arg,) if gold_step else d.arg
                            try:
                                trade(self.rgame, self.recv.char_id, game, cid, *args, self.s.trade_step_gap)
                            except NotSent as e:
                                raise RuntimeError(f'交易请求没发出: {e}') from e
                            memo.sent_at = time.monotonic()
                        time.sleep(self.s.tick)
                    self._save_phase(mem, result)
                finally:
                    game.close()
        except Exception as e:
            result['error'] = f'{type(e).__name__}: {e}'
            self.log.error('失败: %s', e, exc_info=not isinstance(e, RuntimeError))
        result['seconds'] = round(time.monotonic() - started, 1)
        return result

    def _save_phase(self, mem, result):
        obs = observe(mem, read_world(mem))
        if obs is None:
            return
        plan = derive_phase(obs, db.ledger(self.conn, self.alt.char_id), db.station_roles(self.conn))
        db.save_observation(self.conn, obs, plan, time.time())
        result['phase_after'] = plan.phase
        self.log.info('料理 %d 个 金币 %s 阶段=%s（%s）', obs.dishes, obs.gold, plan.phase, plan.reason)


def refresh(conn, alts, logger):
    """Save every coast alt's current phase so db.waiting() sees who holds a 料理."""
    roles, now = db.station_roles(conn), time.time()
    for c, account, slot in alts:
        db.register_alt(conn, c.char_id, account, slot, c.name, now)
        with ProcessMemory(c.session.pid, c.session.base) as mem:
            obs = observe(mem, read_world(mem))
        if obs is None:
            logger.warning('%s 读不到状态，跳过', c.name)
            continue
        db.save_observation(conn, obs, derive_phase(obs, db.ledger(conn, c.char_id), roles), now)


def main():
    settings = load_settings(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'factory.toml')
    log_path = log.setup(ROOT / 'logs', prefix='receive')
    logger = log.for_account('main')
    logger.info('日志文件: %s', log_path)
    conn = db.connect(settings.db_path)
    stations = conn.execute('SELECT * FROM stations WHERE role=?', (RECEIVER,)).fetchall()
    if len(stations) != 1:
        logger.error('数据库里的收货人应正好 1 个，实际 %d 个；先运行 一键登录工位.cmd', len(stations))
        return 2
    st = stations[0]
    clients = {c.char_id: c for c in procs.discover(logger)}
    recv = clients.pop(st['char_id'], None)
    if recv is None:
        logger.error('收货人 %s (ID=%d) 不在本工具的窗口里在线；先运行 一键登录工位.cmd', st['name'], st['char_id'])
        return 2
    logger.info('收货人: %s pid=%d 地图 %d 坐标=(%.0f,%.0f)，收货点 %s', recv.name, recv.session.pid, recv.map_id,
                recv.x, recv.y, settings.receiver_post)
    station_ids = set(db.station_roles(conn))
    alts = []
    for c in clients.values():
        m = ROLE_NAME.match(c.name)
        if m and c.map_id == COAST_MAP and c.char_id not in station_ids:
            alts.append((c, m.group(1), int(m.group(2))))
    by_id = {c.char_id: (c, a, s) for c, a, s in alts}
    results = []
    with ProcessMemory(recv.session.pid, recv.session.base) as rmem:
        post = PostRun(conn, st, recv, rmem, settings, log.for_account(recv.name))
        try:
            post.run()
        except Exception as e:
            logger.error('收货人没能回到收货点: %s', e, exc_info=not isinstance(e, RuntimeError))
            return 1
        finally:
            post.close()
        logger.info('收货人背包料理 %s 个', dish_count(read_bag(rmem)))
        refresh(conn, alts, logger)
        queue = [r['char_id'] for r in db.waiting(conn, QUEUE_RECEIVER, time.time()) if r['char_id'] in by_id]
        logger.info('排收货队列的小号 %d 个: %s', len(queue), ', '.join(by_id[c][0].name for c in queue))
        rgame = Game(recv.session, rmem)
        try:
            for cid in queue:                           # strictly one trade at a time
                if not db.claim(conn, st['station_id'], [cid], settings.receive_lease, time.time()):
                    logger.warning('%s 被别的工位占着或已隔离，跳过', by_id[cid][0].name)
                    continue
                try:
                    results.append(ReceiveJob(conn, st['station_id'], recv, rmem, rgame, by_id[cid][0], settings,
                                              log.for_account(by_id[cid][0].name)).run())
                finally:
                    db.release(conn, st['station_id'], [cid], time.time())
        finally:
            rgame.close()
        total, gold = dish_count(read_bag(rmem)), read_gold(rmem)
    db.heartbeat(conn, st['station_id'], RECEIVER, recv.char_id, 'idle', time.time())
    conn.close()
    out = ROOT / 'logs' / (log_path.stem.replace('receive_', 'receive_summary_') + '.json')
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), 'utf-8')
    logger.info('=' * 60)
    for r in results:
        logger.info('%-8s %s %s', r['name'], '完成' if r['ok'] else '失败',
                    r.get('error', f"金币 {r.get('gold', {}).get('moved') or 0}"))
    ok = sum(r['ok'] for r in results)
    logger.info('完成 %d/%d，收货人背包料理 %s 个、金币 %s。汇总: %s', ok, len(results), total, gold, out)
    return 0 if ok == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
