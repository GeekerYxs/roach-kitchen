"""Research helper (2026-11-06, 电锯杀人王 quest 1852): the leader walks the team in 惊魂监狱 (map 264) to within
REACH px of a point (mapgrid touch spot, short legs), then logs keys / quest of everybody.

    python -X utf8 probe_prison_walk.py X Y [reach, default 250]
"""
import sys

from _bootstrap import ROLES

import chainsaw as cz
import trial_run as t


def main(x, y, reach):
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    cz.walk(lead, (x, y), f'({x},{y})', reach=reach, fix='enter_prison.py')
    s = lead.world()
    cz.say_state(cs, f'队长在 ({s.x:.0f},{s.y:.0f})，队伍 {len(lead.team())}:')


if __name__ == '__main__':
    main(int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else 250)
