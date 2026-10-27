"""Background fighter for the 师徒 runs that only WAIT for battles (gather.py): 伏地魔1/2 cast 扫射 803 and their pets
烈焰爆发 1504 whenever their SP changes (lunhui15.Caster); apprentices' talent points go to 体质. Runs until killed.

    python -X utf8 research/shitu/fight_helper.py
"""
import time

import trial_run as t
from factory.welltrain import Talent, decide_talent
from lunhui15 import APPRENTICES, CASTERS, LEADER, MEMBERS, TICK, Caster
from provisioner import world as w


def main():
    cs = {n: t.Client(n) for n in (LEADER,) + MEMBERS}
    casters = [Caster(cs[n]) for n in CASTERS]
    talents = {n: Talent() for n in APPRENTICES}
    was, battles = {c.c.name: False for c in casters}, 0
    t.say('战斗助手开始')
    while True:
        now = time.monotonic()
        for c in casters:
            st = c.c.world()
            on = bool(st and st.in_battle)
            if on and not was[c.c.name] and c.c.name == CASTERS[0]:
                battles += 1
                t.say(f'第 {battles} 场战斗')
            if not on and was[c.c.name]:
                c.reset()
            was[c.c.name] = on
            if on:
                c.tick(now)
        for n in APPRENTICES:
            if n == LEADER:          # the leader may be the gatherer: its window is gather.py's (no concurrent calls)
                continue
            tm, pts = talents[n], w.read_talent_points(cs[n].mem)
            d = decide_talent(pts, tm, now)
            if d.kind == 'add':
                t.say(f'[{n}] 等级 {w.read_level(cs[n].mem)}，{d.reason}')
                cs[n].game.add_constitution(d.arg)
                tm.sent_at, tm.before = now, pts
            elif d.kind in ('verified', 'unconfirmed'):
                tm.sent_at = None
        time.sleep(TICK)


if __name__ == '__main__':
    main()
