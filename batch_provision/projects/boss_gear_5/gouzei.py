"""突出虫围 (quest 819, lv43, boss 狗贼贼): constants and helpers shared by the 狗贼贼 scripts (user 2026-11-06).

ResLib (MainTask / SubTask / PhaseTask / NPCDirection / maplink / PropLib):
- 皮克斯 (NPC 2303, 苦无沙漠2区 map 171 (1950,1527)) gives and takes the quest; MainTask 819: not a story quest,
  reward 8010 经验 + 1290 潜能 each.
- Step 0: in 巨石之城南部遗址 (map 1050, entrance NPC 10178 at (675,2635) in 171) beat 遗址守护者 (NPC 1191,
  (558,2013)) for 遗址守护者白旗 (11162), 遗址守卫者 (NPC 1192, (4158,1413)) for 遗址守卫者白旗 (11163), then with
  both flags 狗贼贼 (NPC 1193, (1065,967)). Step 1: tell 皮克斯.
- PhaseTask 819: in a team every member must have the quest; one take = one 狗贼贼; fleeing fails the quest.
- mapgrid: 1050 has three parts that do not connect by walking: the entrance part (遗址守护者, 遗址1号传送机 10196
  (702,1971)), the middle part (lands at 10197 (3498,5283); 遗址守卫者, 遗址2号传送机 10198 (4410,1449)) and the deep
  part (lands at 10199 (4194,4203); 狗贼贼). PropLib 11175 / 11176 are passes for 传送机 1 / 2.
- 171 neighbours: 苦无沙漠3区 172 (PP鸡, the 172 -> 171 link is ~800 px from the landing) and 恶人山 50.
"""
from _bootstrap import BATCH  # noqa: F401  (sys.path)

import trial_run as t
from provisioner import world as w

QUEST = 819
DESERT_3, KUWU_2, RUINS = 172, 171, 1050
PIKES, PIKES_XY = 2303, (1950, 1527)
PIKES_STAND = (2192, 1480)          # mapgrid: path-nearest roomy cell within 250 px of 皮克斯 from the 172 side
GATE_NPC, GATE_XY = 10178, (675, 2635)
GUARD1, GUARD1_XY = 1191, (558, 2013)     # 遗址守护者
GUARD2, GUARD2_XY = 1192, (4158, 1413)    # 遗址守卫者
GOUZEI, GOUZEI_XY = 1193, (1065, 967)
TP1, TP1_XY = 10196, (702, 1971)
TP2, TP2_XY = 10198, (4410, 1449)
FLAG1, FLAG2, PASS1, PASS2 = 11162, 11163, 11175, 11176
ITEMS = {FLAG1: '守护者白旗', FLAG2: '守卫者白旗', PASS1: '1号通行证', PASS2: '2号通行证'}
BEAT_STEP, REPORT_STEP, DONE = 0, 1, 2


def steps(c):
    q = w.read_quest(c.mem, QUEST)
    return q.steps if q and q.active else ()


def has_quest(c):
    return bool(steps(c))


def beaten(c):
    s = steps(c)
    return len(s) > BEAT_STEP and s[BEAT_STEP] == DONE


def ready(c):                                  # beat 狗贼贼, not reported yet
    s = steps(c)
    return len(s) > REPORT_STEP and s[BEAT_STEP] == DONE and s[REPORT_STEP] != DONE


def has(c, item):
    return any(b.item_id == item for b in w.read_bag(c.mem) or ())


def items(c):
    return {ITEMS[b.item_id]: b.quantity for b in w.read_bag(c.mem) or () if b.item_id in ITEMS}


def team_full(cs):
    return set(cs[0].team()) == {c.char_id for c in cs}


def say_state(cs, why):
    t.say(why + ' ' + str({c.name: (steps(c), items(c)) for c in cs}))
