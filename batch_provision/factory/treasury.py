"""Treasury: the receiver (who collects every alt's gold before the delete) pays the stations that spend gold, so
the gold loop runs by itself (user-agreed 2026-10-20: the receiver is the treasury; when the receiver character is
swapped, its gold moves to the new one).

Spending per alt (10-16 logs): the dispatcher gives ~490 (the 500 gift); each alt pays 190 to PP鸡 out of it and
earns 1153 from quest 78, so every alt leaves ~1000 more gold in the system than it took - it only piles up at the
receiver. Here a station below its [treasury.<role>] low mark goes to the receiver and gets topped up to target:
  coast leaders end every batch at the rendezvous next to the receiver post; the dispatcher and the well leaders
  take the supply trip to map 81 (factory/supply.py: PP鸡 -> receiver -> 花袭人 -> 回城卷 home).
The trade is driven by the station's thread with the receiver's window, under the lock the receiver's own alt trades
also hold, so trades stay strictly serial. Order as the alt -> receiver gold trades (live 2026-10-15) with the roles
swapped: the receiver invites, the station accepts, the GIVER (receiver) offers and confirms, the station offers 0
and confirms. Verified when the station has the amount more and the receiver the amount less (a quiz popup may add
100 to either side meanwhile); 5 s without it -> re-read and trade again, 3 tries.
Decisions are pure (tests/test_factory_treasury.py).
"""
import math
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from provisioner.game import Game, NotSent
from provisioner.memory import ProcessMemory
from provisioner.world import read_gold, read_world

from .gold import TRADE_RANGE, _idle
from .phase import COAST_MAP

CONFIRM_WAIT = 5.0
TRIES = 3
QUIZ_SLACK = 200            # a quiz popup pays 100: tolerate a little extra on either side while verifying


@dataclass(frozen=True)
class TreasurySettings:
    enabled: bool = True
    reserve: int = 500_000          # the receiver never pays out below this
    max_per_trade: int = 1_000_000  # one trade at most this much (larger single trades not live-tested yet)
    rules: dict = field(default_factory=dict)    # role -> (low, target)


DEFAULT_RULES = {'dispatcher': (200_000, 1_000_000), 'well': (20_000, 100_000), 'coast': (20_000, 100_000)}


def load_treasury(data):
    t = data.get('treasury', {})
    rules = dict(DEFAULT_RULES)
    for role, pair in t.items():
        if isinstance(pair, list):
            low, target = (int(v) for v in pair)
            if not 0 <= low <= target:
                raise ValueError(f'[treasury] {role} 应是 [下限, 目标] 且下限 <= 目标，实际 {pair}')
            rules[role] = (low, target)
    s = TreasurySettings(enabled=bool(t.get('enabled', True)), reserve=int(t.get('reserve', 500_000)),
                         max_per_trade=int(t.get('max_per_trade', 1_000_000)), rules=rules)
    if s.max_per_trade <= 0:
        raise ValueError('[treasury] max_per_trade 应大于 0')
    return s


def load_treasury_file(path):
    import tomllib
    path = Path(path)
    return load_treasury(tomllib.loads(path.read_text('utf-8')) if path.is_file() else {})


# ---- pure decisions ---------------------------------------------------------------------------------------

def shortfall(role, gold, s):
    """Gold this station should get now (0 = enough or no rule)."""
    rule = s.rules.get(role)
    if not s.enabled or rule is None or gold is None or gold >= rule[0]:
        return 0
    return rule[1] - gold


def chunks(amount, treasury_gold, s):
    """Split a top-up into trades, paying only what the treasury has above its reserve."""
    amount = min(amount, max(0, treasury_gold - s.reserve))
    out = []
    while amount > 0:
        out.append(min(amount, s.max_per_trade))
        amount -= out[-1]
    return out


@dataclass(frozen=True)
class Decision:
    kind: str       # wait | trade | verified | unconfirmed | fail
    reason: str


def decide(me, treasury, me_gold, treasury_gold, amount, memo, now):
    """One step of one paid trade. me / treasury: WorldState | None; memo: Memo."""
    if memo.sent_at is not None:
        got, paid = (me_gold or 0) - memo.me_before, memo.treasury_before - (treasury_gold or 0)
        if amount <= got <= amount + QUIZ_SLACK and amount - QUIZ_SLACK <= paid <= amount:
            return Decision('verified', f'拨款到账 {amount}：本工位 {memo.me_before} -> {me_gold}，'
                                        f'收货人 {memo.treasury_before} -> {treasury_gold}')
        if now - memo.sent_at < CONFIRM_WAIT:
            return Decision('wait', '等拨款到账')
        return Decision('unconfirmed', f'{CONFIRM_WAIT:.0f}s 内拨款没到（本工位 +{got}，收货人 -{paid}）')
    if me is None or treasury is None or me_gold is None or treasury_gold is None:
        return Decision('wait', '加载中')
    if me.map_id != COAST_MAP or treasury.map_id != COAST_MAP:
        return Decision('fail', f'不都在平静海岸2区（本工位地图 {me.map_id}，收货人地图 {treasury.map_id}）')
    distance = math.dist((me.x, me.y), (treasury.x, treasury.y))
    if distance > TRADE_RANGE:
        return Decision('fail', f'离收货人太远 ({distance:.0f} > {TRADE_RANGE})')
    if not _idle(me) or not _idle(treasury):
        return Decision('wait', '本工位或收货人忙/战斗/移动/验证中')
    return Decision('trade', f'收货人拨款 {amount}（距离 {distance:.0f}）')


@dataclass
class Memo:
    sent_at: float | None = None
    me_before: int = 0
    treasury_before: int = 0


# ---- the trade ----------------------------------------------------------------------------------------------

class Treasury:
    """What a station needs to be paid: the shared lock and a way to find the receiver's window.
    find(conn) -> procs.Client of the receiver, or None when it is not online (conn: the caller thread's db)."""

    def __init__(self, settings, find, lock=None):
        self.s, self.find = settings, find
        self.lock = lock or threading.Lock()


def pay(treasury, conn, me_client, me_game, me_mem, amount, logger, gap=0.5, tick=0.2, timeout=60.0):
    """Top this station up by `amount` from the receiver standing next to it. -> gold received (may be less than
    asked when the treasury is short). Raises RuntimeError when it cannot be done."""
    recv = treasury.find(conn)
    if recv is None:
        raise RuntimeError('收货人（财政主管）不在线')
    received = 0
    with treasury.lock, ProcessMemory(recv.session.pid, recv.session.base) as rmem:
        rgame = Game(recv.session, rmem)
        try:
            for part in chunks(amount, read_gold(rmem) or 0, treasury.s):
                received += _one(rgame, recv, rmem, me_client, me_game, me_mem, part, logger, gap, tick, timeout)
        finally:
            rgame.close()
    if received < amount:
        logger.warning('财政主管只拨了 %d / %d（保留 %d 不动）', received, amount, treasury.s.reserve)
    return received


def _one(rgame, recv, rmem, me_client, me_game, me_mem, amount, logger, gap, tick, timeout):
    memo, tries, last, started = Memo(), 0, None, time.monotonic()
    while time.monotonic() - started < timeout:
        now = time.monotonic()
        d = decide(read_world(me_mem), read_world(rmem), read_gold(me_mem), read_gold(rmem), amount, memo, now)
        if d.reason != last:
            logger.info('%s', d.reason)
        last = d.reason
        if d.kind == 'verified':
            return amount
        if d.kind == 'fail':
            raise RuntimeError(d.reason)
        if d.kind == 'unconfirmed':
            tries += 1
            if tries >= TRIES:
                raise RuntimeError(f'拨款 {TRIES} 次都没到账')
            memo = Memo()
            time.sleep(1.0)                 # let a half-open trade time out before inviting again
        elif d.kind == 'trade':
            memo = Memo(me_before=read_gold(me_mem), treasury_before=read_gold(rmem))
            steps = ((rgame.trade_invite, (me_client.char_id,)), (me_game.trade_accept, (recv.char_id,)),
                     (rgame.trade_offer_gold, (amount,)), (rgame.trade_confirm, ()),
                     (me_game.trade_offer_gold, (0,)), (me_game.trade_confirm, ()))
            try:
                for i, (step, args) in enumerate(steps):
                    if i:
                        time.sleep(gap)
                    step(*args)
            except NotSent as e:
                raise RuntimeError(f'交易请求没发出: {e}') from e
            memo.sent_at = time.monotonic()
        time.sleep(tick)
    raise RuntimeError(f'拨款 {timeout:.0f}s 内没有完成')
