"""Free portal 逍遥村西区 (1) <-> 自由市场 (300), user round 3 16:2x: test it N round trips with one role.

    python -X utf8 research/shitu/portal_test.py ROLE N

Map 1: gate NPC 10213 (1338,1053), 100 px north of the 回城卷 landing; map 300: gate NPC 24 (1781,1268)
(NPCDirection.csv; AutoPath's 23 is the 梦幻岛 gate: clicking 23 on map 1 got no answer). Click, take the option holding
the target name (or the only one), wait for the map. The path-finder alone does not cross (60 s on map 1).
"""
import sys
import time

import trial_run as t
from pp_chain import walk

GATES = {1: (10213, (1338, 1053), '自由市场', 300), 300: (24, (1781, 1268), '逍遥村', 1)}


def hop(c):
    st = c.world()
    npc, xy, word, dest = GATES[st.map_id]
    walk(c, st.map_id, xy, f'传送门 {npc}')
    t0 = time.monotonic()
    c.game.click_npc(npc)
    d = t.wait(lambda: c.dialog() or c.world().map_id == dest, 5, f'传送门 {npc} 菜单')
    menu = None
    if d is not True and c.world().map_id != dest:
        menu = [(o, t.plain(l)) for o, l in d.options if o]
        hit = [o for o, l in menu if word in l] or ([menu[0][0]] if len(menu) == 1 else [])
        if not hit:
            raise t.Stop(f'传送门 {npc} 菜单不认识: {menu}')
        c.game.select_dialog(hit[0])
        t.wait(lambda: c.world().map_id == dest, 10, f'传送到 {dest}')
    took = time.monotonic() - t0
    time.sleep(1)
    s = c.world()
    t.say(f'[{c.name}] 传送门 {npc}: map {st.map_id} -> {s.map_id} ({s.x:.0f},{s.y:.0f})，{took:.1f}s，菜单 {menu}')


if __name__ == '__main__':
    c, n = t.Client(sys.argv[1]), int(sys.argv[2])
    ok = 0
    for i in range(n):
        hop(c)
        hop(c)
        ok += 1
        t.say(f'第 {i + 1} 次来回成功')
    t.say(f'{n} 次来回，成功 {ok} 次')
