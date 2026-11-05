"""One home routine for every stage: recall, sell, top up scrolls / pet sweets / captain soda.

Previously copied into five scripts with small differences (the captain's worn white gear was unequipped and sold,
one copy did not check soda, one did not handle a role standing outside map 1). Every stage now calls this.
"""
import _bootstrap  # noqa: F401
import math
import os

import trial_run as t
from common import APPRENTICES
from factory.phase import SCROLL_ITEM
from provisioner import log as plog, world as w
import buy_scroll

from guards import LEADER, SODA_ID, SWEET_ID, count

ROLES = (LEADER,) + tuple(APPRENTICES)
TOWN, FREE_MARKET = 1, 300
HOME_MAPS = (1, 8)
SCROLL_LOW, SCROLL_FULL = 20, 50
SWEET_LOW, SWEET_FULL = 250, 5 * 99
SODA_TRIGGER = 599
LEADER_SELL_MODE = 'stones'               # 杂物 / 残骸 / 技能石 / 图纸 / 配方; never equipment
APPRENTICE_SELL_MODE = 'junk-stones-white'
CITY_FEE, FEE_GIFT = 40000, 60000


def say(msg):
    t.say(f'[{LEADER}] {msg}')


def sell_all(roles=ROLES):
    """Captain sells junk and skill stones only; apprentices also sell white gear and gourds.

    Whether worn white gear is taken off first is team.toml `sell_worn_white` (default off: low-level apprentices
    would otherwise fight the next map without armour)."""
    import sell_tradable

    roles = tuple(roles)
    if LEADER in roles:
        sell_tradable.main([LEADER], LEADER_SELL_MODE)
    others = [n for n in roles if n != LEADER]
    if others:
        sell_tradable.main(others, APPRENTICE_SELL_MODE)


def top_up_scrolls_at_home(roles=ROLES):
    """Total 回城卷 over all bag slots; below 20 buy up to 50 at 铁公鸡 in the free market."""
    from zhuanzhi_finish import gate

    for name in roles:
        c = t.Client(name)
        total = buy_scroll.count(c)
        stacks = [(s.slot, s.quantity) for s in w.read_bag(c.mem) or () if s.item_id == SCROLL_ITEM]
        say(f'[{name}] 回城券总数 {total}，各格 {stacks}')
        if total >= SCROLL_LOW:
            continue
        st = c.world()
        if st.map_id not in (TOWN, FREE_MARKET):
            raise t.Stop(f'{name} 不在逍遥村西区/自由市场，不能执行回城券补给：map={st.map_id}')
        if st.map_id == TOWN:
            gate(c, 10213, (1338, 1053), TOWN, '自由市场', FREE_MARKET)
        buy_scroll.buy(c, SCROLL_FULL)
        gate(c, 24, (1781, 1268), FREE_MARKET, '逍遥村西区', TOWN)
        total = buy_scroll.count(c)
        if total < SCROLL_FULL:
            raise t.Stop(f'{name} 回城券补给核验失败：总数 {total}')
        say(f'[{name}] 回城券已补到总数 {total}')


def top_up_master_sweets_at_home():
    c = t.Client(LEADER)
    total = count(c, SWEET_ID)
    say(f'队长甜点总数 {total}')
    if total >= SWEET_LOW:
        return total
    if c.world().map_id != TOWN:
        raise t.Stop(f'队长甜点少于{SWEET_LOW}但未在逍遥村西区：map={c.world().map_id}')
    from factory.supply import PETSHOP, ShopClient

    # Buying scrolls can leave the captain at the village return point (1110,1173),
    # outside the pet shop's 120-unit interaction range.
    st = c.world()
    if math.dist((st.x, st.y), PETSHOP.spot) > 120:
        c.game.navigate(TOWN, *PETSHOP.spot)
        t.wait(lambda: (s := c.world()) and s.map_id == TOWN and
               math.dist((s.x, s.y), PETSHOP.spot) <= 120 and not s.nav_active,
               120, '队长到宠物商人小美附近')

    plog.setup(t.HERE / 'logs', prefix='tour_supply')
    shop = ShopClient(c.game, c.mem, plog.for_account(LEADER))
    try:
        need = SWEET_FULL - total
        while need > 0:
            qty = min(99, need)
            if not shop.buy(PETSHOP, PETSHOP.shelf[SWEET_ID], SWEET_ID, qty):
                raise t.Stop(f'队长甜点购买未到账：请求 {qty}，当前总数 {count(c, SWEET_ID)}')
            need -= qty
    finally:
        shop.close()
    total = count(c, SWEET_ID)
    say(f'队长甜点补给后总数 {total}')
    return total


def top_up_soda(roles=ROLES):
    soda = count(t.Client(LEADER), SODA_ID)
    say(f'回城检查：队长劲爆汽水 {soda}（低于{SODA_TRIGGER}时前往汉尼拔补至1485）')
    if soda < SODA_TRIGGER:
        from hannibal_soda import restock_at_home
        soda = restock_at_home(tuple(roles))
        say(f'汉尼拔购买并回城核验：队长劲爆汽水 {soda}')
    return soda


def report_revive_item():
    item = int(os.environ.get('SHITU_REVIVE_CANDIDATE', '0') or 0)
    if item:
        say(f'队长复活道具 {item} 剩余 {count(t.Client(LEADER), item)}（为0时倒地小号不能被复活）')


def home_and_restock(roles=ROLES):
    """Recall everybody, sell, and refill. Leaves the team in the village, not grouped."""
    from line.ops import home_village

    home_village()
    for name in roles:
        st = t.Client(name).world()
        if not st or st.map_id not in HOME_MAPS or st.in_battle:
            raise t.Stop(f'{name} 回城后状态不安全：{st}')
    sell_all(roles)
    top_up_scrolls_at_home(roles)
    top_up_master_sweets_at_home()
    top_up_soda(roles)
    report_revive_item()


def fund_city_fee(lead, c, fee=CITY_FEE, gift=FEE_GIFT):
    """An apprentice without the 龙之都公民 status pays 铁男 itself; give it 60,000 from the captain first when it
    cannot. Both must stand in the same village map, out of a team; the trade is verified on the receiver's gold."""
    gold = w.read_gold(c.mem)
    if gold >= fee:
        return gold
    from supply_go import trade_until

    if lead.world().map_id != c.world().map_id:
        raise t.Stop(f'{c.name} 金币 {gold} 不足 {fee}，队长不在同一地图无法转账')
    if w.read_gold(lead.mem) < gift + fee:
        raise t.Stop(f'队长金币不足，不能给 {c.name} 转 {gift}')
    for x in (lead, c):
        if x.team():
            x.game.team_leave()
            t.wait(lambda: not x.team(), 5, f'{x.name} 离队后转账')
    before = gold
    trade_until(lead, c, (lead.game.trade_offer_gold, (gift,)),
                lambda: w.read_gold(c.mem) >= before + gift, f'{c.name} 收到队长 {gift} 金币')
    say(f'{c.name} 入城费不足，队长转账 {gift}：{before} -> {w.read_gold(c.mem)}')
    return w.read_gold(c.mem)


def pp_go(target, via):
    """pp_chain.main, but accept the run when its last allowed hop already landed on the target."""
    import pp_chain

    lead = t.Client(LEADER)
    try:
        pp_chain.main(target, list(via))
    except t.Stop:
        if target not in pp_chain.MAP_NAMES.get(lead.world().map_id, ''):
            raise
        say(f'PP鸡最后一跳已到 {target}，继续')
