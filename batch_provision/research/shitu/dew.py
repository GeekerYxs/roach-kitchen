"""Task 181 step 7: gather 5 花露 at a 通天花 (NPC 954-959, 通天塔一区 280) for each named role.

    python -X utf8 research/shitu/dew.py 千万5 千万6 ...      (one thread = one window per role)

Live 16:3x (千万5): ClickNpc(954) ->「采集露水」(option 1) -> 0x46ff「已经采集N滴花露，共需要5滴」, no bag item, the
same flower answers again, until「这朵花上面的露水已经被采集完了，过一会再来吧」(per role: 千万6 could still gather
954 after 千万5 was told so). So each role leaves its team (a member's ClickNpc gets no answer), gathers a flower
until it is used up, then walks alone to the next of the 6 flowers, until 5. Battles: run away (user 16:3x: the 通天塔 monsters are too strong).
"""
import math
import re
import sys
import threading
import time

import trial_run as t
from teamwalk import Escaper          # moved there 18:5x; dew.Escaper still works
from monitor import Tap, texts

COUNT = re.compile(r'已经采集(\d+)滴花露')
MAP = 280
# 通天花 NPCDirection.csv, nearest first from the 通天塔路口 gate (480,4852)
FLOWERS = ((954, (292, 4295)), (957, (1050, 4065)), (955, (1440, 4724)), (956, (1949, 4313)),
           (958, (1156, 3301)), (959, (945, 2817)))
NEAR = 120


def go(c, caster, xy):
    """Walk alone to xy on map 280; in any battle on the way the role runs away (Escaper)."""
    end, last = time.monotonic() + 180, 0
    while True:
        s = c.world()
        if s.in_battle:
            caster.tick(time.monotonic())
        elif math.dist((s.x, s.y), xy) <= NEAR and not s.moving:
            return
        elif not s.nav_active and not s.moving and time.monotonic() - last > 2:
            caster.reset()
            c.game.navigate(MAP, *xy)
            last = time.monotonic()
        if time.monotonic() > end:
            raise t.Stop(f'{c.name} 180s 没走到 {xy}')
        time.sleep(0.15)


def run(name, res):
    c = t.Client(name)
    if c.team():
        c.game.team_leave()
        t.wait(lambda: not c.team(), 5, f'{name} 离队')
    tap = Tap(c.pid, from_end=True)
    tap.ready()
    caster, got = Escaper(c), 0
    for npc, xy in FLOWERS:
        go(c, caster, xy)
        for _ in range(6):
            go(c, caster, xy)
            c.game.click_npc(npc)
            d = t.wait(lambda: c.dialog(), 5, f'{name} 通天花 {npc}')
            if not any('采集' in t.plain(l) for _, l in d.options):
                c.game.select_dialog(0)
                t.say(f'[{name}] 通天花 {npc} 采完了（{got}/5），换下一朵')
                break
            c.game.select_dialog(next(o for o, l in d.options if '采集' in t.plain(l)))
            end = time.monotonic() + 5
            while time.monotonic() < end:
                for _, dd, op, body, _ in tap.poll():
                    k = COUNT.search(' '.join(texts(body))) if op == 0x46ff else None
                    if k:
                        got, end = int(k.group(1)), 0
                time.sleep(0.1)
            if got >= 5:
                break
        if got >= 5:
            break
    res[name] = got
    t.say(f'[{name}] 花露 {got}/5，逃跑指令 {caster.escapes} 次')


if __name__ == '__main__':
    res = {}
    ths = [threading.Thread(target=run, args=(n, res)) for n in sys.argv[1:]]
    [x.start() for x in ths]
    [x.join() for x in ths]
    t.say(f'花露: {res}')
