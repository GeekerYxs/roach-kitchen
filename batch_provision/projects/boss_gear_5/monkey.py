"""金刚猴的挑战书 (quest 518, lv38): constants and helpers shared by the 金刚猴 scripts (user 2026-11-06).

ResLib (MainTask / SubTask / PhaseTask / NPCDirection / maplink 518):
- 龙上利 (NPC 1707, 迷惑森林1区 map 150 (1746,206)) gives and takes the quest; reward 5400 经验 + 950 潜能 each.
- Step 0: in 秘密宝窟 (map 850, entrance NPC 10170 at (211,210) in 150) get 1 定土神针 (11170) from the wild
  流浪蟠桃怪 (monster 619) and 1 鲜花铠甲 (11171) from the wild 野人狗仔队 (monster 444), give both to 变形金猴
  (NPC 1180, (1650,1905)) for the right to fight, beat it. Step 1: tell 龙上利.
- PhaseTask: in a team every member must have the quest; one take = one 变形金猴; fleeing fails the quest.
- mapgrid: 850 has three parts that do not connect by walking. The 150 entrance lands in the big one (土拨鼠 1133,
  mole.py 2026-11-03); 变形金猴 stands in another one with「秘密宝窟一层」NPC 10219 (4140,2208).「秘密宝窟二层」
  10218 (3780,2628) in the big part leads there (maplink 850 -> 850 rect (3744,2592)-(3816,2664)); live 2026-11-06
  standing on it did nothing, a raw 0x50 click on it moved the whole team to (4158,2055). Round 3: a walk that ENDED
  in its rect moved the team up as well (then nothing in the lower part is reachable).
"""
from _bootstrap import BATCH  # noqa: F401  (sys.path)

import trial_run as t
from provisioner import world as w

QUEST = 518
FOREST_1, BAOKU = 150, 850
LONG, LONG_XY = 1707, (1746, 206)
GATE_NPC, GATE_XY = 10170, (211, 210)
UP_NPC, UP_XY = 10218, (3780, 2628)   # 秘密宝窟二层: live 2026-11-06 a raw click on it moves the team up
DOWN_NPC, DOWN_XY = 10219, (4140, 2208)  # 秘密宝窟一层: back from 变形金猴's part
MONKEY, MONKEY_XY = 1180, (1650, 1905)
PIN, ARMOR = 11170, 11171
ITEMS = {PIN: '定土神针', ARMOR: '鲜花铠甲'}
BEAT_STEP, REPORT_STEP, DONE = 0, 1, 2

_UPPER = None


def steps(c):
    q = w.read_quest(c.mem, QUEST)
    return q.steps if q and q.active else ()


def has_quest(c):
    return bool(steps(c))


def beaten(c):
    s = steps(c)
    return len(s) > BEAT_STEP and s[BEAT_STEP] == DONE


def ready(c):                                  # beat 变形金猴, not reported yet
    s = steps(c)
    return len(s) > REPORT_STEP and s[BEAT_STEP] == DONE and s[REPORT_STEP] != DONE


def has(c, item):
    return any(b.item_id == item for b in w.read_bag(c.mem) or ())


def items(c):
    return {ITEMS[b.item_id]: b.quantity for b in w.read_bag(c.mem) or () if b.item_id in ITEMS}


def upper(c):
    """In the part of 850 where 变形金猴 stands (mapgrid component of the monkey)."""
    global _UPPER
    from provisioner import mapgrid
    s = c.world()
    if s.map_id != BAOKU:
        return False
    if _UPPER is None:
        g = mapgrid.load(BAOKU)
        _UPPER = (g, set(g.distances(MONKEY_XY)))
    g, cells = _UPPER
    cell = g.nearest_walkable(*g.cell(s.x, s.y), limit=4)
    return cell in cells


def team_full(cs):
    return set(cs[0].team()) == {c.char_id for c in cs}


def say_state(cs, why):
    t.say(why + ' ' + str({c.name: (steps(c), items(c)) for c in cs}))
