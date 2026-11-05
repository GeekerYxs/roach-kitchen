"""Pure decisions of the 1-70 line (line70.py): when the whole team goes home, what each role buys or sells there,
what a missing team member means. No game access here: tests/test_line70_policy.py pins every rule.

User rules (2026-11-05):
  - any role's bag is (nearly) full -> all five go home and sell once, so drops always have room
  - 回城卷 below 20 -> buy up to 50, everybody at the same trip home (scrolls are only spent by trips home, so the
    check runs at every trip, whatever caused it)
  - the leader keeps its own drinks (劲爆汽水 = player mp and pet mp, the server drinks them by itself) and the pet's
    甜点 (loyalty); 0 汽水 = go home at once (README), below 599 = buy up to 1485 at 汉尼拔 (map 180)
  - an apprentice died (sent to the village), has no scroll, or dropped offline -> everybody home, relog who is
    offline, regroup in the village, then back to the same map (user rule 2026-11-02: "if teleported home, whole
    team scrolls home, regroups at spawn, continues")
"""
from dataclasses import dataclass, field

SCROLL, SODA, SWEET, BENTO = 9801, 8456, 8573, 8406     # 回城卷, 劲爆汽水, 甜点, 怀旧便当
VILLAGE = (1, 8)


@dataclass(frozen=True)
class Rules:
    scroll_low: int = 20          # below this at a trip home -> buy
    scroll_full: int = 50
    scroll_leave: int = 3         # never walk out of the village with fewer (one to come back + spare)
    bag_free_min: int = 3         # fewer free slots than this in the field -> everybody home to sell
    bag_free_home: int = 10       # at home anyway: sell when fewer free slots than this
    soda_field: int = 100         # leader drinks below this in the field -> home (README: 0 = home at once)
    soda_low: int = 599           # at a trip home: below this -> 汉尼拔, up to soda_full
    soda_full: int = 1485         # 15 x 99
    sweet_field: int = 50
    sweet_low: int = 250          # at a trip home: below this -> 小美, up to sweet_full
    sweet_full: int = 495         # 5 x 99
    bento_low: int = 50           # leader HP food: only bought when 汉尼拔's shelf is known
    bento_full: int = 198


@dataclass(frozen=True)
class RoleView:
    """What the policy needs to know about one role, read by the caller."""
    name: str
    online: bool = True
    map_id: int = 0
    in_team: bool = True
    free_slots: int = 40
    sellable_slots: int = 0       # tradable slots its sell mode would sell
    counts: dict = field(default_factory=dict)    # item id -> total quantity over all bag slots


def total(view, item):
    return int(view.counts.get(item, 0))


def field_trip(leader, apprentices, rules=Rules()):
    """In the field, out of battle: -> reason (str) to take the whole team home now, or None.
    A full bag only counts when there is something to sell (a bag full of 不可交易 items cannot be emptied: that
    would send the team home after every battle)."""
    roles = (leader,) + tuple(apprentices)
    off = [r.name for r in roles if not r.online]
    if off:
        return f'掉线: {off}'
    gone = [r.name for r in roles[1:] if r.map_id in VILLAGE and r.map_id != leader.map_id]
    if gone:
        return f'回了村（阵亡被送回）: {gone}'
    out = [r.name for r in roles[1:] if not r.in_team]
    if out:
        return f'不在队里: {out}'
    full = [r.name for r in roles if r.free_slots < rules.bag_free_min and r.sellable_slots > 0]
    if full:
        return f'背包满: {full}'
    if total(leader, SODA) < rules.soda_field:
        return f'队长劲爆汽水只剩 {total(leader, SODA)}'
    if total(leader, SWEET) < rules.sweet_field:
        return f'队长甜点只剩 {total(leader, SWEET)}'
    return None


def bag_warnings(roles, rules=Rules()):
    """Roles whose bag is full of things that cannot be sold (drops get lost; the caller logs it once)."""
    return [r.name for r in roles if r.free_slots < rules.bag_free_min and r.sellable_slots == 0]


@dataclass(frozen=True)
class HomeJob:
    sell: bool = False
    scrolls_to: int = 0           # 0 = enough
    sweets_to: int = 0
    soda_to: int = 0
    bento_to: int = 0


def home_job(view, is_leader, rules=Rules()):
    """What one role does at a trip home (all roles do theirs at the same time)."""
    sell = view.free_slots < rules.bag_free_home and view.sellable_slots > 0
    scrolls = rules.scroll_full if total(view, SCROLL) < rules.scroll_low else 0
    if not is_leader:
        return HomeJob(sell, scrolls)
    sweets = rules.sweet_full if total(view, SWEET) < rules.sweet_low else 0
    soda = rules.soda_full if total(view, SODA) < rules.soda_low else 0
    bento = rules.bento_full if soda and total(view, BENTO) < rules.bento_low else 0   # same shop, same trip
    return HomeJob(sell, scrolls, sweets, soda, bento)


def can_leave(views, rules=Rules()):
    """-> [names] that must not leave the village yet (too few scrolls to come back)."""
    return [v.name for v in views if total(v, SCROLL) < rules.scroll_leave]


def first_stage(levels, untils):
    """Index of the first stage whose target is not reached by every apprentice (len(untils) = all done)."""
    low = min(levels)
    return next((i for i, u in enumerate(untils) if low < u), len(untils))


def stop_after(fails, limit=3):
    """The same stage failed this many times in a row -> stop for a human instead of looping."""
    return fails >= limit
