"""Return the five-person team to 荒芜之地一区, walk to 荒芜之地二区, then farm 禁锢之地 to level 65 and 记忆之地 to 70
(61-64: patrol (3800,3500) <-> (3300,3500); 65-70: 记忆之地 (3400,850) <-> (3000,1100), memory_land.py;
user 2026-11-07).

The user supplied the transition coordinate (4120,2600), the patrol line, and the instruction to choose the first
entry option at NPC 10184. Only the 方士 captain and its pet issue combat commands. Anyone leaving the stage's maps or
an empty captain soda bag raises t.Stop once the captain is out of battle, so the supervisor counts it as a failure
and recovers (it used to return normally, which the supervisor took for a finished stage and retried forever).
"""
import _bootstrap  # noqa: F401
import os
import time

import maze_train as m
import trial_run as t
from common import APPRENTICES
from provisioner import world as w

import guards
import home_supply
import memory_land

DESERT_1, DESERT_2 = 180, 181
TO_DESERT_2 = (4120, 2600)
GATE_NPC, GATE_XY = 10184, (3123, 2630)
FORBIDDEN_LAND, TARGET_LEVEL = 1200, 70
PATROL_A, PATROL_B = (8898, 5985), (8500, 5750)
# user 2026-11-07: once all four apprentices are 61, patrol (3800,3500) <-> (3300,3500) in the same map until 65;
# from 65 on the team walks out to 记忆之地 (memory_land.py) until 70 (maze_train walks the stages in order)
MID_FROM, MID_UNTIL = 61, 65
MID_A, MID_B = (3800, 3500), (3300, 3500)
LEADER = os.environ['SHITU_LEADER']
ROLES = (LEADER,) + tuple(APPRENTICES)
LEFT_GRACE = 10.0    # s a member may be off the leader's map while the team crosses a map link


def say(msg):
    t.say(f'[{LEADER}] {msg}')


def verify_team_map(map_id, where):
    states = {n: t.Client(n).world() for n in ROLES}
    wrong = {n: (s.map_id, round(s.x), round(s.y)) for n, s in states.items() if s.map_id != map_id}
    if wrong:
        raise t.Stop(f'{where} 后五人未全部在 map {map_id}：{wrong}')
    lead = t.Client(LEADER)
    expected = {t.Client(n).char_id for n in ROLES}
    if set(lead.team()) != expected:
        raise t.Stop(f'{where} 后队伍名单不完整：{lead.team()}')
    say(f'{where}核验通过：五人都在 map {map_id}，等级 ' +
        str({n: w.read_level(t.Client(n).mem) for n in APPRENTICES}))


def enter(low=0):
    """Village -> 荒芜之地二区 -> 禁锢之地; from 65 on it stops in 荒芜之地二区 (memory_land.LEGS go on from there)."""
    home_supply.home_and_restock(ROLES)
    home_supply.pp_go('荒芜之地1区', ['平静海岸2区', '龙之都', '恶人山', '苦无沙漠3区'])
    lead = t.Client(LEADER)
    if lead.world().map_id != DESERT_1:
        raise t.Stop(f'PP鸡没有到荒芜之地一区：map={lead.world().map_id}')

    # The local transition is a walk to the coordinate given by the user; m.Route waits through battles.
    m.STAGES = (dict(name='走到荒芜之地二区', goal=(DESERT_2, None), maze=None, until=None,
                     patrol_b=None, legs={DESERT_1: ('walk', DESERT_1, TO_DESERT_2)}),)
    m.main()
    verify_team_map(DESERT_2, '切入荒芜之地二区')
    if low >= memory_land.FROM_LEVEL:
        return

    # The NPC has multiple destination choices. Route's click handler selects the first selectable option,
    # as explicitly requested by the user.
    m.STAGES = (dict(name='进入禁锢之地', goal=(FORBIDDEN_LAND, None), maze=None, until=None,
                     patrol_b=None, legs={DESERT_2: ('click', GATE_NPC, GATE_XY)}),)
    m.main()
    verify_team_map(FORBIDDEN_LAND, 'NPC 10184 第一选项')


def resume_maps(low):
    """Maps on which a complete team just goes on patrolling instead of the trip from the village."""
    return (FORBIDDEN_LAND, memory_land.MEMORY) if low >= memory_land.FROM_LEVEL else (FORBIDDEN_LAND,)


def allowed_maps(low):
    """Maps the team may be on while patrolling: from 65 also the way out to 记忆之地."""
    return memory_land.WAY if low >= memory_land.FROM_LEVEL else (FORBIDDEN_LAND,)


def left_members(maps, lead_map, allowed, since, now, grace=LEFT_GRACE):
    """{name: map} of members off the allowed maps or off the leader's map for `grace` s (since: name -> first seen,
    updated in place). The five clients change map a moment apart when the team crosses a link."""
    for n, mp in maps.items():
        if mp not in allowed or mp != lead_map:
            since.setdefault(n, now)
        else:
            since.pop(n, None)
    return {n: maps[n] for n, at in since.items() if now - at >= grace and n in maps}


def main():
    m.CASTERS = (LEADER,)
    lead = t.Client(LEADER)
    expected = {t.Client(n).char_id for n in ROLES}
    low = min(w.read_level(t.Client(n).mem) for n in APPRENTICES)
    maps = {t.Client(n).world().map_id for n in ROLES}
    if len(maps) == 1 and maps <= set(resume_maps(low)) and set(lead.team()) == expected:
        say(f'完整队伍已在 map {next(iter(maps))}，原地续跑')
    else:
        enter(low)

    watchers = {n: t.Client(n) for n in ROLES}
    since = {}

    def someone_left_map():
        states = {n: c.world() for n, c in watchers.items()}
        now_low = min(w.read_level(c.mem) for n, c in watchers.items() if n != LEADER)
        lead_map = states[LEADER].map_id if states[LEADER] else None
        out = left_members({n: s.map_id for n, s in states.items() if s}, lead_map, allowed_maps(now_low),
                           since, time.monotonic())
        if out:
            raise t.Stop(f'有人离开练级地图 / 不在队长的地图，停止巡逻：{out}（队长 map {lead_map}）')
        return False

    m.STAGES = patrol_stages(guards.all_of(someone_left_map, guards.soda_guard), low)
    guards.configure_revive()
    say('开始巡逻：' + '；'.join(f'{s["name"]} {s["patrol_a"]} ↔ {s["patrol_b"]} 到 {s["until"]} 级'
                              for s in m.STAGES))
    m.main()


def patrol_stages(done_when, low):
    """The patrol stages still ahead for the lowest apprentice level `low` (maze_train skips reached ones itself, but
    it indexes past the end when every stage is reached, so the finished ones are dropped here)."""
    stages = (dict(name='禁锢之地巡逻', maze=FORBIDDEN_LAND, until=MID_FROM,
                   patrol_a=PATROL_A, patrol_b=PATROL_B, legs={}, done_when=done_when),
              dict(name=f'禁锢之地巡逻 {MID_FROM}-{MID_UNTIL} 级', maze=FORBIDDEN_LAND, until=MID_UNTIL,
                   patrol_a=MID_A, patrol_b=MID_B, legs={}, done_when=done_when),
              dict(name=f'记忆之地巡逻 {memory_land.FROM_LEVEL}-{TARGET_LEVEL} 级', maze=memory_land.MEMORY,
                   until=TARGET_LEVEL, patrol_a=memory_land.PATROL_A, patrol_b=memory_land.PATROL_B,
                   legs=dict(memory_land.LEGS), done_when=done_when))
    left = tuple(s for s in stages if low < s['until'])
    return left or stages[-1:]


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        try:
            lead = t.Client(LEADER)
            if lead.world().nav_active:
                lead.game.cancel_navigation()
        except Exception:
            pass
        say('收到停止指令，已取消队长寻路')
    except t.Stop as exc:
        lead = t.Client(LEADER)
        if lead.world().nav_active:
            lead.game.cancel_navigation()
        say(f'停止：{exc}')
        raise SystemExit(1)
