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
