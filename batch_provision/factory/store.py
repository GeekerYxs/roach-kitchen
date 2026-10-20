"""料理仓库号 stage 2a: fresh accounts box07..box16 become store characters for the receiver's 美味小强料理.

Entry: python -m factory.store [store.toml]   (一键建仓库号.cmd)
Accounts: local.toml [store_accounts] (store.toml [accounts] from = "store_accounts"); 4 roles each, named
<account>仓<N> (box07仓1 .. box07仓4). Never <...>r<digits>: factory/runner.py ROLE_NAME would take it for an alt.
Per account:
  1. create the missing roles (provisioner AccountJob, the 一键建角 code, role_suffix from store.toml)
Per role (provisioner/pipeline.py AccountRun, one window per role, closed afterwards):
  2. login -> enter the slot -> 菜鸟训练营 -> 逍遥村西区 (provisioner/novice.py, 一键新手出村)
  3. eat one (御)小肉林 and one (御)小酒池 (0x49 use item, verified by the bag count, like factory/meat.py)
  4. walk to 宠物商人小美 and sell the novice gear: every equipment slot + 萝卜糕 + 胡萝卜汁 (factory/supply.py
     ShopClient; nothing else is sold)
  5. read the bag: at least [store] free_min empty slots (35 of 40) -> factory.db stores row status village_ready
Every step reads the bag first and does only what is still missing, so a run can stop anywhere and the .cmd can be
double-clicked again; roles with a village_ready row are skipped. Stage 2b (1000 gold, PP鸡 to the receiver) and 2c
(the supervisor using the stores) are not here.
Pure parts: store_names, sell_slots, eat_slot, decide (tests/test_factory_store.py).
"""
import json
import math
import sys
import threading
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from provisioner import config, log, native
from provisioner.game import Game, NotSent
from provisioner.login import LaunchThrottle
from provisioner.memory import ProcessMemory
from provisioner.pipeline import AccountRun, OwnWindows
from provisioner.procs import game_pids
from provisioner.world import item_count, read_bag, read_bag_capacity, read_dialog, read_world
from provisioner.worker import AccountJob

from . import db, items
from .config import ROOT, load_settings
from .phase import VILLAGE_MAP
from .runner import ROLE_NAME
from .supply import HP_ITEM, MP_ITEM, PETSHOP, SHOP_RANGE, ShopClient

# ItemLib (Gemini unpacked ResLib/ItemLib_utf8.csv): 30188 (御)小肉林, 30187 (御)小酒池, 30186 小肉林, 30185 小酒池
MEAT_ITEMS = (30188, 30186)
WINE_ITEMS = (30187, 30185)
EAT_NAMES = {30188: '(御)小肉林', 30186: '小肉林', 30187: '(御)小酒池', 30185: '小酒池'}
NOVICE_FOOD = (HP_ITEM, MP_ITEM)              # 萝卜糕, 胡萝卜汁 (30 each in a new bag)

EAT_WAIT = 5.0          # the bag count must drop this long after a 0x49
EAT_TRIES = 3
NAV_RETRY = 3.0
STALL = 6.0
SELL_TRIES = 2


@dataclass(frozen=True)
class StoreSettings:
    free_min: int = 35          # empty bag slots a store must have after stage 2a
    timeout: float = 180.0      # eat + walk + sell for one role
    tick: float = 0.2


def load_store(data):
    s = data.get('store', {})
    return StoreSettings(free_min=int(s.get('free_min', 35)), timeout=float(s.get('timeout', 180)),
                         tick=float(s.get('tick', 0.2)))


# ---- pure decisions ---------------------------------------------------------------------------------------

def store_names(settings, account):
    """Role names of one store account; refuses names the alt machinery would claim (…r<digits>)."""
    names = settings.role_names(account)
    bad = [n for n in names if ROLE_NAME.match(n)]
    if bad:
        raise ValueError(f'仓库号名字 {bad} 以 r+数字 结尾，总大脑会把它们当小号；请改 store.toml 的 role_suffix')
    return names


def sell_slots(bag, table):
    """The novice gear a store sells: every equipment slot plus 萝卜糕 / 胡萝卜汁 (all priced in items.csv).
    Nothing else (小肉林 / 小酒池 are eaten, anything unknown stays)."""
    return [s for s in bag if s.item_id in table and
            (table[s.item_id].type in items.EQUIP_TYPES or s.item_id in NOVICE_FOOD)]


def eat_slot(bag, eaten):
    """Next (slot, item) to eat: one of the 小肉林 kind, one of the 小酒池 kind; `eaten` = kinds done this run."""
    for kind, ids in (('meat', MEAT_ITEMS), ('wine', WINE_ITEMS)):
        if kind in eaten:
            continue
        slot = next((s for s in bag if s.item_id in ids), None)
        if slot:
            return kind, slot
    return None


@dataclass(frozen=True)
class Decision:
    kind: str       # 'wait' | 'fail' | 'eat' | 'walk' | 'arrived' | 'sell' | 'done' | 'short'
    reason: str
    arg: object = None


def decide(world, bag, capacity, table, eaten, free_min, shop=PETSHOP, rule=sell_slots):
    """One step of stage 2a from what the client shows now. eaten: kinds already eaten this run.
    rule(bag, table) -> slots to sell (stage 2b sells the well drops with the alt rule, factory/items.py)."""
    if world is None or bag is None or capacity is None:
        return Decision('wait', '加载中')
    if world.map_id != VILLAGE_MAP:
        return Decision('fail', f'不在逍遥村西区（地图 {world.map_id}）')
    if world.verification:
        return Decision('wait', '验证码弹窗，等待答题')
    if world.in_battle or world.busy:
        return Decision('wait', '角色忙/战斗中')
    food = eat_slot(bag, eaten)
    if food:
        kind, slot = food
        return Decision('eat', f'吃{EAT_NAMES[slot.item_id]}（背包第 {slot.slot} 格，{slot.quantity} 个）', food)
    junk = rule(bag, table)
    if junk:
        distance = math.dist((world.x, world.y), shop.spot)
        if distance > SHOP_RANGE:
            if world.nav_active or world.moving:
                return Decision('wait', f'走向{shop.name}（距离 {distance:.0f}）')
            return Decision('walk', f'去{shop.name}（距离 {distance:.0f}）')
        if world.nav_active:
            return Decision('arrived', f'到了{shop.name}，停下寻路')
        return Decision('sell', f'在{shop.name}卖 {len(junk)} 格新手物品', junk)
    free = capacity - len(bag)
    if free < free_min:
        return Decision('short', f'背包空 {free}/{capacity} 格，少于 {free_min}', free)
    return Decision('done', f'背包空 {free}/{capacity} 格', free)


# ---- one role in the village ------------------------------------------------------------------------------

class VillagePrep:
    """Steps 3-5 for one entered store role (its window, ProcessMemory and Game are opened here)."""

    def __init__(self, session, char_id, settings, logger, table=None, rule=sell_slots):
        self.session, self.char_id, self.s, self.log = session, char_id, settings, logger
        self.table = table if table is not None else items.table()
        self.rule = rule

    def run(self):
        """-> dict(free, capacity, bag, eaten, sold, x, y); raises RuntimeError when the role is not ready."""
        with ProcessMemory(self.session.pid, self.session.base) as mem:
            game = Game(self.session, mem)
            shop = ShopClient(game, mem, self.log)
            try:
                if read_dialog(mem) is not None:
                    shop.close()
                bag = read_bag(mem)
                self.log.info('背包（准备前）: %s', describe(bag, self.table))
                return self._loop(mem, game, shop)
            finally:
                if read_dialog(mem) is not None:
                    shop.close()
                game.close()

    def _loop(self, mem, game, shop):
        started = time.monotonic()
        out = {'eaten': [], 'sold': 0}
        eaten, eat_tries, sells, last_nav, last_reason = set(), {}, 0, 0.0, None
        while True:
            now = time.monotonic()
            if now - started > self.s.timeout:
                raise RuntimeError(f'{self.s.timeout:.0f}s 内没有准备好')
            if not native.alive(self.session.pid):
                raise RuntimeError('游戏进程已退出')
            world, bag, capacity = read_world(mem), read_bag(mem), read_bag_capacity(mem)
            if world and world.char_id != self.char_id:
                raise RuntimeError(f'角色变了 {self.char_id} -> {world.char_id}')
            d = decide(world, bag, capacity, self.table, eaten, self.s.free_min, rule=self.rule)
            if d.reason != last_reason:
                self.log.info('%s', d.reason)
            last_reason = d.reason
            if d.kind == 'fail':
                raise RuntimeError(d.reason)
            if d.kind == 'short':
                self.log.error('背包: %s', describe(bag, self.table))
                raise RuntimeError(d.reason)
            if d.kind == 'done':
                out.update(free=d.arg, capacity=capacity, bag=[(s.slot, s.item_id, s.quantity) for s in bag],
                           x=round(world.x), y=round(world.y))
                self.log.info('背包（准备后）: %s', describe(bag, self.table))
                return out
            if d.kind == 'eat':
                kind, slot = d.arg
                eat_tries[kind] = eat_tries.get(kind, 0) + 1
                if self._eat(mem, game, slot):
                    eaten.add(kind)
                    out['eaten'].append(EAT_NAMES[slot.item_id])
                elif eat_tries[kind] >= EAT_TRIES:
                    raise RuntimeError(f'{EAT_NAMES[slot.item_id]} 吃了 {EAT_TRIES} 次数量都没变')
            elif d.kind == 'walk' and now - last_nav >= NAV_RETRY:
                game.navigate(VILLAGE_MAP, *PETSHOP.spot)
                last_nav = now
            elif d.kind == 'wait' and world and world.nav_active and world.still_for >= STALL and \
                    now - last_nav >= STALL:
                self.log.info('%.0fs 没动，重新寻路', world.still_for)
                game.cancel_navigation()
                last_nav = 0.0
            elif d.kind == 'arrived':
                game.cancel_navigation()
            elif d.kind == 'sell':
                sells += 1
                if sells > SELL_TRIES:
                    names = [describe((s,), self.table) for s in d.arg]
                    raise RuntimeError(f'{PETSHOP.name} 卖了 {SELL_TRIES} 次还剩 {len(d.arg)} 格: {"; ".join(names)}')
                try:
                    out['sold'] += shop.sell(PETSHOP, d.arg)
                finally:
                    shop.close()
            time.sleep(self.s.tick)

    def _eat(self, mem, game, slot):
        """One 0x49 on this bag slot. -> True when the item's count dropped."""
        before = item_count(read_bag(mem) or (), slot.item_id)
        try:
            game.use_item(slot.slot)
        except NotSent as e:
            raise RuntimeError(f'吃{EAT_NAMES[slot.item_id]}没发出去: {e}') from None
        end = time.monotonic() + EAT_WAIT
        while time.monotonic() < end:
            time.sleep(0.2)
            if item_count(read_bag(mem) or (), slot.item_id) < before:
                self.log.info('%s %d -> %d', EAT_NAMES[slot.item_id], before, before - 1)
                return True
        self.log.warning('%s %.0fs 内数量没变（%d）', EAT_NAMES[slot.item_id], EAT_WAIT, before)
        return False


def describe(bag, table):
    if bag is None:
        return '读不到'
    return ', '.join(f'{s.slot}:{table[s.item_id].name if s.item_id in table else EAT_NAMES.get(s.item_id, s.item_id)}'
                     f'×{s.quantity}' for s in bag) or '空'


# ---- the run ----------------------------------------------------------------------------------------------

class StoreRun(AccountRun):
    """provisioner pipeline for one store role (login -> enter -> novice), plus VillagePrep and the stores row."""

    def __init__(self, s, account, slot, expected, throttle, own, account_lock, run_id, store_settings, db_path):
        super().__init__(s, account, slot, throttle, own, account_lock, run_id)
        self.expected, self.store_s, self.db_path = expected, store_settings, db_path

    def before_enter(self, char_id, name):
        if name != self.expected:
            raise RuntimeError(f'槽{self.slot} 是 {name}，不是 {self.expected}；不处理（请检查这个账号的角色）')

    def in_village(self, session, char_id, name, r):
        self._step('村里腾背包')
        r.update(VillagePrep(session, char_id, self.store_s, self.log).run())

    def run(self):
        r = super().run()
        conn = db.connect(self.db_path)
        try:
            status = db.STORE_VILLAGE_READY if r['ok'] else db.STORE_FAILED
            db.save_store(conn, self.account.name, self.slot, self.expected, status, time.time(),
                          char_id=r.get('char_id'), free_slots=r.get('free'), capacity=r.get('capacity'),
                          map_id=r.get('map_id'), x=r.get('x'), y=r.get('y'), error=r.get('error'))
            db.log_event(conn, time.time(), 'store', f'{self.expected} {status} 空格 {r.get("free")}'
                         f'{" " + r["error"] if r.get("error") else ""}', char_id=r.get('char_id'))
        finally:
            conn.close()
        return r


def todo_roles(accounts, names_of, ready):
    """[(account, slot, name)] still to prepare, account by account. ready: {(account, slot): name} done rows."""
    return [(a, slot, name) for a in accounts for slot, name in enumerate(names_of(a.name), 1)
            if ready.get((a.name, slot)) != name]


def main():
    cfg_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'store.toml'
    log_path = log.setup(ROOT / 'logs', prefix='store')
    logger = log.for_account('main')
    logger.info('日志文件: %s', log_path)
    try:
        create = config.load(cfg_path)
        pipe = config.load_pipeline(cfg_path)
        store_s = load_store(tomllib.loads(cfg_path.read_text('utf-8')))
        names = {a.name: store_names(create, a.name) for a in create.accounts}
        db_path = load_settings(ROOT / 'factory.toml').db_path
    except Exception as e:
        logger.error('配置错误 (%s): %s', cfg_path, e)
        return 2
    if not native.LAUNCHER.is_file():
        logger.error('缺少 %s，请先运行 native\\build.ps1', native.LAUNCHER)
        return 2
    conn = db.connect(db_path)
    ready = {(r['account'], r['slot']): r['name'] for r in db.stores(conn) if r['status'] == db.STORE_VILLAGE_READY}
    conn.close()
    roles = todo_roles(create.accounts, names.get, ready)
    logger.info('仓库账号 %d 个: %s；数据库 %s；已就绪跳过 %d 个角色，待处理 %d 个',
                len(create.accounts), ', '.join(names), db_path,
                sum(len(v) for v in names.values()) - len(roles), len(roles))
    if not roles:
        logger.info('全部仓库号都已在村里腾好背包')
        return 0
    logger.info('启动前已有游戏进程（不会被关闭）: %s', game_pids())
    throttle = LaunchThrottle(pipe.launch_interval, pipe.min_free_memory_mb)
    run_id = time.strftime('%Y%m%d_%H%M%S')
    started = time.monotonic()

    # 1. roles: the 一键建角 job for every account that still has roles to prepare (it skips existing ones)
    accounts = [a for a in create.accounts if any(r[0] is a for r in roles)]
    logger.info('== 建角: %s ==', ', '.join(a.name for a in accounts))
    with ThreadPoolExecutor(max_workers=create.parallel, thread_name_prefix='make') as pool:
        made = list(pool.map(lambda a: AccountJob(create, a, ROOT, throttle).run(), accounts))
    for m in made:
        logger.info('%s 建角%s 角色=%s%s', m['account'], '完成' if m['ok'] else '未完成', m.get('roles'),
                    f" | {m['step']} {m['error']}" if m.get('error') else '')

    # 2-5. per role: login -> enter -> novice -> eat / sell -> check, one window each
    logger.info('== 出村 + 腾背包: %d 个角色，同时最多 %d 个窗口 ==', len(roles), pipe.max_windows)
    own = OwnWindows(pipe.max_windows, logger)
    locks = {a.name: threading.Lock() for a in create.accounts}
    with ThreadPoolExecutor(max_workers=pipe.max_windows, thread_name_prefix='store') as pool:
        results = list(pool.map(lambda t: StoreRun(pipe, t[0], t[1], t[2], throttle, own, locks[t[0].name], run_id,
                                                   store_s, db_path).run(), roles))
    seconds = time.monotonic() - started
    stamp = log_path.stem.replace('store_', '')
    out = ROOT / 'logs' / f'store_summary_{stamp}.json'
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), 'utf-8')
    logger.info('=' * 60)
    for r in results:
        logger.info('%-10s %s 空格=%s/%s 吃=%s 卖=%s%s', r.get('role') or f"{r['account']}#{r['slot']}",
                    '就绪' if r['ok'] else '失败', r.get('free'), r.get('capacity'), r.get('eaten'), r.get('sold'),
                    f" | {r['step']} {r['error']}" if r.get('error') else '')
    ok = sum(r['ok'] for r in results)
    logger.info('完成 %d/%d，总用时 %.0fs，本工具残留窗口 %d。汇总: %s', ok, len(results), seconds, own.count(), out)
    return 0 if ok == len(results) and all(m['ok'] for m in made) else 1


if __name__ == '__main__':
    sys.exit(main())
