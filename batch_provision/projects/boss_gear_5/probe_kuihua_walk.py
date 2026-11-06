"""Research helper (2026-11-06, 葵花宝典 quest 475): the leader walks the team in 葵花魔穴 (map 800) to within REACH px
of a point (mapgrid touch spot), then logs where everybody stands.

    python -X utf8 probe_kuihua_walk.py X Y [reach, default 250]
"""
import sys

from _bootstrap import ROLES

import kuihua as kh
import tiger_fight
import trial_run as t
from provisioner import mapgrid


def main(x, y, reach):
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    g = mapgrid.load(kh.CAVE)
    s = lead.world()
    hit = g.touch_spot(g.distances((s.x, s.y)), (x, y), reach)
    if not hit:
        raise SystemExit(f'从 ({s.x:.0f},{s.y:.0f}) 走不到 ({x},{y}) 附近')
    legs = g.waypoints((s.x, s.y), hit[1], 600)
    for i, wp in enumerate(legs, 1):
        tiger_fight.walk(lead, wp, f'({x},{y}) 第 {i}/{len(legs)} 段', kh.CAVE, '葵花魔穴', 'enter_kuihua.py')
    s = lead.world()
    t.say(f'队长在 ({s.x:.0f},{s.y:.0f})，任务 {kh.steps(lead)}，队伍 {len(lead.team())}')


if __name__ == '__main__':
    main(int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else 250)
