"""Return the five-person team to 荒芜之地一区, walk to 荒芜之地二区, then farm 禁锢之地 to level 70.

The user supplied the transition coordinate (4120,2600), the patrol line, and the instruction to choose the first
entry option at NPC 10184. Only the 方士 captain and its pet issue combat commands; an apprentice leaving map 1200
stops the patrol once the captain is out of battle.
"""
import _bootstrap  # noqa: F401
import math

import maze_train as m
import pp_chain
import trial_run as t
from common import APPRENTICES
from lunhui15 import LEADER
from provisioner import world as w
from well10 import form_team
from line.ops import home_village

DESERT_1, DESERT_2 = 180, 181
TO_DESERT_2 = (4120, 2600)
GATE_NPC, GATE_XY = 10184, (3123, 2630)
FORBIDDEN_LAND, TARGET_LEVEL = 1200, 70
PATROL_A, PATROL_B = (8898, 5985), (8500, 5750)
ROLES = (LEADER,) + APPRENTICES


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


def main():
    m.CASTERS = (LEADER,)
    home_village()
    pp_chain.main('荒芜之地1区', ['平静海岸2区', '龙之都', '恶人山', '苦无沙漠3区'])
    lead = t.Client(LEADER)
    if lead.world().map_id != DESERT_1:
        raise t.Stop(f'PP鸡没有到荒芜之地一区：map={lead.world().map_id}')

    # The local transition is a walk to the coordinate given by the user; m.Route waits through battles.
    m.STAGES = (dict(name='走到荒芜之地二区', goal=(DESERT_2, None), maze=None, until=None,
                     patrol_b=None, legs={DESERT_1: ('walk', DESERT_1, TO_DESERT_2)}),)
    m.main()
    verify_team_map(DESERT_2, '切入荒芜之地二区')

    # The NPC has multiple destination choices. Route's click handler selects the first selectable option,
    # as explicitly requested by the user.
    m.STAGES = (dict(name='进入禁锢之地', goal=(FORBIDDEN_LAND, None), maze=None, until=None,
                     patrol_b=None, legs={DESERT_2: ('click', GATE_NPC, GATE_XY)}),)
    m.main()
    verify_team_map(FORBIDDEN_LAND, 'NPC 10184 第一选项')

    watchers = {n: t.Client(n) for n in ROLES}
    def someone_left_map():
        outside = {n: c.world().map_id for n, c in watchers.items()
                   if c.world() and c.world().map_id != FORBIDDEN_LAND}
        if outside:
            say(f'有人离开禁锢之地，停止巡逻：{outside}')
        return bool(outside)

    m.STAGES = (dict(name='禁锢之地巡逻', maze=FORBIDDEN_LAND, until=TARGET_LEVEL,
                     patrol_a=PATROL_A, patrol_b=PATROL_B, legs={}, done_when=someone_left_map),)
    say(f'开始禁锢之地巡逻：{PATROL_A} ↔ {PATROL_B}，四个小号目标70级')
    m.main()


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
