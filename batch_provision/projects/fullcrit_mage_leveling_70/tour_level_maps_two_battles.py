"""Tour the 11 user-directed level 1-70 maps, stopping after exactly two battles on each map.

The user explicitly asked to assume every apprentice is ready to change maps after two fights. This is a route
verification run, not a claim that two fights actually level a character to the next threshold. The four apprentices
remain silent; only the 方士 captain and its pet fight. A captain with zero 劲爆汽水 immediately breaks off and
returns the party to town.
"""
import _bootstrap  # noqa: F401
import math
import maze_train as m
import pp_chain
import trial_run as t
from common import APPRENTICES, MASTERS
from factory.phase import SCROLL_ITEM
from lunhui15 import LEADER
from provisioner import log as plog, world as w
import buy_scroll
import sell_tradable
import sys

SODA_ID, SWEET_ID = 8456, 8573
ROLES = (LEADER,) + APPRENTICES
TOWN, FREE_MARKET = 1, 300


def say(msg):
    t.say(f'[{LEADER}] {msg}')


def count(c, item_id):
    return w.item_count(w.read_bag(c.mem) or (), item_id)


class SodaGuardCaster(m.Caster):
    def tick(self, now):
        if self.c.name == LEADER and count(self.c, SODA_ID) == 0:
            raise t.Stop('队长劲爆汽水为0，立即结束巡逻并全队回城')
        return super().tick(now)


def top_up_scrolls_at_home():
    from zhuanzhi_finish import gate

    for name in ROLES:
        c = t.Client(name)
        total = buy_scroll.count(c)
        stacks = [(s.slot, s.quantity) for s in w.read_bag(c.mem) or ()
                  if s.item_id == SCROLL_ITEM]
        say(f'[{name}] 回城券总数 {total}，各格 {stacks}')
        if total < 20:
            if c.world().map_id != TOWN:
                raise t.Stop(f'{name} 不在村里，不能执行回城券补给：map={c.world().map_id}')
            gate(c, 10213, (1338, 1053), TOWN, '自由市场', FREE_MARKET)
            buy_scroll.buy(c, 50)
            gate(c, 24, (1781, 1268), FREE_MARKET, '逍遥村西区', TOWN)
            total = buy_scroll.count(c)
            if total < 50:
                raise t.Stop(f'{name} 回城券补给核验失败：总数 {total}')
            say(f'[{name}] 回城券已补到总数 {total}')


def top_up_master_sweets_at_home():
    c = t.Client(LEADER)
    total = count(c, SWEET_ID)
    say(f'队长甜点总数 {total}')
    if total >= 250:
        return
    if c.world().map_id != TOWN:
        raise t.Stop(f'队长甜点少于250但未回村：map={c.world().map_id}')
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
        need = 5 * 99 - total
        while need > 0:
            qty = min(99, need)
            if not shop.buy(PETSHOP, PETSHOP.shelf[SWEET_ID], SWEET_ID, qty):
                raise t.Stop(f'队长甜点购买未到账：请求 {qty}，当前总数 {count(c, SWEET_ID)}')
            need -= qty
    finally:
        shop.close()
    say(f'队长甜点补给后总数 {count(c, SWEET_ID)}')


def home_between_maps():
    from line.ops import home_village

    home_village()
    top_up_scrolls_at_home()
    top_up_master_sweets_at_home()
    soda = count(t.Client(LEADER), SODA_ID)
    say(f'回城检查：队长劲爆汽水 {soda}（低于599时前往汉尼拔补至1485）')
    if soda < 599:
        from hannibal_soda import restock_at_home
        soda = restock_at_home(ROLES)
        say(f'汉尼拔购买并回城核验：队长劲爆汽水 {soda}')


def install_stage(name, maze, legs, patrol_a=None, patrol_b=None):
    m.CASTERS = (LEADER,)
    m.Caster = SodaGuardCaster
    m.STAGES = (dict(name=name, maze=maze, until=None, patrol_a=patrol_a,
                     patrol_b=patrol_b, legs=legs, battle_limit=2,
                     done_when=lambda: count(t.Client(LEADER), SODA_ID) == 0),)
    say(f'前往 {name}（map {maze}），完成两场即切图')
    m.main()


def run_stage(name, maze, legs, patrol_a=None, patrol_b=None, pp=None, via=()):
    if pp:
        pp_chain.main(pp, list(via))
    install_stage(name, maze, legs, patrol_a, patrol_b)


def run_prison():
    import ruin_east_to_prison as prison

    cs = {n: t.Client(n) for n in ROLES}
    prison.home_and_fly(cs)
    install_stage('惊魂监狱', 264,
                  {24: ('click', 1339, (5660, 3258))},
                  (2369, 2000), (1000, 2900))


def route_stages():
    """The user-directed no-task leveling route; thresholds are targets, not two-fight guarantees."""
    return [
        ("阴森古井", 651, {1: ('walk', 130, (2544, 2904)), 130: ('click', 10152, (2596, 2880))}, (2214, 1653), (1000, 260), None, ()),
        ("轮回之城", 555, {81: ('click', 10158, (1635, 3041))}, (2754, 291), (2550, 616), '平静海岸2区', ()),
        ("暗影迷城", 600, {81: ('walk', 82, (1724, 2489)), 82: ('click', 10160, (1724, 2489))}, (786, 771), (1136, 771), '平静海岸2区', ()),
        ("八阵图", 700, {81: ('walk', 82, (1724, 2489)), 82: ('walk', 140, (831, 2257)), 140: ('click', 10164, (831, 2257))}, None, (1200, 1800), '平静海岸2区', ()),
        ("遗忘洞穴", 750, {20: ('walk', 141, (3410, 252)), 141: ('click', 10166, (3410, 252))}, (1590, 3369), (1946, 2430), '龙之都', ()),
        ("通天塔一区", 280, {279: ('click', 952, (935, 290), '一区')}, (414, 4893), (106, 4467), '通天塔', ('平静海岸2区',)),
        ("通天塔二区", 281, {279: ('click', 952, (935, 290), '二区')}, (600, 500), (1200, 400), '通天塔', ('平静海岸2区',)),
        ("巨石之城东部遗址", 1100, {172: ('click', 10180, (642, 1180))}, (8562, 2943), (3300, 600), '苦无沙漠3区', ('平静海岸2区', '龙之都', '恶人山')),
        ("惊魂监狱", 264, {24: ('click', 1339, (5660, 3258))}, (2369, 2000), (1000, 2900), None, ()),
        ("陷阱囚牢", 1150, {180: ('click', 10182, (2415, 329))}, (4722, 3723), (4200, 4000), '荒芜之地1区', ('平静海岸2区', '龙之都', '恶人山', '苦无沙漠3区')),
        ("禁锢之地", 1200, {180: ('walk', 180, (4120, 2600)), 181: ('click', 10184, (3123, 2630))}, (8898, 5985), (8500, 5750), '荒芜之地1区', ('平静海岸2区', '龙之都', '恶人山', '苦无沙漠3区')),
    ]


def run_route(first_stage=1):
    if len(APPRENTICES) != 4 or len(MASTERS) != 1:
        raise t.Stop('这条路线要求曾经不曾带四个元素使')
    if first_stage < 1 or first_stage > 11:
        raise t.Stop(f'续跑起始图编号超界: {first_stage}（合法范围 1..11）')
    for index, (name, maze, legs, a, b, pp, via) in enumerate(route_stages(), start=1):
        if index < first_stage:
            continue
        if name == '惊魂监狱':
            run_prison()
        else:
            run_stage(name, maze, legs, a, b, pp=pp, via=via)
        if index != 11:
            home_between_maps()


def main():
    first_stage = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    home_between_maps()
    run_route(first_stage)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        try:
            lead = t.Client(LEADER)
            if lead.world().nav_active:
                lead.game.cancel_navigation()
        except Exception:
            pass
        say('收到停止指令，已取消队长寻路')
    except t.Stop as exc:
        lead = t.Client(LEADER)
        if lead.world().nav_active:
            lead.game.cancel_navigation()
        say(f'停止：{exc}')
        if count(lead, SODA_ID) == 0 and any(t.Client(n).world().map_id not in (1, 8) for n in ROLES):
            from line.ops import home_village
            home_village()
        raise SystemExit(1)
