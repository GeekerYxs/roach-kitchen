"""Task 181 step 7 without a team (user 16:3x: run from every battle): each named role travels alone to 通天塔一区
and gathers 5 花露 (dew.run).

    python -X utf8 research/shitu/dew_solo.py 千万1 千万7 ...       (one thread = one window per role)

Route per role: pp_chain.hop with itself as the only member (map 1 -> 81 平静海岸2区 -> 279 通天塔路口, 190 + 690 gold),
then walk to 通天塔门 952 (935,290) and pick「到通天塔一区」, then dew.run. Every battle on the way: dew.Escaper.
"""
import math
import sys
import threading
import time

import trial_run as t
import dew
from pp_chain import hop

GATE, GATE_XY = 952, (935, 290)


def walk(c, esc, map_id, xy, near=80):
    end, last = time.monotonic() + 180, 0
    while True:
        s = c.world()
        if s.in_battle:
            esc.tick(time.monotonic())
        elif s.map_id == map_id and math.dist((s.x, s.y), xy) <= near and not s.moving:
            return
        elif not s.nav_active and not s.moving and time.monotonic() - last > 2:
            esc.reset()
            c.game.navigate(map_id, *xy)
            last = time.monotonic()
        if time.monotonic() > end:
            raise t.Stop(f'{c.name} 180s 没走到 {map_id} {xy}')
        time.sleep(0.15)


def travel(c):
    esc = dew.Escaper(c)
    if c.team():
        c.game.team_leave()
        t.wait(lambda: not c.team(), 5, f'{c.name} 离队')
    for _ in range(3):
        if c.world().map_id in (279, dew.MAP):
            break
        hop(c, [c], '通天塔', ['平静海岸2区'])
    if c.world().map_id == 279:
        walk(c, esc, 279, GATE_XY)
        c.game.click_npc(GATE)
        d = t.wait(lambda: c.dialog(), 5, f'{c.name} 通天塔门')
        c.game.select_dialog(next(o for o, l in d.options if '一区' in t.plain(l)))
        t.wait(lambda: c.world().map_id == dew.MAP, 10, f'{c.name} 进通天塔一区')
    t.say(f'[{c.name}] 到通天塔一区 ({c.world().x:.0f},{c.world().y:.0f})')


def run(name, res):
    try:
        travel(t.Client(name))
        dew.run(name, res)
    except t.Stop as e:
        res[name] = f'停止: {e}'
        t.say(f'[{name}] 停止: {e}')


if __name__ == '__main__':
    res = {}
    ths = [threading.Thread(target=run, args=(n, res)) for n in sys.argv[1:]]
    [x.start() for x in ths]
    [x.join() for x in ths]
    t.say(f'花露: {res}')
