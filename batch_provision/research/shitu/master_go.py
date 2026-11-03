"""The master alone walks somewhere, fighting what it meets (lunhui15.Caster), optionally through an entrance NPC.

    python -X utf8 research/shitu/master_go.py MASTER MAP X Y [NPC OPTION_WORD MAP2 X2 Y2]

2026-11-03 元素使 team, 187 last step: the apprentices can only be sent to 死鸟人 one by one (奥里雷西亚「只允许单人
传送，请先解散队伍」), so the master walks in: 龙之都 -> 无尽平原3区 142 -> 葵花魔穴 entrance 10168 (3165,2244) ->
800 -> 死鸟人 (7734,1335). Its battle assist is off (revive.py), so battles on the way are fought here.
"""
import math
import sys
import time

import trial_run as t
from lunhui15 import Caster

NEAR, STALL = 120, 8.0


def go(c, caster, map_id, xy, why):
    last_nav, at, moved = -1e9, time.monotonic(), None
    while True:
        now = time.monotonic()
        s = c.world()
        if s.in_battle:
            caster.tick(now)
            at = now
            time.sleep(0.15)
            continue
        if s.map_id == map_id and math.dist((s.x, s.y), xy) <= NEAR and not s.moving:
            t.say(f'[{c.name}] 到了{why} map {s.map_id} ({s.x:.0f},{s.y:.0f})')
            return
        if moved is None or math.dist((s.x, s.y), moved) > 15:
            moved, at = (s.x, s.y), now
        if now - at > STALL:
            c.game.cancel_navigation()
            last_nav, at = -1e9, now
        if not s.nav_active and not s.moving and now - last_nav > 2:
            c.game.navigate(map_id, *xy)
            last_nav = now
        time.sleep(0.2)


def main(name, map_id, x, y, npc=None, word=None, map2=None, x2=None, y2=None):
    c = t.Client(name)
    if c.team():
        c.game.team_leave()
    if c.dialog():
        c.game.select_dialog(0)
    caster = Caster(c)
    go(c, caster, int(map_id), (int(x), int(y)), f'地图 {map_id}')
    if npc:
        c.game.click_npc(int(npc))
        # 10168 (葵花魔穴, 2026-11-03 01:07) sends the clicker in at once, no dialog: a dialog or the map change
        t.wait(lambda: c.dialog() or c.world().map_id == int(map2), 5, f'NPC {npc} 对话框或进地图 {map2}')
        d = c.dialog()
        if d and c.world().map_id != int(map2):
            t.say(f'[{name}] NPC {npc}: {t.body(d)[:60]} {d.options}')
            c.game.select_dialog(next(o for o, l in d.options if o and (word == '*' or word in t.plain(l))))   # * = first real option
        t.wait(lambda: c.world().map_id == int(map2), 10, f'进地图 {map2}')
        s = c.world()
        t.say(f'[{name}] 进了地图 {map2}，落点 ({s.x:.0f},{s.y:.0f})')
        go(c, caster, int(map2), (int(x2), int(y2)), f'地图 {map2} ({x2},{y2})')


if __name__ == '__main__':
    try:
        main(*sys.argv[1:])
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
