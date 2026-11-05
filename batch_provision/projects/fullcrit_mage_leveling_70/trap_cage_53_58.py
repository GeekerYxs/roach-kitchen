"""Level the four apprentices in 陷阱囚牢 (map 1150) from 53 to 58.

Route: recall, sell and refill (home_supply) -> PP鸡 to 荒芜之地1区 (180) -> entrance NPC 10182 (2415,329) ->
patrol (4461,3656) <-> (4200,4000) until all four apprentices are 58 with no talent points left.
Only the 方士 captain uses 天之箭 354 lv7 and pet 烈焰爆发 1504; apprentices issue no battle commands.
Deaths follow the supervisor policy (team.toml max_falls; more when the captain carries the revive item),
and an empty captain soda bag stops the patrol out of battle for a restock.
"""
import _bootstrap  # noqa: F401
import os

import maze_train as m
import trial_run as t
from common import APPRENTICES
from provisioner import world as w

import guards
import home_supply

LEADER = os.environ['SHITU_LEADER']
ROLES = (LEADER,) + tuple(APPRENTICES)
DESERT_1, TRAP_CAGE = 180, 1150
ENTRANCE_NPC, ENTRANCE_XY = 10182, (2415, 329)
PATROL_A, PATROL_B = (4461, 3656), (4200, 4000)
TARGET_LEVEL = 58


def say(msg):
    t.say(f'[{LEADER}] {msg}')


def home_sell_and_report():
    """Recall, log what each role will sell and the gold it made, then refill."""
    import sell_tradable
    from line.ops import home_village

    home_village()
    items = sell_tradable.load_items()
    for name in ROLES:
        c = t.Client(name)
        if c.world().map_id not in home_supply.HOME_MAPS or c.world().in_battle:
            raise t.Stop(f'{name} 回城后状态不安全：{c.world()}')
        mode = home_supply.LEADER_SELL_MODE if name == LEADER else home_supply.APPRENTICE_SELL_MODE
        selected = [items[s.item_id].name for s in w.read_bag(c.mem) or ()
                    if s.item_id in items and items[s.item_id].tradable and
                    sell_tradable.wanted(items[s.item_id], mode)]
        say(f'[{name}] 待售物品（{len(selected)}格，模式 {mode}）：{selected}')
    before = {name: w.read_gold(t.Client(name).mem) for name in ROLES}
    home_supply.sell_all(ROLES)
    for name in ROLES:
        after = w.read_gold(t.Client(name).mem)
        say(f'[{name}] 本次卖物金币：{before[name]} -> {after}，增加 {after - before[name]}')
    home_supply.top_up_scrolls_at_home(ROLES)
    home_supply.top_up_master_sweets_at_home()
    home_supply.top_up_soda(ROLES)
    home_supply.report_revive_item()


def main():
    cs = {n: t.Client(n) for n in ROLES}
    lead = cs[LEADER]
    expected = {c.char_id for c in cs.values()}
    resume = all((s := c.world()) and s.map_id == TRAP_CAGE for c in cs.values()) and set(lead.team()) == expected
    if resume:
        say('完整队伍已在陷阱囚牢，原地续跑')
    else:
        home_sell_and_report()
        # The live PP menu is inspected at every hop; a menu that differs from the recorded graph stops pp_chain.
        home_supply.pp_go('荒芜之地1区', ['平静海岸2区', '龙之都', '恶人山', '苦无沙漠3区'])
        if lead.world().map_id != DESERT_1:
            raise t.Stop(f'PP鸡后未到荒芜之地1区 map {DESERT_1}，当前 map={lead.world().map_id}')
        m.CASTERS = (LEADER,)
        m.STAGES = (
            dict(name='进入陷阱囚牢', goal=(TRAP_CAGE, None), maze=None, until=None, patrol_b=None,
                 legs={DESERT_1: ('click', ENTRANCE_NPC, ENTRANCE_XY)}),
        )
        m.main()
        if lead.world().map_id != TRAP_CAGE:
            raise t.Stop(f'未进入陷阱囚牢：map={lead.world().map_id}')

    guards.configure_revive()
    m.CASTERS = (LEADER,)
    m.STAGES = (
        dict(name='陷阱囚牢巡逻', maze=TRAP_CAGE, until=TARGET_LEVEL,
             patrol_a=PATROL_A, patrol_b=PATROL_B, legs={}, done_when=guards.soda_guard),
    )
    say(f'开始陷阱囚牢巡逻：{PATROL_A} ↔ {PATROL_B}，目标四个小号 {TARGET_LEVEL} 级')
    m.main()


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
        try:
            lead = t.Client(LEADER)
            if lead.world().nav_active:
                lead.game.cancel_navigation()
        except Exception:
            pass
        say(f'停止：{exc}')
        raise SystemExit(1)
