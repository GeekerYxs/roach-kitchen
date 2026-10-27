"""Record 飞鞋 (0x82) next to 大个王 (map 20 (4398,2553)) for 伏地魔1/2 + the apprentices, so take224.py can fly back.

    python -X utf8 research/shitu/shoe_dagewang.py

The team is left first; each role walks to its own spot (like 01:31 round 1: 45 px apart east of 大个王), stands
still 1.5 s (the record takes the SERVER position) and the record is read back ([[ui]+0xD84]+0x438 map / +0x43C xy).
"""
import math
import time

import trial_run as t
from bai_shi import mark
from common import APPRENTICES, MASTERS
from provisioner import world as w

BOSS = (20, 4398, 2553)


def main():
    cs = [t.Client(n) for n in MASTERS + APPRENTICES]
    for c in cs:
        if c.team():
            c.game.team_leave()
    for c in cs:
        t.wait(lambda: not c.team(), 5, f'{c.name} 离队')
    for i, c in enumerate(cs):
        xy = (BOSS[1] + 45 * i, BOSS[2] + 18 * i)
        st = c.world()
        if st.map_id != BOSS[0]:
            raise t.Stop(f'{c.name} 不在龙之都外城 (map {st.map_id})')
        if math.dist((st.x, st.y), xy) > 30:
            c.game.navigate(BOSS[0], *xy)
            t.wait(lambda: (s := c.world()) and math.dist((s.x, s.y), xy) <= 30 and not s.moving, 30, f'{c.name} 走到 {xy}')
    time.sleep(1.5)
    for c in cs:
        c.game.shoe_record()
    time.sleep(1.0)
    for c in cs:
        rec = w.read_shoe_record(c.mem)
        ok = rec and rec[0] == BOSS[0] and math.dist(rec[1:], (BOSS[1], BOSS[2])) < 400
        t.say(f'[{c.name}] 飞鞋记录 {rec} {"OK" if ok else "不对"}')
        if not ok:
            raise t.Stop(f'{c.name} 飞鞋没记上: {rec}')
        mark(c.name, 'shoe_dagewang', record=list(rec))


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
