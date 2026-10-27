"""Read-only one-line status per role (level, map/xy, gold, team, quests 24/224, bag fill, shoe) for the 2nd round.

    python -X utf8 research/shitu/r2_status.py [role ...]     (default: 伏地魔1 伏地魔2 + SHITU_APPRENTICES)
"""
import sys

from common import APPRENTICES, MASTERS, find_roles, module_base
from provisioner import world as w
from provisioner.memory import ProcessMemory


def line(name, pid):
    m = ProcessMemory(pid, module_base(pid))
    st = w.read_world(m)
    bag = w.read_bag(m)
    team = w.read_team(m)
    return (f'{name:6} lv{w.read_level(m):<3} map {st.map_id} ({st.x:.0f},{st.y:.0f}) gold {w.read_gold(m)} '
            f'talent {w.read_talent_points(m)} team {team.members if team else ()} '
            f'q24 {w.read_quest(m, 24)} q224 {w.read_quest(m, 224)} bag {len(bag)}/{w.read_bag_capacity(m)} '
            f'shoe {w.read_shoe_record(m)}')


def main(names):
    found = find_roles(names)
    for n in names:
        print(line(n, found[n][0]) if n in found else f'{n}: 没有窗口')


if __name__ == '__main__':
    main(tuple(sys.argv[1:]) or MASTERS + APPRENTICES)
