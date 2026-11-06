"""Research helper (2026-11-06, 狗贼贼 quest 819): the leader walks the team in 巨石之城南部遗址 (map 1050) to within
REACH px of a point (mapgrid touch spot, short legs), then logs where everybody stands.

    python -X utf8 probe_ruins_walk.py X Y [reach, default 250]
"""
import sys

from _bootstrap import ROLES

import gouzei as gz
import tiger_fight
import trial_run as t
from provisioner import mapgrid


def main(x, y, reach):
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    g = mapgrid.load(gz.RUINS)
    s = lead.world()
    hit = g.touch_spot(g.distances((s.x, s.y)), (x, y), reach)
    if not hit:
        raise SystemExit(f'从 ({s.x:.0f},{s.y:.0f}) 走不到 ({x},{y}) 附近')
    legs = g.waypoints((s.x, s.y), hit[1], 600)
    for i, wp in enumerate(legs, 1):
        tiger_fight.walk(lead, wp, f'({x},{y}) 第 {i}/{len(legs)} 段', gz.RUINS, '巨石之城南部遗址', 'enter_ruins.py')
    s = lead.world()
    gz.say_state(cs, f'队长在 ({s.x:.0f},{s.y:.0f})，队伍 {len(lead.team())}:')


if __name__ == '__main__':
    main(int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else 250)
