"""Send the existing apprentice team to map 1150 and test the 53-58 patrol route.

This can be started at a lower level for a user-requested route test. Apprentices stay silent in combat;
only the 方士 captain uses 天之箭 354 lv7 and pet 烈焰爆发 1504. Deaths are tolerated for this test.
"""
import _bootstrap  # noqa: F401
import os

import maze_train as m
import pp_chain
import trial_run as t
from common import APPRENTICES, MASTERS
from lunhui15 import LEADER
from provisioner import world as w
import sell_tradable
import buy_scroll

DESERT_1, TRAP_CAGE = 180, 1150
ENTRANCE_NPC, ENTRANCE_XY = 10182, (2415, 329)
PATROL_A, PATROL_B = (4722, 3723), (4200, 4000)
TARGET_LEVEL = 58


def say(msg):
    t.say(f'[{LEADER}] {msg}')


def home_sell_and_report():
    from line.ops import home_village

    home_village()
    items = sell_tradable.load_items()
    mode = 'junk-stones-white'
    for name in APPRENTICES:
        c = t.Client(name)
        if c.world().map_id not in (1, 8) or c.world().in_battle:
            raise t.Stop(f'{name} 回城后状态不安全：{c.world()}')
        bag = w.read_bag(c.mem) or ()
        selected = [items[s.item_id].name for s in bag
                    if s.item_id in items and items[s.item_id].tradable and
                    sell_tradable.wanted(items[s.item_id], mode)]
        say(f'[{name}] 待售物品（{len(selected)}格）：{selected}')
    before = {name: w.read_gold(t.Client(name).mem) for name in APPRENTICES}
    sell_tradable.main(APPRENTICES, mode)
    for name in APPRENTICES:
        after = w.read_gold(t.Client(name).mem)
        say(f'[{name}] 本次卖物金币：{before[name]} -> {after}，增加 {after - before[name]}')


def restock_scrolls():
    from zhuanzhi_finish import gate

    names = (LEADER,) + APPRENTICES
    for name in names:
        c = t.Client(name)
        bag = w.read_bag(c.mem) or ()
        stacks = [(s.slot, s.quantity) for s in bag if s.item_id == buy_scroll.SCROLL_ITEM]
        total = buy_scroll.count(c)
        say(f'[{name}] 回城券各格 {stacks}，合计 {total}')
        if total < 20:
            say(f'[{name}] 合计少于20，补到50（按全部格子累计）')
            if c.world().map_id == 1:
                gate(c, 10213, (1338, 1053), 1, '自由市场', 300)
            buy_scroll.buy(c, 50)
            if c.world().map_id == 300:
                gate(c, 24, (1781, 1268), 300, '逍遥村西区', 1)
        final = buy_scroll.count(c)
        if total < 20 and final < 50:
            raise t.Stop(f'{name} 回城券补给后只有 {final}，未达到50')
        final_stacks = [(s.slot, s.quantity) for s in w.read_bag(c.mem) or ()
                        if s.item_id == buy_scroll.SCROLL_ITEM]
        say(f'[{name}] 回城券补给核验：各格 {final_stacks}，合计 {final}')


def main():
    os.environ.setdefault('SHITU_PLAYER_SKILL', '354')
    os.environ.setdefault('SHITU_PLAYER_SKILL_LEVEL', '7')
    restock_scrolls()
    home_sell_and_report()

    # User specified the PP鸡 route to 荒芜沙漠一区. The live menu is inspected at every hop;
    # if the server menu differs from the recorded graph, pp_chain stops and prints the options.
    pp_chain.main('荒芜之地1区', ['平静海岸2区', '龙之都', '恶人山', '苦无沙漠3区'])
    lead = t.Client(LEADER)
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

    m.STAGES = (
        dict(name='陷阱囚牢巡逻', maze=TRAP_CAGE, until=TARGET_LEVEL,
             patrol_a=PATROL_A, patrol_b=PATROL_B, legs={}),
    )
    say(f'开始陷阱囚牢测试巡逻：{PATROL_A} ↔ {PATROL_B}，目标四个小号 {TARGET_LEVEL} 级；允许测试中倒地')
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
        lead = t.Client(LEADER)
        if lead.world().nav_active:
            lead.game.cancel_navigation()
        say(f'停止：{exc}')
        raise SystemExit(1)
