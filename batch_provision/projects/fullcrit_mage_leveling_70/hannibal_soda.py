"""Verified captain soda resupply at Hannibal in 荒芜之地一区 (map 180)."""
import _bootstrap  # noqa: F401

import math
import time

import pp_chain
import trial_run as t
from common import APPRENTICES
from lunhui15 import LEADER
from provisioner import log as plog, world as w

SODA_ID = 8456
TARGET = 15 * 99
TRIGGER = 599
HANNIBAL = 2508
MAP_ID = 180
SPOT = (1638, 939)
SHELF_SLOT = 5
ROLES = (LEADER,) + tuple(APPRENTICES)


def purchase_batches(current, target=TARGET, maximum=99):
    """Return conservative per-request quantities without exceeding target."""
    remaining = max(0, target - current)
    batches = []
    while remaining:
        quantity = min(maximum, remaining)
        batches.append(quantity)
        remaining -= quantity
    return batches


def count(c):
    return w.item_count(w.read_bag(c.mem) or (), SODA_ID)


def needs_restock(captain):
    return count(captain) < TRIGGER


def restock_at_home(roles=ROLES, target=TARGET):
    """Buy verified stacks up to target, returning the whole team to town afterward.

    Caller must first bring the team home and sell junk. Every purchase is verified against the live bag before
    another request is sent, so a delayed shop update cannot cause a duplicate buy.
    """
    captain = t.Client(LEADER)
    if captain.world().map_id != 1 or captain.world().in_battle:
        raise t.Stop(f'汉尼拔补汽水前要求队长在村内且不在战斗：{captain.world()}')
    before = count(captain)
    if before >= target:
        return before

    # The reviewed PP鸡 route uses the shared team's configured roles (leader + four apprentices).
    pp_chain.main('荒芜之地1区', ['平静海岸2区', '龙之都', '恶人山', '苦无沙漠3区'])
    states = {name: t.Client(name).world() for name in roles}
    wrong = {name: (s.map_id, round(s.x), round(s.y)) for name, s in states.items() if not s or s.map_id != MAP_ID}
    if wrong:
        raise t.Stop(f'PP鸡后队员未全部到荒芜之地一区，取消汽水购买：{wrong}')

    st = captain.world()
    if math.dist((st.x, st.y), SPOT) > 80:
        captain.game.navigate(MAP_ID, *SPOT)
        end = time.monotonic() + 120
        while time.monotonic() < end:
            st = captain.world()
            if st.map_id == MAP_ID and math.dist((st.x, st.y), SPOT) <= 80 and not st.nav_active:
                break
            time.sleep(0.25)
        else:
            raise t.Stop('队长未能走到汉尼拔，取消汽水购买')

    from factory.supply import Shop, ShopClient

    shop_data = Shop('汉尼拔', HANNIBAL, MAP_ID, SPOT, {SODA_ID: SHELF_SLOT}, 1, 2)
    plog.setup(t.HERE / 'logs', prefix='hannibal_soda')
    shop = ShopClient(captain.game, captain.mem, plog.for_account(LEADER))
    try:
        for quantity in purchase_batches(count(captain), target):
            if not shop.buy(shop_data, SHELF_SLOT, SODA_ID, quantity):
                raise t.Stop(f'汉尼拔汽水未到账：请求 {quantity}，当前 {count(captain)}；停止避免重复购买')
    finally:
        shop.close()

    final = count(captain)
    if final < target:
        raise t.Stop(f'汉尼拔汽水补给后核验不足：{final}/{target}')
    from line.ops import home_village
    home_village()
    for name in roles:
        state = t.Client(name).world()
        if not state or state.map_id not in (1, 8):
            raise t.Stop(f'{name} 汉尼拔补给后未全员回城：{state}')
    return final
