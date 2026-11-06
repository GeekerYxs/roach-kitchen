"""传说中的老树叶 (quest 673, lv48, 10 a day like the eagle): constants and helpers shared by the 老树叶 scripts.

ResLib (MainTask / SubTask / PhaseTask / NPCDirection 673):
- 克拉苏 (NPC 1903, 迷惑森林3区 map 152 (3294,171)) gives and takes the quest; reward 9840 经验 + 1440 潜能 each.
- In 失落之地 (map 950, entrance NPC 10195 at (2178,85) in 152): beat the right one of three 老树护卫 (1186-1188) ->
  拜山帖 11173; then the right one of three 老树随从 (1183-1185) -> 老树根 11169; then 黑山老妖 1189 -> 老树叶 11172.
  Step 0 = beat 黑山老妖, step 1 = hand the leaf to 克拉苏.
- PhaseTask: in a team every member must have the quest; one take = one 黑山老妖; fleeing fails the quest.

Live 2026-11-06 (伏地魔1 + four 70s, round 1 19:05-19:47):
- 克拉苏 from the PP鸡 landing (3252,432) (264 px, raw 0x50): ☆传说中的老树叶(48）-> 哇，这么麻烦？-> 放心这难不倒我的.
  The leader's accept gave quest 673 to all five at once. 克拉苏: "only the RIGHT guard / follower gives the item".
- 失落之地 has two halves that do not connect by walking (mapgrid: north y <= 3640, south y >= 3968). The guards are
  in the north (team lands at (1842,3459)), the followers and 黑山老妖 in the south. 失落之地界碑 4238 (2106,3417):
  get a 传送石 (11026) from one of four 石碑 4038-4041 (「搜查石碑的背面」: empty =「光滑、平整」, right =「一颗石头
  镶嵌…」-> 拾取; only the leader gets it), beat 暗天爪牙 1165 (614,2399), touch the 传送门 1166 that appears there
  (3 min, then the 爪牙 respawns): 传送 -> the whole team lands at (1746,4743) in the south half, the stone is used up.
  (界碑 coordinates are 4/3 of the map's: its (819,3199) = (614,2399).) 19:30 the 爪牙 was gone (killed by someone
  else) and came back within ~1 min.
- Round 1: guards 1187, 1188 wrong (a won battle, nothing), 1186 right; 石碑 4038, 4039 empty, 4040 had the stone;
  followers 1184 wrong, 1185 right (拜山帖 swapped for 老树根); 黑山老妖 started at the first「开打」(no quiz), 57 s.
  Every guard / follower / 爪牙 / 老妖 fight took 46-66 s with all five casting; the leader's fight counts for all five.
- Round 2 (20:05, round_leaf.py, 15.4 min): guard 1186 right again; stone in 4041 (4040 empty now); follower 1184
  right, 1185 wrong -> the right 石碑 / follower are dealt anew each round.
- Through walls: 4040 answered from 393 px; 4041 did not from 446 px.
- Hand-in: 传说中的老树叶［进行中］-> 接受奖励 (all five at once) -> 接受 (re-take, all five).
"""
import json

from _bootstrap import BATCH

import trial_run as t
from provisioner import world as w

QUEST = 673
FOREST_3, LOST = 152, 950
KELASU, KELASU_XY = 1903, (3294, 171)
GATE_NPC, GATE_XY = 10195, (2178, 85)
BAISHAN, ROOT, LEAF, STONE = 11173, 11169, 11172, 11026
ITEMS = {BAISHAN: '拜山帖', ROOT: '老树根', LEAF: '老树叶', STONE: '传送石'}
# npc -> ResLib NPCDirection xy
GUARDS = {1186: (2514, 477), 1187: (2958, 657), 1188: (1926, 639)}
FOLLOWERS = {1183: (1506, 8043), 1184: (762, 7647), 1185: (1938, 7449)}
STELES = {4038: (1122, 1263), 4039: (3222, 1179), 4040: (3510, 759), 4041: (1386, 3291)}
CLAW, PORTAL, CLAW_XY = 1165, 1166, (614, 2399)
YAO, YAO_XY = 1189, (2932, 7968)
SOUTH_Y = 3800               # mapgrid: the north half ends at y 3640, the south half starts at 3968
BEAT_STEP, REPORT_STEP, DONE = 0, 1, 2
# this round's wrong guards / followers / steles, and last round's right ones (tried first: maybe fixed)
LOG = BATCH / 'runtime' / 'boss_gear_5_leaf.json'


def steps(c):
    q = w.read_quest(c.mem, QUEST)
    return q.steps if q and q.active else ()


def has_quest(c):
    return bool(steps(c))


def beaten(c):
    s = steps(c)
    return len(s) > BEAT_STEP and s[BEAT_STEP] == DONE


def ready(c):                                  # beat 黑山老妖, not reported yet
    s = steps(c)
    return len(s) > REPORT_STEP and s[BEAT_STEP] == DONE and s[REPORT_STEP] != DONE


def has(c, item):
    return any(b.item_id == item for b in w.read_bag(c.mem) or ())


def items(c):
    return {ITEMS[b.item_id]: b.quantity for b in w.read_bag(c.mem) or () if b.item_id in ITEMS}


def south(c):
    s = c.world()
    return s.map_id == LOST and s.y >= SOUTH_Y


def load_log():
    try:
        data = json.loads(LOG.read_text(encoding='utf8'))
    except (OSError, ValueError):
        data = {}
    data.setdefault('wrong', {})
    data.setdefault('right', {})
    return data


def save_log(data):
    LOG.parent.mkdir(exist_ok=True)
    LOG.write_text(json.dumps(data, ensure_ascii=False), encoding='utf8')


def new_round():
    """The hand-in ends a round: this round's wrong picks are forgotten, last round's right ones are kept."""
    data = load_log()
    data['wrong'] = {}
    save_log(data)


def team_full(cs):
    return set(cs[0].team()) == {c.char_id for c in cs}


def say_state(cs, why):
    t.say(why + ' ' + str({c.name: (steps(c), items(c)) for c in cs}))
