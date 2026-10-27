"""伏地魔1 leads the 5-man team through PP鸡 teleports, one after another, until a map named in TARGET is reached.

    python -X utf8 research/shitu/pp_chain.py [target word, default 通天塔] [via word ...]

At every PP鸡 (table below, AutoPath/NPCDirection.csv) the leader walks next to it, ClickNpc ->「传送服务」(if the
first menu has it) -> the option whose text holds the target word. Every menu seen is logged; when no option holds
the target word, the first `via` word found is taken instead (each via at most once); with none of them the run
stops and prints the options (no guessing). Live 2026-10-27 02:10: 逍遥村 PP鸡 11 offers only 平静海岸2区 / 自由市场. Members pay their own fee (190 to 81).
"""
import math
import sys
import time

import trial_run as t
from lunhui15 import LEADER, MEMBERS
from provisioner import world as w
from well10 import form_team

# + 20/40/50/152/172 from the old pp graph (D:/Codes/Gemini_Prj/smsm2_game/mwxqll_game/runtime/pp_runtime/data.json,
# 「complete server menus, verified landings」): 20 -> 81 279 40 50 300 210; 50 -> 20 172 300; 40 -> 20 152 300
PP = {1: (11, (342, 315)), 10: (12, (342, 1671)), 20: (586, (3954, 273)), 40: (15, (1607, 1897)), 50: (16, (265, 323)),
      81: (13, (1158, 779)), 152: (17, (3259, 287)), 172: (18, (1051, 350)), 279: (14, (227, 285)), 300: (26, (1902, 1071))}
NEAR = 80


def walk(c, map_id, xy, why):
    st = c.world()
    if st.map_id == map_id and math.dist((st.x, st.y), xy) <= NEAR:
        return
    t.say(f'[{c.name}] 走去{why} {xy}（距离 {math.dist((st.x, st.y), xy):.0f}）')
    c.game.navigate(map_id, *xy)
    last, last_t, end = None, time.monotonic(), time.monotonic() + 120
    while time.monotonic() < end:
        s = c.world()
        if s.map_id == map_id and math.dist((s.x, s.y), xy) <= NEAR and not s.moving:
            return
        p = (round(s.x), round(s.y))
        if s.in_battle or p != last:
            last, last_t = p, time.monotonic()
        elif time.monotonic() - last_t > 5:
            c.game.navigate(map_id, *xy)
            last_t = time.monotonic()
        time.sleep(0.2)
    raise t.Stop(f'{c.name} 没走到{why}')


def hop(lead, cs, target, via):
    st = lead.world()
    if st.map_id not in PP:
        raise t.Stop(f'地图 {st.map_id} 上没有已知的 PP鸡')
    npc, xy = PP[st.map_id]
    walk(lead, st.map_id, xy, f'PP鸡 {npc}')
    t.wait(lambda: all(math.dist(((s := c.world()).x, s.y), (lead.world().x, lead.world().y)) <= 250
                       for c in cs if c is not lead), 20, '队员跟上')
    lead.game.click_npc(npc)
    d = t.wait(lambda: lead.dialog(), 5, f'PP鸡 {npc} 菜单')
    t.say(f'[{lead.name}] PP鸡 {npc} 菜单: {[t.plain(l) for _, l in d.options]}')
    if any('传送服务' in t.plain(l) for _, l in d.options):
        opt = next(o for o, l in d.options if '传送服务' in t.plain(l))
        d = t.choose(lead, d, opt, '传送服务')
        t.say(f'[{lead.name}] 传送服务: {[t.plain(l) for _, l in d.options]}')
    hits = [(o, l) for o, l in d.options if target in t.plain(l)]
    for v in list(via):
        if hits:
            break
        hits = [(o, l) for o, l in d.options if v in t.plain(l)]
        if hits:
            via.remove(v)
            t.say(f'[{lead.name}] 菜单里没有「{target}」，先中转到「{v}」')
    if not hits:
        lead.game.select_dialog(0)
        raise t.Stop(f'PP鸡 {npc}（map {st.map_id}）的菜单里没有「{target}」，停下等指示')
    gold = {c.name: w.read_gold(c.mem) for c in cs}
    t.say(f'[{lead.name}] 选「{t.plain(hits[0][1])}」')
    lead.game.select_dialog(hits[0][0])
    t.wait(lambda: lead.world() and lead.world().map_id != st.map_id, 10, '传送')
    time.sleep(1.5)
    for c in cs:
        s = c.world()
        t.say(f'[{c.name}] map {s.map_id} ({s.x:.0f},{s.y:.0f}) 金币 {gold[c.name]} -> {w.read_gold(c.mem)}')


def main(target, via):
    cs = [t.Client(n) for n in (LEADER,) + MEMBERS]
    lead = cs[0]
    form_team(lead, cs[1:])
    for _ in range(4):
        st = lead.world()
        if target in MAP_NAMES.get(st.map_id, ''):
            t.say(f'到了 {MAP_NAMES[st.map_id]}（map {st.map_id}），队伍 {lead.team()}，停下等指示')
            return
        hop(lead, cs, target, via)
    raise t.Stop('传送 4 次还没到')


MAP_NAMES = {1: '逍遥村西区', 10: '乌龙村南区', 11: '乌龙村北区', 20: '龙之都外城', 40: '圣人谷', 50: '恶人山',
             152: '迷惑森林3区', 172: '苦无沙漠3区', 24: '龙之都内城', 25: '龙之都交叉口', 81: '平静海岸2区', 279: '通天塔路口',
             280: '通天塔一区', 300: '自由市场'}

if __name__ == '__main__':
    try:
        main(sys.argv[1] if len(sys.argv) > 1 else '通天塔', sys.argv[2:])
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
