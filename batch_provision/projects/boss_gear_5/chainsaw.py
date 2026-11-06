"""惊魂监狱的杀人狂 (quest 1852, lv49, boss 电锯杀人狂): constants and helpers shared by the 电锯杀人王 scripts
(user 2026-11-06).

ResLib (MainTask / SubTask / PhaseTask / NPCDirection / AutoPath / maplink / PropLib):
- 老刘 (NPC 576, 龙之都外城 map 20 (3666,1959)) gives and takes the quest; MainTask 1852: not a story quest, special
  type 3 (猎杀任务), reward 12000 经验 + 1500 潜能 each. Step 0: beat 电锯杀人狂 in 惊魂监狱 (map 264); step 1: tell 老刘.
- 惊魂监狱 is entered from 龙之都内城 (map 24) at 惊魂监狱入口 NPC 1339 (5660,3258). Map 24 is reached from
  龙之都交叉口 (map 25) only through 守门人 铁男 (NPC 575, (294,171)); 20 -> 25 is the walk-on exit 10227 (663,166).
- Inside 264 (quest 1853 死亡游戏, given by 惊魂监狱机关): three groups of two prisoners, kill ONE of each group for a
  key; two sets of three keys; with a full set open 惊魂监狱机关 1336 (2471,1941). Prisoners (NPC, xy, key):
  看守 1330 崩溃的傻瓜猎人 (906,3735) 11295 / 1331 昏迷的蠢材士兵 (786,3765) 11296;
  行刑官 1333 抓狂的呆子巡警 (2622,603) 11297 / 1332 昏迷的笨蛋卫兵 (2766,561) 11298;
  监狱官 1334 痴呆的倒霉警察 (4174,3777) 11299 / 1335 昏迷的猪头大兵 (4302,3747) 11300.
  电锯杀人狂 NPC 1337 (3498,5139); a second 惊魂监狱机关 1340 (4355,5328); 惊魂监狱密封口 1338 (2280,1905).
- 龙之都外城 has walk-in doors (NPCDirection type 18): the client's own path from the PP鸡 landing walks into
  连锁商店 (map 31); walk() below paths on mapgrid with the doors walled off (mapgrid.DOORS).
"""
from _bootstrap import LEADER

import tiger_fight
import trial_run as t
from provisioner import mapgrid
from provisioner import world as w

QUEST = 1852
OUTER, CROSS, INNER, PRISON, SHOP = 20, 25, 24, 264, 31
LAOLIU, LAOLIU_XY = 576, (3666, 1959)
CROSS_EXIT = (663, 166)              # AutoPath 10227: walk onto it in map 20 -> map 25
TIENAN, TIENAN_XY = 575, (294, 171)
SHOP_EXIT = (793, 764)               # NPC 10423 in map 31: walking onto it -> map 20 (2024,612), live 2026-11-06
GATE_NPC, GATE_XY = 1339, (5660, 3258)
MACHINE, MACHINE_XY = 1336, (2471, 1941)
BOSS, BOSS_XY = 1337, (3498, 5139)
KEYS = {11295: '看守钥匙(猎人)', 11296: '看守钥匙(士兵)', 11297: '行刑官钥匙(巡警)', 11298: '行刑官钥匙(卫兵)',
        11299: '监狱官钥匙(警察)', 11300: '监狱官钥匙(大兵)'}
# group -> ((npc, xy, key), (npc, xy, key))
PRISONERS = (((1330, (906, 3735), 11295), (1331, (786, 3765), 11296)),
             ((1333, (2622, 603), 11297), (1332, (2766, 561), 11298)),
             ((1334, (4174, 3777), 11299), (1335, (4302, 3747), 11300)))
BEAT_STEP, REPORT_STEP, DONE = 0, 1, 2
LEG = 400                            # px of path per walking leg (shorter than 600: the doors of map 20)
MAP_NAMES = {OUTER: '龙之都外城', CROSS: '龙之都交叉口', INNER: '龙之都内城', PRISON: '惊魂监狱'}

_GRIDS = {}


def steps(c):
    q = w.read_quest(c.mem, QUEST)
    return q.steps if q and q.active else ()


def has_quest(c):
    return bool(steps(c))


def beaten(c):
    s = steps(c)
    return len(s) > BEAT_STEP and s[BEAT_STEP] == DONE


def ready(c):
    """Beat 电锯杀人狂, not handed in yet. Live 2026-11-06: just opening 老刘's reward page already sets step 1 to
    DONE ((2, 2)); only「接受奖励」removes the quest. So a beaten quest still on the role is ready, whatever step 1 says."""
    return beaten(c)


def keys(c):
    return {KEYS[b.item_id]: b.quantity for b in w.read_bag(c.mem) or () if b.item_id in KEYS}


def has(c, item):
    return any(b.item_id == item for b in w.read_bag(c.mem) or ())


def team_full(cs):
    return set(cs[0].team()) == {c.char_id for c in cs}


def all_in(cs, map_id):
    return all((s := c.world()) and s.map_id == map_id for c in cs) and team_full(cs)


def say_state(cs, why):
    t.say(why + ' ' + str({c.name: (steps(c), keys(c)) for c in cs}))


def grid(map_id):
    if map_id not in _GRIDS:
        _GRIDS[map_id] = mapgrid.load(map_id, avoid_doors=True)
    return _GRIDS[map_id]


def walk(lead, xy, why, reach=0, fix='go_laoliu.py'):
    """Walk the leader (team behind) in its current map to xy (or the path-nearest spot within reach px of it) in
    LEG px legs on the door-free mapgrid path. The last leg may be a walk-on exit (another map afterwards)."""
    s = lead.world()
    map_id = s.map_id
    g = grid(map_id)
    goal = xy
    if reach:
        hit = g.touch_spot(g.distances((s.x, s.y)), xy, reach)
        if not hit:
            raise t.Stop(f'[{LEADER}] 在{MAP_NAMES.get(map_id, map_id)} ({s.x:.0f},{s.y:.0f}) 走不到{why} {xy}')
        goal = hit[1]
    legs = g.waypoints((s.x, s.y), goal, LEG)
    if legs is None:
        raise t.Stop(f'[{LEADER}] 在{MAP_NAMES.get(map_id, map_id)} ({s.x:.0f},{s.y:.0f}) 走不到{why} {xy}')
    for i, wp in enumerate(legs, 1):
        if lead.world().map_id != map_id:
            return                             # crossed (walk-on exit / door) on the way
        tiger_fight.walk(lead, wp, f'{why}（第 {i}/{len(legs)} 段）', map_id, MAP_NAMES.get(map_id, map_id), fix)


def cross(lead, cs, exit_xy, to_map, why):
    """Walk the team onto a walk-on exit of the current map (doors avoided on the way) and wait for all of cs in
    to_map. The last ~LEG px are one navigate onto the exit (pp_chain.walk would take the new map as a failure)."""
    s = lead.world()
    if s.map_id != to_map:
        legs = grid(s.map_id).waypoints((s.x, s.y), exit_xy, LEG) or [exit_xy]
        if len(legs) > 1:
            walk(lead, legs[-2], why)
        for attempt in range(1, 6):
            tiger_fight.fight_out(lead, 300)
            if lead.world().map_id == to_map:
                break
            lead.game.navigate(lead.world().map_id, *exit_xy)
            try:
                t.wait(lambda: lead.world().map_id == to_map, 20, why)
                break
            except t.Stop:
                t.say(f'[{LEADER}] 第 {attempt} 次没走过{why}（在 map {lead.world().map_id}）')
        else:
            raise t.Stop(f'[{LEADER}] 走了 5 次没过{why}')
    t.wait(lambda: all(c.world().map_id == to_map for c in cs), 15, f'全队过{why}')
