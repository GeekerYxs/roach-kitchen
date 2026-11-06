"""葵花宝典 (quest 475, lv33 story quest): constants and helpers shared by the 葵花 scripts (user 2026-11-06).

ResLib (MainTask / SubTask / PhaseTask / NPCDirection / maplink 475):
- 苦力强 (NPC 1607, 无尽平原3区 map 142 (1890,225)) gives and takes the quest; reward: one of 4 items (257), no exp.
- Step 0: in 葵花魔穴 (map 800, entrance NPC 10168 at (3165,2244) in 142) beat 葵花姐姐 (NPC 1146, hidden: map -800,
  (5862,1077)); she only shows once enough of the 10 葵花 NPCs (1008-1017) in the cave are destroyed. Then hand
  葵花宝典 to 苦力强.
- Live 2026-11-06 21:27: the leader's accept gave 475 to the leader only (story quest; no team clause in PhaseTask),
  unlike 518 / 673 / 1185 / 1130. 欧皇丨花花乀 had 475 in the done list and 苦力强 no longer offered it to them.
"""
from _bootstrap import BATCH  # noqa: F401  (sys.path)

from provisioner import world as w

QUEST = 475
PLAIN_3, CAVE = 142, 800
KULI, KULI_XY = 1607, (1890, 225)
GATE_NPC, GATE_XY = 10168, (3165, 2244)
SISTER, SISTER_XY = 1146, (5862, 1077)
FLOWERS = {1008: (2574, 2229), 1009: (3726, 939), 1010: (2946, 693), 1011: (5262, 2373), 1012: (8370, 3153),
           1013: (8406, 2223), 1014: (5898, 1665), 1015: (6690, 1797), 1016: (7554, 645), 1017: (5946, 909)}


def steps(c):
    q = w.read_quest(c.mem, QUEST)
    return q.steps if q and q.active else ()


def has_quest(c):
    return bool(steps(c))


def team_full(cs):
    return set(cs[0].team()) == {c.char_id for c in cs}
