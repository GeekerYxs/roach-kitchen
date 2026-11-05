"""The master's supply before every apprentice batch: 蓝 / 血 / 宠物忠诚 / 回城卷, one rule for the 勇者 and 元素使 lines.

Design and live facts: SUPPLY_DESIGN.md §4.0 (user 2026-11-05). Stage 1 = the pure decision only (plan / fit);
the trip (翠花 in 龙之都外城, then 小美 in the village) comes in stage 3.

User 2026-11-05 quota, counted in restore points (data/potions.csv), so a borrowed master's other potions count too:
    mp    15 x 99 x 310 = 460350   (健康果汁 8454)
    hp     3 x 99 x 310 =  92070   (心情便当 8404)
    loyal  4 x 99 x 150 =  59400   (甜点 8573)
    回城卷  <= 30 -> 100
Prices / shelves measured live 2026-11-05 with 自由三号: 翠花 NPC 554 shelf 2 心情便当 50, 5 健康果汁 50, 8 回城卷 100;
小美 甜点 240. No "keep 15 free slots" any more (user: the bag is 40 slots, the supply alone takes 24).
"""
import csv
import math
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
POTIONS = HERE / 'data' / 'potions.csv'
LINE_TOML = HERE / 'line' / 'line.toml'

SCROLL = 9801
BUY = {'mp': 8454, 'hp': 8404, 'loyal': 8573}                 # what a short master buys of each kind
PRICE = {8454: 50, 8404: 50, 8573: 240, SCROLL: 100}           # live 2026-11-05
STACK = {SCROLL: 50}                                           # every other potion stacks to 99
QUOTA = {'mp': 460350, 'hp': 92070, 'loyal': 59400, 'scroll_low': 30, 'scroll_full': 100}
TRIM = (BUY['mp'], BUY['hp'], BUY['loyal'], SCROLL)           # bag too full: cut 健康果汁 first, 回城卷 last


def load_potions(path=POTIONS):
    """{item_id: (kind, points)} from data/potions.csv."""
    with Path(path).open(encoding='utf-8', newline='') as f:
        return {int(r['item_id']): (r['kind'], int(r['points'])) for r in csv.DictReader(f)}


def load_quota(path=LINE_TOML):
    """QUOTA with line.toml [supply] laid over it."""
    q = dict(QUOTA)
    if Path(path).exists():
        q.update(tomllib.loads(Path(path).read_text(encoding='utf-8')).get('supply', {}))
    return q


def points(bag, potions):
    """Restore points in the bag per kind: {'hp': .., 'mp': .., 'loyal': ..}."""
    have = {k: 0 for k in BUY}
    for s in bag:
        kind, value = potions.get(s.item_id, (None, 0))
        if kind in have:
            have[kind] += s.quantity * value
    return have


def stacks(bag, item, qty):
    """New bag slots that qty more of item takes, partial stacks filled first."""
    size = STACK.get(item, 99)
    room = sum(size - s.quantity for s in bag if s.item_id == item and s.quantity < size)
    return math.ceil(max(0, qty - room) / size)


@dataclass
class Plan:
    have: dict                                  # restore points per kind before buying
    scrolls: int
    buys: dict = field(default_factory=dict)    # item -> qty, in trip order
    cost: int = 0
    slots: int = 0                              # new bag slots the buys take
    free: int = 0
    warnings: list = field(default_factory=list)

    @property
    def short_slots(self):
        return max(0, self.slots - self.free)


def _total(p, bag):
    p.cost = sum(PRICE[i] * n for i, n in p.buys.items())
    p.slots = sum(stacks(bag, i, n) for i, n in p.buys.items())
    return p


def plan(bag, capacity, potions, quota=QUOTA):
    """What this master has to buy to reach the quota. bag: slots with .item_id / .quantity."""
    have = points(bag, potions)
    scrolls = sum(s.quantity for s in bag if s.item_id == SCROLL)
    p = Plan(have, scrolls, free=capacity - len(bag))
    if scrolls <= quota['scroll_low']:
        p.buys[SCROLL] = quota['scroll_full'] - scrolls          # bought first at 翠花: the way home needs one
    for kind in ('mp', 'hp', 'loyal'):
        short = quota[kind] - have[kind]
        if short > 0:
            item = BUY[kind]
            p.buys[item] = math.ceil(short / potions[item][1])
    return _total(p, bag)


def fit(p, bag, free):
    """The plan cut down to `free` new slots (after the drops are sold / dropped), 健康果汁 first; warns per cut."""
    q = Plan(p.have, p.scrolls, dict(p.buys), free=free, warnings=list(p.warnings))
    _total(q, bag)
    for item in TRIM:
        while q.slots > free and q.buys.get(item, 0) > 0:
            size = STACK.get(item, 99)
            n = q.buys[item]
            q.buys[item] = n - (n % size or size)                 # one stack less (the odd part first)
            _total(q, bag)
        if q.buys.get(item) != p.buys.get(item):
            q.warnings.append(f'背包格不够：{item} 只买 {q.buys.get(item, 0)}（要 {p.buys[item]}）')
        if q.buys.get(item) == 0:
            del q.buys[item]
    return q


def gold_problem(p, gold):
    """None, or the error text when the master cannot pay the plan (user 2026-11-05: stop at start)."""
    if gold < p.cost:
        return f'师傅金币 {gold} 不够补给（要 {p.cost}）'
    return None


# ---- stage 3: the trip (user 2026-11-05, routes and shelves live-tested with 自由三号 the same day) -----------------

CUIHUA = dict(npc=554, map_id=20, spot=(4360, 540), shelf={SCROLL: 8, 8454: 5, 8404: 2})   # 龙之都外城
VILLAGE, CUIHUA_VIA = 1, ['平静海岸2区']      # 逍遥村 PP鸡 -> 平静海岸2区 (190) -> 龙之都 (690)
BATCH_MAX = 99                                # per shop request; 回城卷 per its 50 stack


def chunks(item, qty):
    size = min(BATCH_MAX, STACK.get(item, 99))
    while qty > 0:
        yield min(size, qty)
        qty -= size


def summary(p):
    return (f'蓝 {p.have["mp"]:,} / 血 {p.have["hp"]:,} / 忠诚 {p.have["loyal"]:,} / 回城卷 {p.scrolls}；'
            f'要买 {p.buys or "无"}，约 {p.cost:,} 金币，新占 {p.slots} 格（空 {p.free} 格）')


def ensure(name):
    """Top the master up to the quota before a batch: one trip 翠花 (龙之都外城) -> 回城卷 home -> 小美. -> final Plan."""
    import logging
    import time

    import master_bag
    import trial_run as t
    from factory.supply import PETSHOP, Shop, ShopClient
    from pp_chain import hop, walk
    from provisioner import world as w
    from quanshou import scroll

    c = t.Client(name)
    potions, quota = load_potions(), load_quota()

    def now():
        bag = w.read_bag(c.mem)
        return bag, plan(bag, w.read_bag_capacity(c.mem), potions, quota)

    bag, p = now()
    t.say(f'[{name}] 补给检查：{summary(p)}')
    if not p.buys:
        return p
    err = gold_problem(p, w.read_gold(c.mem))
    if err:
        raise t.Stop(err)                       # user 2026-11-05: short of gold -> stop at the start
    if c.dialog():
        c.game.select_dialog(0)
        time.sleep(0.5)
    if c.world().map_id != VILLAGE:
        scroll(c)
    if p.short_slots:
        t.say(f'[{name}] 报警：背包空 {p.free} 格，补给要 {p.slots} 格；先卖 / 丢地图掉落')
        master_bag.clean(name)
        bag, p = now()
    if p.short_slots:
        p = fit(p, bag, p.free)
        for msg in p.warnings:
            t.say(f'[{name}] 报警：{msg}')
    shop = ShopClient(c.game, c.mem, logging.getLogger(f'supply.{name}'))
    cui = {i: n for i, n in p.buys.items() if i in CUIHUA['shelf']}
    if cui:
        for _ in range(4):
            if c.world().map_id == CUIHUA['map_id']:
                break
            hop(c, [c], '龙之都', list(CUIHUA_VIA))
        walk(c, CUIHUA['map_id'], CUIHUA['spot'], '补给商翠花')
        cuihua = Shop('补给商翠花', CUIHUA['npc'], CUIHUA['map_id'], CUIHUA['spot'], CUIHUA['shelf'], 1, 2)
        try:
            for item, qty in cui.items():
                for n in chunks(item, qty):
                    if not shop.buy(cuihua, CUIHUA['shelf'][item], item, n):
                        raise t.Stop(f'{name} 翠花 {item} ×{n} 没到账，停下以免重复买')
        finally:
            shop.close()
    if c.world().map_id != VILLAGE:
        scroll(c)
    pet = p.buys.get(BUY['loyal'], 0)
    if pet:
        walk(c, VILLAGE, PETSHOP.spot, '宠物商人小美')
        try:
            for n in chunks(BUY['loyal'], pet):
                if not shop.buy(PETSHOP, PETSHOP.shelf[BUY['loyal']], BUY['loyal'], n):
                    raise t.Stop(f'{name} 小美 甜点 ×{n} 没到账，停下以免重复买')
        finally:
            shop.close()
    bag, done = now()
    t.say(f'[{name}] 补给完成：{summary(done)}；金币 {w.read_gold(c.mem):,}')
    if done.buys:
        t.say(f'[{name}] 报警：补给后仍不够额定值 {done.buys}')
    return done
