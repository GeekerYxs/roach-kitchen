"""After the well: 伏地魔1 gives each apprentice 10 回城卷 + 50000 gold, everybody scrolls home, then 伏地魔1 leads the
five of them through PP鸡 to 平静海岸2区 (map 81) and stops there.

    python -X utf8 research/shitu/supply_go.py

User's order (2026-10-27). Restartable, every step decided from what is read:
  supply   per apprentice, two trades (factory gold-trade sequence, 0.5 s apart):
           items: 伏地魔1 invites -> apprentice accepts -> 伏地魔1 offers 0x63 <IqIII>(0,0,1,slot,10) -> confirm ->
                  apprentice offers gold 0 -> confirm; proof = apprentice's 回城卷 count +10
           gold:  same with 0x63 <IqI>(0,50000,0); proof = apprentice's gold +50000
           done trades go to state.json (supply_scroll / supply_gold), so a rerun does not give twice
  home     anybody not on map 1 and not on 81: leave the team, use a 回城卷
  trip     伏地魔1 invites the four (0x30), they accept; factory.transport.decide_trip walks to 传送操作员3号 (NPC 11),
           「传送服务」->「平静海岸2区」; every member pays its own 190 fee
No UI clicks.
"""
import math
import os
import time

import trial_run as t
from bai_shi import done, mark
from factory.phase import COAST_MAP, SCROLL_ITEM, VILLAGE_MAP
from factory.transport import Trip, decide_trip
from provisioner import world as w
from well10 import form_team

from common import APPRENTICES, MASTERS  # noqa: E402
MASTER = MASTERS[0]
OTHERS = APPRENTICES + MASTERS[1:]
SCROLLS, GOLD = int(os.environ.get('SHITU_SCROLLS', '10')), 50000   # round 3: 伏地魔1 had only 33
GAP = 0.5
TRADE_NEAR = 80


def scrolls(c):
    return w.item_count(w.read_bag(c.mem) or (), SCROLL_ITEM)


def trade(giver, taker, offer):
    """Six requests, each from the side that owns it (factory/gold.py trade_gold)."""
    steps = ((giver.game.trade_invite, (taker.char_id,)), (taker.game.trade_accept, (giver.char_id,)),
             offer, (giver.game.trade_confirm, ()),
             (taker.game.trade_offer_gold, (0,)), (taker.game.trade_confirm, ()))
    for i, (step, args) in enumerate(steps):
        if i:
            time.sleep(GAP)
        step(*args)


def calm(*cs):
    """A trade sent while either side is in a battle is lost (round 2, 03:32: a well encounter hit at the first trade)."""
    for c in cs:
        t.wait(lambda: not (s := c.world()).in_battle and not s.busy, 120, f'{c.name} 战斗结束')
    giver, taker = cs[0], cs[1]
    a, b = giver.world(), taker.world()
    if math.dist((a.x, a.y), (b.x, b.y)) > TRADE_NEAR:   # 0x46ff「玩家距离您太远」at 230 px (round 2, 03:32)
        if giver.team():                                  # a team member cannot walk on its own
            giver.game.team_leave()
            t.wait(lambda: not giver.team(), 5, f'{giver.name} 离队')
        t.say(f'[{giver.name}] 走到 {taker.name} 旁边 ({b.x:.0f},{b.y:.0f})')
        giver.game.navigate(b.map_id, round(b.x) + 30, round(b.y))
        t.wait(lambda: (s := giver.world()) and math.dist((s.x, s.y), (b.x, b.y)) <= TRADE_NEAR and not s.moving,
               30, f'{giver.name} 走到 {taker.name} 旁边')
    time.sleep(1)


def trade_until(giver, taker, offer, cond, what):
    for attempt in (1, 2):
        calm(giver, taker)
        trade(giver, taker, offer)
        try:
            return t.wait(cond, 8, what)
        except t.Stop:
            if attempt == 2:
                raise
            t.say(f'[{giver.name}] {what} 没到，等战斗结束后重试一次')


def supply(m, a):
    if not done(a.name, 'supply_scroll'):
        start = scrolls(a)
        while (got := scrolls(a) - start) < SCROLLS:     # round 3: several smaller stacks (伏地魔1: 14 + 19)
            slot = max((s for s in w.read_bag(m.mem) if s.item_id == SCROLL_ITEM), key=lambda s: s.quantity, default=None)
            if slot is None:
                raise t.Stop(f'{m.name} 没有回城卷了')
            k, before = min(slot.quantity, SCROLLS - got), scrolls(a)
            t.say(f'[{m.name}] 交易给 {a.name}：{k} 张回城卷（第 {slot.slot} 格，{slot.quantity} 张），{a.name} 现有 {before}')
            trade_until(m, a, (m.game.trade_offer_item, (slot.slot, k)),
                        lambda: scrolls(a) >= before + k, f'{a.name} 回城卷 +{k}')
        mark(a.name, 'supply_scroll', n=SCROLLS)
        t.say(f"[{a.name}] 回城卷 {start} -> {scrolls(a)}")
    if not done(a.name, 'supply_gold'):
        before = w.read_gold(a.mem)
        t.say(f'[{m.name}] 交易给 {a.name}：{GOLD} 金币，{a.name} 现有 {before}')
        trade_until(m, a, (m.game.trade_offer_gold, (GOLD,)),
                    lambda: w.read_gold(a.mem) >= before + GOLD, f'{a.name} 金币 +{GOLD}')
        mark(a.name, 'supply_gold', n=GOLD)
        t.say(f'[{a.name}] 金币 {before} -> {w.read_gold(a.mem)}')


def go_home(cs):
    away = [c for c in cs.values() if c.world().map_id not in (VILLAGE_MAP, COAST_MAP)]
    for c in away:
        if c.team():
            c.game.team_leave()
    for c in away:
        t.wait(lambda: not c.team(), 5, f'{c.name} 离队')
        st = c.world()
        t.wait(lambda: not (s := c.world()).in_battle and not s.busy, 120, f'{c.name} 战斗结束')
        slot = next((s.slot for s in w.read_bag(c.mem) if s.item_id == SCROLL_ITEM), None)
        if slot is None:
            raise t.Stop(f'{c.name} 没有回城卷（在地图 {st.map_id}）')
        t.say(f'[{c.name}] 用回城卷（第 {slot} 格），现在地图 {st.map_id}')
        c.game.use_item(slot)
        t.wait(lambda: c.world() and c.world().map_id != st.map_id, 10, f'{c.name} 回城卷生效')
        s = c.world()
        t.say(f'[{c.name}] 回城卷后到地图 {s.map_id} ({s.x:.0f},{s.y:.0f})')
        if s.map_id != VILLAGE_MAP:
            raise t.Stop(f'{c.name} 回城卷把它送到了地图 {s.map_id}，不是逍遥村西区；先停下')


def trip(m, cs):
    memo, last = Trip(), None
    while True:
        now = time.monotonic()
        st = m.world()
        memo.observe(st, now)
        d = decide_trip(st, [c.world() for c in cs.values() if c is not m], memo, now)
        if d.reason != last:
            t.say(f'[{m.name}] {d.reason}')
            last = d.reason
        if d.kind == 'fail':
            raise t.Stop(d.reason)
        if d.kind == 'arrived':
            return
        if d.kind == 'navigate':
            m.game.navigate(*d.arg)
        elif d.kind == 'cancel_nav':
            m.game.cancel_navigation()
        elif d.kind == 'click':
            m.game.click_npc(d.arg)
        elif d.kind in ('select', 'destination'):
            m.game.select_dialog(d.arg)
        if d.kind != 'wait':
            memo.record(d, st, now)
        time.sleep(0.15)


def main():
    cs = {n: t.Client(n) for n in (MASTER,) + OTHERS}
    m = cs[MASTER]
    for n, c in cs.items():
        s = c.world()
        t.say(f'[{n}] 等级 {w.read_level(c.mem)} 地图 {s.map_id} 金币 {w.read_gold(c.mem)} 回城卷 {scrolls(c)}')
    if all(c.world().map_id == COAST_MAP for c in cs.values()):
        t.say('5 个人都已在平静海岸2区')
        return
    for n in APPRENTICES:
        supply(m, cs[n])
    go_home(cs)
    form_team(m, [cs[n] for n in OTHERS])
    trip(m, cs)
    t.wait(lambda: all(c.world() and c.world().map_id == COAST_MAP for c in cs.values()), 15, '全员到平静海岸2区')
    for n, c in cs.items():
        s = c.world()
        t.say(f'[{n}] 地图 {s.map_id} ({s.x:.0f},{s.y:.0f}) 金币 {w.read_gold(c.mem)} 回城卷 {scrolls(c)}')
    t.say(f'全员到平静海岸2区，队伍 {m.team()}，等下一步')


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
