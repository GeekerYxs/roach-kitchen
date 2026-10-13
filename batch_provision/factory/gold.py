"""Stage 3: the dispatcher gives gold to every alt in 逍遥村西区 that has less than two teleport fees.

Entry: python -m factory.gold [factory.toml]
The dispatcher is the station registered with role 'dispatcher' (一键登录工位.cmd). Trades run one at a
time (a single dispatcher; the user's rule: trades strictly serial, >= 0.2 s apart).

Lenient by design (user, 2026-10-12): gold is worthless. No balance reconciliation; success = the alt now
has >= the top-up floor (380 = two teleports). Unknown result -> re-read; still short after the wait -> trade again (3 tries, then
quarantine). The DISPATCHER always invites, so the leftover invite dialog lands on the disposable alt.

decide() is pure (tests/test_factory_gold.py).
"""
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from provisioner import log, native, procs
from provisioner.game import Game, NotSent
from provisioner.memory import ProcessMemory
from provisioner.world import read_gold, read_world

from . import db
from .config import ROOT, load_settings
from .phase import DISPATCHER, GOLD_GIFT, GOLD_TOPUP_BELOW, VILLAGE_MAP
from .runner import ROLE_NAME

TRADE_RANGE = 200       # px between dispatcher and alt (old successful trades: ~80 px)
CONFIRM_WAIT = 5.0      # after the last step, the alt's gold must reach the fee within this long
SETTLE_GAP = 0.3        # quiet time after each finished trade (user rule: >= 0.2 s)


@dataclass(frozen=True)
class Decision:
    kind: str      # 'done' | 'verified' | 'fail' | 'wait' | 'trade' | 'unconfirmed'
    reason: str


@dataclass
class Memo:
    sent_at: float | None = None
    gold_before: int | None = None


def _idle(w):
    return not (w.in_battle or w.busy or w.nav_active or w.moving or w.verification)


def decide(alt, alt_gold, disp, disp_gold, memo, now, amount=GOLD_GIFT, floor=GOLD_TOPUP_BELOW):
    """alt / disp: WorldState or None. Gold values: int or None. Alts below `floor` get `amount`."""
    if memo.sent_at is not None:
        if alt_gold is not None and alt_gold >= floor:
            return Decision('verified', f'金币 {memo.gold_before} -> {alt_gold}')
        if now - memo.sent_at < CONFIRM_WAIT:
            return Decision('wait', '等金币到账')
        return Decision('unconfirmed', f'{CONFIRM_WAIT:.0f}s 内金币没到 {floor}（现在 {alt_gold}）')
    if alt is None or disp is None or alt_gold is None or disp_gold is None:
        return Decision('wait', '加载中')
    if alt_gold >= floor:
        return Decision('done', f'金币 {alt_gold} 已够两次传送')
    if alt.map_id != VILLAGE_MAP or disp.map_id != VILLAGE_MAP:
        return Decision('fail', f'不都在逍遥村西区（小号地图 {alt.map_id}，调度员地图 {disp.map_id}）')
    distance = math.dist((alt.x, alt.y), (disp.x, disp.y))
    if distance > TRADE_RANGE:
        return Decision('fail', f'离调度员太远 ({distance:.0f} > {TRADE_RANGE})')
    if disp_gold < amount:
        return Decision('fail', f'调度员金币不足 ({disp_gold} < {amount})')
    if not _idle(alt) or not _idle(disp):
        return Decision('wait', '小号或调度员忙/战斗/移动/验证中')
    return Decision('trade', f'给 {amount} 金币（现有 {alt_gold}，距离 {distance:.0f}）')


def trade_gold(disp_game, disp_id, alt_game, alt_id, amount, gap):
    """The six requests of one gold trade, each from the side that owns it, `gap` seconds apart."""
    steps = ((disp_game.trade_invite, (alt_id,)), (alt_game.trade_accept, (disp_id,)),
             (disp_game.trade_offer_gold, (amount,)), (disp_game.trade_confirm, ()),
             (alt_game.trade_offer_gold, (0,)), (alt_game.trade_confirm, ()))
    for i, (step, args) in enumerate(steps):
        if i:
            time.sleep(gap)
        step(*args)


class GoldJob:
    def __init__(self, conn, disp, disp_mem, disp_game, alt, account, slot, settings, log_):
        self.conn, self.disp, self.disp_mem, self.disp_game = conn, disp, disp_mem, disp_game
        self.alt, self.account, self.slot, self.s, self.log = alt, account, slot, settings, log_

    def run(self):
        started = time.monotonic()
        cid = self.alt.char_id
        result = {'name': self.alt.name, 'pid': self.alt.session.pid, 'char_id': cid, 'ok': False}
        db.register_alt(self.conn, cid, self.account, self.slot, self.alt.name, time.time())
        memo, last_reason = Memo(), None
        try:
            with ProcessMemory(self.alt.session.pid, self.alt.session.base) as mem:
                game = Game(self.alt.session, mem)
                try:
                    while True:
                        now = time.monotonic()
                        if now - started > self.s.gold_timeout:
                            raise RuntimeError(f'{self.s.gold_timeout:.0f}s 内没有完成')
                        for pid in (self.alt.session.pid, self.disp.session.pid):
                            if not native.alive(pid):
                                raise RuntimeError(f'游戏进程 {pid} 已退出')
                        alt_w, disp_w = read_world(mem), read_world(self.disp_mem)
                        if alt_w and alt_w.char_id != cid:
                            raise RuntimeError(f'角色变了 {cid} -> {alt_w.char_id}')
                        if db.alt(self.conn, cid)['quarantined']:
                            raise RuntimeError('已隔离')
                        alt_gold, disp_gold = read_gold(mem), read_gold(self.disp_mem)
                        d = decide(alt_w, alt_gold, disp_w, disp_gold, memo, now, self.s.gold_amount,
                                   self.s.gold_topup_below)
                        if d.reason != last_reason:
                            self.log.info('%s', d.reason)
                        last_reason = d.reason
                        if d.kind == 'done':
                            result.update(ok=True, skipped=True, gold=alt_gold)
                            break
                        if d.kind == 'verified':
                            db.log_event(self.conn, time.time(), 'gold', d.reason, char_id=cid,
                                         station_id=self.disp.name)
                            result.update(ok=True, gold_before=memo.gold_before, gold=alt_gold,
                                          seconds_to_verify=round(now - memo.sent_at, 2))
                            time.sleep(SETTLE_GAP)
                            break
                        if d.kind == 'fail':
                            raise RuntimeError(d.reason)
                        if d.kind == 'unconfirmed':
                            memo = Memo()
                            if db.record_failure(self.conn, cid, d.reason, time.time()):
                                raise RuntimeError(f'连续失败 {db.MAX_RETRIES} 次，已隔离')
                            time.sleep(1.0)     # let a half-open trade time out before inviting again
                        elif d.kind == 'trade':
                            memo = Memo(gold_before=alt_gold)
                            try:
                                trade_gold(self.disp_game, self.disp.char_id, game, cid, self.s.gold_amount,
                                           self.s.trade_step_gap)
                            except NotSent as e:
                                raise RuntimeError(f'交易请求没发出: {e}') from e
                            memo.sent_at = time.monotonic()
                        time.sleep(self.s.tick)
                finally:
                    game.close()
        except Exception as e:
            result['error'] = f'{type(e).__name__}: {e}'
            self.log.error('失败: %s', e, exc_info=not isinstance(e, RuntimeError))
        result['seconds'] = round(time.monotonic() - started, 1)
        return result


def main():
    import json
    settings = load_settings(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'factory.toml')
    log_path = log.setup(ROOT / 'logs', prefix='gold')
    logger = log.for_account('main')
    logger.info('日志文件: %s', log_path)
    conn = db.connect(settings.db_path)
    stations = [r for r in conn.execute('SELECT * FROM stations WHERE role=?', (DISPATCHER,))]
    if len(stations) != 1:
        logger.error('数据库里的调度员应正好 1 个，实际 %d 个；先运行 一键登录工位.cmd', len(stations))
        return 2
    clients = {c.char_id: c for c in procs.discover(logger)}
    disp = clients.pop(stations[0]['char_id'], None)
    if disp is None:
        logger.error('调度员 %s (ID=%d) 不在本工具的窗口里在线；先运行 一键登录工位.cmd', stations[0]['name'],
                     stations[0]['char_id'])
        return 2
    logger.info('调度员: %s pid=%d 坐标=(%.0f,%.0f)', disp.name, disp.session.pid, disp.x, disp.y)
    alts = []
    for c in clients.values():
        m = ROLE_NAME.match(c.name)
        if m and c.map_id == VILLAGE_MAP:
            alts.append((c, m.group(1), int(m.group(2))))
        else:
            logger.info('%s 不是在逍遥村西区的小号，跳过', c.name)
    results = []
    with ProcessMemory(disp.session.pid, disp.session.base) as disp_mem:
        disp_game = Game(disp.session, disp_mem)
        try:
            for c, account, slot in sorted(alts, key=lambda t: t[0].name):   # strictly one trade at a time
                results.append(GoldJob(conn, disp, disp_mem, disp_game, c, account, slot, settings,
                                       log.for_account(c.name)).run())
        finally:
            disp_game.close()
    conn.close()
    out = ROOT / 'logs' / (log_path.stem.replace('gold_', 'gold_summary_') + '.json')
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), 'utf-8')
    logger.info('=' * 60)
    for r in results:
        logger.info('%-8s %s 金币=%s %s', r['name'], '完成' if r['ok'] else '失败', r.get('gold'),
                    r.get('error', '原本就够' if r.get('skipped') else ''))
    ok = sum(r['ok'] for r in results)
    logger.info('完成 %d/%d。汇总: %s', ok, len(results), out)
    return 0 if ok == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
