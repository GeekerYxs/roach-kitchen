"""记忆之地 (map 1250) for levels 65-70 (user 2026-11-07): from 禁锢之地 out to 荒芜之地2区, walk to 荒芜之地3区,
enter 记忆之地, patrol (3400,850) <-> (3000,1100).

    python -X utf8 memory_land.py --test 欧皇丨花花乀     route test: one strong role alone, runs from EVERY battle
                                                          (user: test only; production fights, jingu_47_70)
    python -X utf8 memory_land.py --test 欧皇丨花花乀 --from-here    go on from the current map (after a relog)

Map links (client tables AutoPath_utf8.csv / NPCDirection_utf8.csv, unpacked ResLib):
  1200 exit NPC 10183 at (9024,5916) -> 181 (stand on it: same exit kind as 1202's 11132, live 2026-10-29)
  181 map link 10053 at (4104,1368) -> 182 (荒芜之地3区)
  182 entrance NPC 10186 at (228,1065) -> 1250 (「迷宫·66~70级练级点」; a second one 10216 at (834,181)):
      CLICK it (live 2026-11-07 欧皇: stood at (256,1080) 10 s, nothing; ClickNpc -> map 1250 at once, no menu)
  1250's own exit 10185 at (3660,792) -> 182, ~260 px from patrol A: a patrol leg must not step on it.
The first two legs are same-map walks onto the link point (as jingu_47_70's 180 -> 181 leg): crossing happens on
arrival (live 2026-11-07: 1200 exit -> 181 (3114,2637); 181 (4104,1368) -> 182 (222,2763)).
"""
import _bootstrap  # noqa: F401
import math
import sys
import time

import trial_run as t
from provisioner import world as w

JINGU, DESERT_2, DESERT_3, MEMORY = 1200, 181, 182, 1250
LEGS = {JINGU: ('walk', JINGU, (9024, 5916)),          # 禁锢之地 exit -> 荒芜之地2区
        DESERT_2: ('walk', DESERT_2, (4104, 1368)),    # -> 荒芜之地3区
        DESERT_3: ('click', 10186, (228, 1065))}       # -> 记忆之地: standing next to it does nothing, a click
                                                       # takes the team in, no menu (live 2026-11-07, lands (3522,867))
PATROL_A, PATROL_B = (3400, 850), (3000, 1100)
FROM_LEVEL, TARGET_LEVEL = 65, 70
WAY = (JINGU, DESERT_2, DESERT_3, MEMORY)              # maps the team is allowed to be on during this stage


def say(msg):
    t.say(f'[记忆之地] {msg}')


def walk_escaping(c, map_id, xy, why, timeout=300):
    """TEST ONLY: c walks alone to xy on map_id (or until the map changes), running from every battle."""
    import teamwalk
    esc, end = teamwalk.Escaper(c), time.monotonic() + timeout
    start_map, seen, seen_at, sent, logged = c.world().map_id, None, time.monotonic(), -1e9, 0.0
    while time.monotonic() < end:
        now, s = time.monotonic(), c.world()
        if s is None:
            time.sleep(0.3)
            continue
        if s.map_id != start_map and not s.in_battle:
            say(f'[{c.name}] {why}：切到 map {s.map_id} ({s.x:.0f},{s.y:.0f})')
            return s.map_id
        if now - logged > 10:
            say(f'[{c.name}] 去{why} {xy}: map {s.map_id} ({s.x:.0f},{s.y:.0f}) 距离 {math.dist((s.x, s.y), xy):.0f}'
                f'{"，战斗中逃跑" if s.in_battle else ""}')
            logged = now
        if seen is None or math.dist((s.x, s.y), seen) > 15 or s.in_battle:
            seen, seen_at = (s.x, s.y), now
        if s.in_battle:
            esc.tick(now)
        elif math.dist((s.x, s.y), xy) <= 40 and not s.moving:
            say(f'[{c.name}] 到了{why} ({s.x:.0f},{s.y:.0f})')
            return s.map_id
        elif now - seen_at > 6:
            c.game.cancel_navigation()
            seen_at, sent = now, -1e9
        elif not s.nav_active and not s.moving and now - sent > 2:
            esc.reset()
            c.game.navigate(map_id, *xy)
            sent = now
        time.sleep(0.15)
    raise t.Stop(f'{c.name} {timeout}s 没走到{why}')


def test(name, from_here=False):
    """User 2026-11-07: simulate 禁锢之地 (3800,3500) -> 记忆之地 patrol with one role, escaping every battle.
    from_here: go on from the current map along LEGS (a relog mid-test landed in 181)."""
    import pp_chain
    from quanshou import scroll
    c = t.Client(name)
    if c.team():
        c.game.team_leave()
        t.wait(lambda: not c.team(), 5, f'{name} 离队')
    t0 = time.monotonic()
    if from_here and c.world().map_id in WAY:
        pass
    elif c.world().map_id not in (180, DESERT_2, JINGU, DESERT_3, MEMORY):
        if c.world().map_id not in (1, 8):
            scroll(c)
        via = ['平静海岸2区', '龙之都', '恶人山', '苦无沙漠3区']
        for _ in range(8):
            if c.world().map_id == 180:
                break
            pp_chain.hop(c, [c], '荒芜之地1区', via)
    if not (from_here and c.world().map_id in WAY) and c.world().map_id == 180:
        walk_escaping(c, 180, (4120, 2600), '荒芜之地2区入口')
    if not (from_here and c.world().map_id in WAY) and c.world().map_id == DESERT_2:
        walk_escaping(c, DESERT_2, (3123, 2630), '禁锢之地 NPC 10184')
        c.game.click_npc(10184)
        d = t.wait(lambda: c.dialog(), 6, 'NPC 10184 菜单')
        opts = [(o, t.plain(l)) for o, l in d.options if o]
        say(f'[{name}] NPC 10184 菜单 {opts}，选第一项')
        c.game.select_dialog(opts[0][0])
        t.wait(lambda: c.world().map_id == JINGU, 10, '进入禁锢之地')
    if c.world().map_id == JINGU:
        walk_escaping(c, JINGU, (3800, 3500), '禁锢之地 61-65 巡逻点 (3800,3500)')
        say(f'[{name}] 模拟起点就位，用时 {(time.monotonic() - t0) / 60:.1f} 分；开始走记忆之地')
    t1 = time.monotonic()
    for _ in range(4):
        m = c.world().map_id
        if m == MEMORY:
            break
        leg = LEGS.get(m)
        if not leg:
            raise t.Stop(f'{name} 在意外的地图 {m}')
        if leg[0] == 'click':
            walk_escaping(c, m, leg[2], f'map {m} 的 NPC {leg[1]}')
            c.game.click_npc(leg[1])
        else:
            walk_escaping(c, leg[1], leg[2], f'map {m} 的出口 {leg[2]}')
        t.wait(lambda: c.world() and c.world().map_id != m, 10, f'离开 map {m}')
    if c.world().map_id != MEMORY:
        raise t.Stop(f'{name} 没进记忆之地：map {c.world().map_id}')
    s = c.world()
    say(f'[{name}] 进了记忆之地，落点 ({s.x:.0f},{s.y:.0f})，路上 {(time.monotonic() - t1) / 60:.1f} 分')
    for lap in range(2):
        for xy in (PATROL_A, PATROL_B):
            if walk_escaping(c, MEMORY, xy, f'巡逻点 {xy}') != MEMORY:
                raise t.Stop(f'{name} 巡逻去 {xy} 时出了记忆之地（踩到出口？）')
    say(f'[{name}] 巡逻 2 圈都在 map {c.world().map_id}，等级 {w.read_level(c.mem)}；测试完成，回城')
    scroll(c)


if __name__ == '__main__':
    try:
        if '--test' in sys.argv:
            test(sys.argv[sys.argv.index('--test') + 1], from_here='--from-here' in sys.argv)
    except t.Stop as e:
        say(f'停止：{e}')
        raise SystemExit(1)
