"""Leader supplies: between two batches a station buys 回城卷 / 红药 / 蓝药 / 宠物药 when it runs low and sells junk
when its bag fills up, so nobody has to restock the leaders by hand.

Entry (manual / test): python -m factory.supply [factory.toml] <role> <character name>
In production the supervisor calls village_supply() / coast_supply() at the start of a batch.

Shops (user, 2026-10-20; buying verified live on box01, client 2.98; selling on cap07, client 2.99: 6 junk slots
sold at 花袭人 for +578 = half the ItemLib price, supplies and 重要物品 kept):
  军医花袭人 NPC 409, map 81 at the PP鸡 landing (1152,932), shelf 5: 0 萝卜糕 64002 (5), 2 胡萝卜汁 63954 (5),
      4 回城卷 9801 (100); options 1 购买杂货, 2 出售物品
  宠物商人小美 NPC 329, map 1 at the village start (1338,1155) where a 回城卷 lands, shelf 13: 7 甜点 8573 (240);
      options 1 购买宠物道具, 3 出售物品
Requests: open = 0x50 <I 0><I npc> + 0x51 <I 0><I option><I 0>; then ONE
0x55 <I 0><I npc><B 1><B 0 buy | 1 sell><H 0><B shelf slot | bag slot><B qty>. Every buy needs a fresh open (a
second 0x55 without one is ignored). A buy fills the existing stack first, then new bag slots. Afterwards the NPC
dialog is closed (离开 = SelectNpcDialogEntry(0)): left open, the next NPC's dialog is misread (live 2026-10-20:
小美's dialog was taken for PP鸡's).

Who buys where (user-agreed 2026-10-20: leaders fetch cross-map supplies themselves, lowest-priced items):
  village stations (well leaders, dispatcher), idle in the village between batches:
      甜点 low or bag nearly full -> 小美 right there (sell, buy); 回城卷/红/蓝 low -> PP鸡 to 81, 花袭人, 回城卷 home
  coast stations (coast leaders), on map 81 before a batch:
      回城卷/红/蓝 low or bag nearly full -> 花袭人 at the landing; 甜点 low -> 回城卷 home, 小美, PP鸡 back
Low = below [supply.<role>] low; then buy up to target in one go, so trips stay rare. Junk = factory/items.py with the
leader rule (equipment except blue-or-better, every 技能石, 配方, 杂物; user 2026-10-20); anything we buy is never
sold. A failed supply run is logged and retried after retry_after; the batch itself always goes on.
Decisions are pure (tests/test_factory_supply.py).
"""
import math
import struct
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from provisioner import log, native, procs
from provisioner.game import NotSent
from provisioner.memory import ProcessMemory
from provisioner.world import read_bag, read_bag_capacity, read_dialog, read_gold, read_world

from . import db, items
from .coast import LANDING, CoastRun
from .config import ROOT, load_settings
from .phase import COAST_MAP, SCROLL_ITEM, VILLAGE_MAP
from .treasury import Treasury, load_treasury_file, pay, shortfall

HP_ITEM, MP_ITEM, PET_ITEM = 64002, 63954, 8573          # 萝卜糕, 胡萝卜汁, 甜点
ITEM_KEYS = {'scroll': SCROLL_ITEM, 'hp': HP_ITEM, 'mp': MP_ITEM, 'pet': PET_ITEM}
ITEM_NAMES = {SCROLL_ITEM: '回城卷', HP_ITEM: '萝卜糕', MP_ITEM: '胡萝卜汁', PET_ITEM: '甜点'}
STACK = {SCROLL_ITEM: 50, HP_ITEM: 99, MP_ITEM: 99, PET_ITEM: 99}
MAX_QTY = 99                    # one 0x55 buys at most this many (the qty byte; tested 99)

OP_CLICK_NPC, OP_DIALOG, OP_SHOP = 0x50, 0x51, 0x55
CLOSE_WAIT = 2.0                # the NPC dialog must be gone this long after 离开
SHOP_RANGE = 120                # stand this close to the shop spot before talking (box01 talked from ~0)
OPEN_SETTLE = 0.6               # after the open, before the 0x55 (box01: the UI took < 0.5 s)
VERIFY_WAIT = 3.0               # the bag must show the change this long after the 0x55
SELL_LIMIT = 100                # junk sold per visit = the whole bag (user 2026-10-20: sell everything sellable; the
                                # game's own 自动卖店 stops at 20, we do not)
LANDING_SCROLL_WAIT = 8.0


@dataclass(frozen=True)
class Shop:
    name: str
    npc: int
    map_id: int
    spot: tuple
    shelf: dict                 # item_id -> shelf slot
    buy_option: int
    sell_option: int            # 出售物品


NURSE = Shop('军医花袭人', 409, COAST_MAP, LANDING, {HP_ITEM: 0, MP_ITEM: 2, SCROLL_ITEM: 4}, 1, 2)
PETSHOP = Shop('宠物商人小美', 329, VILLAGE_MAP, (1338, 1155), {PET_ITEM: 7}, 1, 3)
PRICE = {SCROLL_ITEM: 100, HP_ITEM: 5, MP_ITEM: 5, PET_ITEM: 240}


@dataclass(frozen=True)
class SupplySettings:
    enabled: bool = True
    keep_free: int = 3              # never buy into the last free bag slots
    sell_below_free: int = 8        # fewer free slots than this -> sell junk at 花袭人
    retry_after: float = 600.0      # a failed supply run is tried again this long after
    timeout: float = 300.0          # one supply run (walking + trips + shopping) at most this long
    rules: dict = field(default_factory=dict)   # role -> {item_id: (low, target)}


DEFAULT_RULES = {
    'well': {SCROLL_ITEM: (20, 100), HP_ITEM: (30, 198), MP_ITEM: (30, 198), PET_ITEM: (10, 99)},
    'coast': {SCROLL_ITEM: (20, 100), HP_ITEM: (30, 198), MP_ITEM: (30, 198), PET_ITEM: (10, 99)},
    'dispatcher': {SCROLL_ITEM: (20, 100)},
}


def load_supply(data):
    """[supply] + [supply.<role>] (item = [low, target], items: scroll hp mp pet) -> SupplySettings."""
    s = data.get('supply', {})
    rules = {role: dict(wanted) for role, wanted in DEFAULT_RULES.items()}
    for role, wanted in s.items():
        if not isinstance(wanted, dict):
            continue
        rules[role] = {}
        for key, pair in wanted.items():
            if key not in ITEM_KEYS:
                raise ValueError(f'[supply.{role}] 不认识 {key}（可用 {", ".join(ITEM_KEYS)}）')
            low, target = (int(v) for v in pair)
            if not 0 <= low <= target:
                raise ValueError(f'[supply.{role}] {key} 应是 [下限, 上限] 且下限 <= 上限，实际 {pair}')
            rules[role][ITEM_KEYS[key]] = (low, target)
    return SupplySettings(enabled=bool(s.get('enabled', True)), keep_free=int(s.get('keep_free', 3)),
                          sell_below_free=int(s.get('sell_below_free', 8)),
                          retry_after=float(s.get('retry_after_minutes', 10)) * 60,
                          timeout=float(s.get('timeout', 300)), rules=rules)


def load_supply_file(path):
    import tomllib
    path = Path(path)
    return load_supply(tomllib.loads(path.read_text('utf-8')) if path.is_file() else {})


# ---- pure decisions ---------------------------------------------------------------------------------------

def counts(bag):
    out = {}
    for s in bag:
        out[s.item_id] = out.get(s.item_id, 0) + s.quantity
    return out


def shortages(bag, rules):
    """{item: amount to buy} for the items below their low mark (up to target)."""
    have = counts(bag)
    return {item: target - have.get(item, 0) for item, (low, target) in rules.items() if have.get(item, 0) < low}


def plan_buys(bag, capacity, wanted, shop, gold, keep_free):
    """[(shelf slot, item, qty)] for this shop: fill existing stacks first, then new slots while more than keep_free
    stay empty, and only what the gold pays for. Each entry is one 0x55 (qty <= 99)."""
    free = capacity - len(bag) - keep_free
    plan = []
    for item, amount in wanted.items():
        if item not in shop.shelf or amount <= 0:
            continue
        stack = STACK[item]
        room = sum(stack - s.quantity for s in bag if s.item_id == item and s.quantity < stack)
        while amount > room and free > 0:
            room += stack
            free -= 1
        amount = min(amount, room, gold // PRICE[item])
        gold -= amount * PRICE[item]
        while amount > 0:
            qty = min(amount, MAX_QTY)
            plan.append((shop.shelf[item], item, qty))
            amount -= qty
    return plan


def junk(bag, table, keep, limit=SELL_LIMIT):
    """Bag slots a leader sells (factory/items.py leader rule), never one we keep."""
    return items.sell_slots(bag, table, keep, leader=True, limit=limit)


def needs(bag, capacity, rules, s):
    """What this station should do now: (coast items to buy, village items to buy, sell junk?)."""
    short = shortages(bag, rules)
    coast = {i: n for i, n in short.items() if i in NURSE.shelf}
    village = {i: n for i, n in short.items() if i in PETSHOP.shelf}
    return coast, village, capacity - len(bag) < s.sell_below_free


# ---- talking to a shop ------------------------------------------------------------------------------------

class ShopClient:
    def __init__(self, game, mem, logger, sleep=time.sleep, clock=time.monotonic):
        self.game, self.mem, self.log, self.sleep, self.clock = game, mem, logger, sleep, clock

    def open(self, shop, option):
        self.game.send(OP_CLICK_NPC, struct.pack('<II', 0, shop.npc))
        self.sleep(OPEN_SETTLE)
        self.game.send(OP_DIALOG, struct.pack('<III', 0, option, 0))
        self.sleep(OPEN_SETTLE)

    def close(self):
        """离开: close the NPC dialog and wait until it is gone. -> True when closed."""
        self.game.select_dialog(0)
        end = self.clock() + CLOSE_WAIT
        while self.clock() < end:
            if read_dialog(self.mem) is None:
                return True
            self.sleep(0.2)
        self.log.warning('NPC 对话框 %.0fs 内没关上', CLOSE_WAIT)
        return False

    def _request(self, shop, sell, slot, qty):
        self.game.send(OP_SHOP, struct.pack('<IIBBHBB', 0, shop.npc, 1, int(sell), 0, slot, qty))

    def _wait(self, done):
        end = self.clock() + VERIFY_WAIT
        while self.clock() < end:
            bag = read_bag(self.mem)
            if bag is not None and done(bag):
                return True
            self.sleep(0.2)
        return False

    def buy(self, shop, shelf_slot, item, qty):
        """One verified purchase. -> True when the bag holds qty more."""
        before = counts(read_bag(self.mem) or ()).get(item, 0)
        self.open(shop, shop.buy_option)
        self._request(shop, False, shelf_slot, qty)
        ok = self._wait(lambda bag: counts(bag).get(item, 0) >= before + qty)
        self.log.info('%s 买 %s ×%d %s', shop.name, ITEM_NAMES.get(item, item), qty, '成功' if ok else '没到账')
        return ok

    def sell(self, shop, slots):
        """Sell the given bag slots, one verified request each. -> number sold."""
        sold = 0
        for s in slots:
            self.open(shop, shop.sell_option)
            self._request(shop, True, s.slot, s.quantity)
            if self._wait(lambda bag: all(b.slot != s.slot or b.item_id != s.item_id for b in bag)):
                sold += 1
            else:
                self.log.warning('%s 卖 背包第 %d 格（物品 %d ×%d）没成功', shop.name, s.slot, s.item_id, s.quantity)
        return sold


# ---- the run ----------------------------------------------------------------------------------------------

class SupplyRun(CoastRun):
    """One station's supply errand. Walks with the coast leaders' code (to_coast = back to 81, PP鸡 from the
    village; goto = walk on 81), so the receiver-style subclass needs no team."""

    def __init__(self, conn, station, client, mem, settings, logger, role, supply, sellable, treasury=None):
        super().__init__(conn, station, client, mem, {}, settings, logger)
        self.role, self.sup, self.sellable, self.treasury = role, supply, sellable, treasury
        self.rules = supply.rules.get(role, {})
        self.shop = ShopClient(self.lgame, mem, logger)
        self.done = {'bought': {}, 'sold': 0, 'paid': 0, 'gold_before': read_gold(mem)}

    def check(self):
        if time.monotonic() - self.started > self.sup.timeout:
            raise RuntimeError(f'补给 {self.sup.timeout:.0f}s 内没有完成')
        if not native.alive(self.leader.session.pid):
            raise RuntimeError(f'游戏进程 {self.leader.session.pid} 已退出')
        w = read_world(self.lmem)
        if w and w.char_id != self.leader.char_id:
            raise RuntimeError('角色变了')
        return w

    def periodic(self, now, status):
        if now - self.last_observe >= 10.0:
            self.last_observe = now
            db.heartbeat(self.conn, self.sid(), self.role, self.leader.char_id, 'supplying', time.time())

    def bag(self):
        bag, cap = read_bag(self.lmem), read_bag_capacity(self.lmem)
        if bag is None or cap is None:
            raise RuntimeError('读不到背包')
        return bag, cap

    def at(self, shop):
        """Stand at the shop spot (walking on 81 fights on the way; in the village there are no monsters)."""
        w = self.check()
        if w.map_id != shop.map_id:
            raise RuntimeError(f'不在 {shop.name} 所在的地图 {shop.map_id}（在 {w.map_id}）')
        if math.dist((w.x, w.y), shop.spot) <= SHOP_RANGE:
            return
        if shop.map_id == COAST_MAP:
            self.goto(shop.spot, f'去{shop.name}', 'supplying')
            return
        self.lgame.navigate(shop.map_id, *shop.spot)
        end = time.monotonic() + 60
        while time.monotonic() < end:
            time.sleep(0.5)
            w = self.check()
            if w and math.dist((w.x, w.y), shop.spot) <= SHOP_RANGE and not w.nav_active:
                return
        raise RuntimeError(f'60s 内没走到{shop.name}')

    def visit(self, shop, wanted, sell):
        """Sell junk (if asked) then buy what is wanted, at the shop's spot; the dialog is closed afterwards."""
        self.at(shop)
        try:
            self._shop(shop, wanted, sell)
        finally:
            self.shop.close()

    def _shop(self, shop, wanted, sell):
        if sell:
            bag, _ = self.bag()
            slots = junk(bag, self.sellable, set(self.rules) | set(ITEM_NAMES))
            if slots:
                self.log.info('背包快满，在%s卖 %d 格杂物', shop.name, len(slots))
                self.done['sold'] += self.shop.sell(shop, slots)
        bag, cap = self.bag()
        gold = read_gold(self.lmem) or 0
        plan = plan_buys(bag, cap, wanted, shop, gold, self.sup.keep_free)
        if wanted and not plan:
            self.log.warning('在%s什么也买不了（背包空位 %d，金币 %d）', shop.name, cap - len(bag), gold)
        for shelf_slot, item, qty in plan:
            if self.shop.buy(shop, shelf_slot, item, qty):
                self.done['bought'][item] = self.done['bought'].get(item, 0) + qty

    def scroll_home(self):
        """回城卷 from map 81 to the village start (next to 小美)."""
        bag, _ = self.bag()
        slot = next((s.slot for s in bag if s.item_id == SCROLL_ITEM), None)
        if slot is None:
            raise RuntimeError('没有回城卷，回不了村')
        self.log.info('用回城卷回村（背包第 %d 格）', slot)
        self.lgame.use_item(slot)
        end = time.monotonic() + LANDING_SCROLL_WAIT
        while time.monotonic() < end:
            time.sleep(0.5)
            w = self.check()
            if w and w.map_id == VILLAGE_MAP:
                return w
        raise RuntimeError(f'回城卷 {LANDING_SCROLL_WAIT:.0f}s 后还没回到村里')

    def money(self):
        """Gold this station should get from the treasury now (0 = enough / no treasury)."""
        return shortfall(self.role, read_gold(self.lmem), self.treasury.s) if self.treasury else 0

    def bank(self, amount):
        """Walk to the receiver post on map 81 and get `amount` from the treasury."""
        self.log.info('金币低于下限，去收货人（财政主管）那里领 %d', amount)
        self.goto(self.s.receiver_post, '去收货人那里领金币', 'supplying')
        self.done['paid'] += pay(self.treasury, self.conn, self.leader, self.lgame, self.lmem, amount, self.log,
                                 gap=self.s.trade_step_gap, tick=self.s.tick)

    def clear_dialog(self):
        if read_dialog(self.lmem) is not None:
            self.log.info('先关掉开着的 NPC 对话框')
            self.shop.close()

    def village_run(self):
        """Well leader / dispatcher, idle in the village."""
        self.clear_dialog()
        bag, cap = self.bag()
        coast, village, sell = needs(bag, cap, self.rules, self.sup)
        money = self.money()
        if village or sell:
            self.visit(PETSHOP, village, sell)
        if coast or money:
            self.log.info('去海岸补给（%s）', describe(coast, False, money))
            self.to_coast()
            if money:
                self.bank(money)
            if coast:
                self.visit(NURSE, coast, False)
            self.scroll_home()
        return self.summary()

    def coast_run(self):
        """Coast leader before a batch: on 81 (to_coast brings it back from anywhere)."""
        self.clear_dialog()
        self.to_coast()
        money = self.money()
        if money:
            self.bank(money)
        bag, cap = self.bag()
        coast, village, sell = needs(bag, cap, self.rules, self.sup)
        if coast or sell:
            self.visit(NURSE, coast, sell)
        if village:
            self.log.info('回村找小美买 %s', describe(village, False))
            self.scroll_home()
            self.visit(PETSHOP, village, False)
            self.to_coast()
        return self.summary()

    def summary(self):
        gold = read_gold(self.lmem)
        before = self.done['gold_before']
        out = {'bought': {ITEM_NAMES[i]: n for i, n in self.done['bought'].items()}, 'sold': self.done['sold'],
               'paid': self.done['paid'], 'gold_change': None if gold is None or before is None else gold - before}
        if out['paid']:
            db.log_event(self.conn, time.time(), 'treasury', f'财政主管拨款 {out["paid"]}', station_id=self.sid())
        if out['bought'] or out['sold']:
            db.log_event(self.conn, time.time(), 'supply', f'买 {out["bought"]} 卖 {out["sold"]} 格 金币变化 '
                         f'{out["gold_change"]}', station_id=self.sid())
        return out


def describe(items, sell, money=0):
    parts = [f'{ITEM_NAMES[i]} {n}' for i, n in items.items()]
    if sell:
        parts.append('卖杂物')
    if money:
        parts.append(f'领金币 {money}')
    return '、'.join(parts) or '无'


def due(role, bag, capacity, supply, gold=None, treasury=None):
    """True when this station has something to buy, sell or collect now (cheap check before starting a run)."""
    rules = supply.rules.get(role, {})
    coast, village, sell = needs(bag, capacity, rules, supply)
    shop = supply.enabled and bool(rules) and bool(coast or village or sell)
    return shop or bool(treasury and shortfall(role, gold, treasury.s))


class Gate:
    """Per-station retry pause after a failed supply run (keeps a broken shop from slowing every batch)."""

    def __init__(self, retry_after, clock=time.monotonic):
        self.retry_after, self.clock, self.failed_at = retry_after, clock, {}

    def open(self, sid):
        t = self.failed_at.get(sid)
        return t is None or self.clock() - t >= self.retry_after

    def failed(self, sid):
        self.failed_at[sid] = self.clock()

    def ok(self, sid):
        self.failed_at.pop(sid, None)


def run_supply(conn, station, client, mem, settings, supply, sellable, gate, logger, village, treasury=None):
    """Supervisor hook: one supply errand (shopping and / or a treasury top-up) if due, never raising.
    village: True = village station."""
    sid = station['station_id']
    if not gate.open(sid):
        return None
    bag, cap = read_bag(mem), read_bag_capacity(mem)
    if bag is None or cap is None or not due(station['role'], bag, cap, supply, read_gold(mem), treasury):
        return None
    run = SupplyRun(conn, station, client, mem, settings, logger, station['role'], supply, sellable, treasury)
    try:
        result = run.village_run() if village else run.coast_run()
        gate.ok(sid)
        logger.info('补给完成: %s', result)
        return result
    except Exception as e:      # noqa: BLE001 - supplies never stop the batch
        gate.failed(sid)
        logger.error('补给失败（%.0f 分钟后再试）: %s', supply.retry_after / 60, e, exc_info=not isinstance(e, RuntimeError))
        db.log_event(conn, time.time(), 'supply_fail', str(e), station_id=sid)
        return None
    finally:
        run.close()


def main():
    """python -m factory.supply [factory.toml] <role> <name>: one supply errand for one online character."""
    args = sys.argv[1:]
    cfg = Path(args.pop(0)) if args and args[0].endswith('.toml') else ROOT / 'factory.toml'
    if len(args) != 2 or args[0] not in DEFAULT_RULES:
        print(f'用法: python -m factory.supply [factory.toml] <{"|".join(DEFAULT_RULES)}> <角色名>')
        return 2
    role, name = args
    log_path = log.setup(ROOT / 'logs', prefix='supply')
    logger = log.for_account(name)
    logger.info('日志文件: %s', log_path)
    settings = load_settings(cfg)
    supply = load_supply_file(cfg)
    client = next((c for c in procs.discover(logger) if c.name == name), None)
    if client is None:
        logger.error('%s 不在本工具的窗口里在线', name)
        return 2
    conn = db.connect(settings.db_path)
    station = {'station_id': f'supply-{name}', 'role': role, 'char_id': client.char_id}

    def receiver(c):        # the treasury: the registered receiver station's window
        row = c.execute("SELECT char_id FROM stations WHERE role='receiver' ORDER BY station_id").fetchone()
        return next((x for x in procs.discover(logger) if row and x.char_id == row['char_id']), None)

    ts = load_treasury_file(cfg)
    treasury = Treasury(ts, receiver) if ts.enabled else None
    with ProcessMemory(client.session.pid, client.session.base) as mem:
        run = SupplyRun(conn, station, client, mem, settings, logger, role, supply, items.table(), treasury)
        try:
            village = role in ('well', 'dispatcher')
            result = run.village_run() if village else run.coast_run()
        finally:
            run.close()
    logger.info('结果: %s', result)
    conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
