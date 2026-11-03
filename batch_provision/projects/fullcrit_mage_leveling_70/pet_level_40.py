"""Level each apprentice's second (囧盒仔) pet from 1 to 40 along the B+ map route.

The existing maze controller decides when to change maps from character levels.  This
wrapper supplies each apprentice's observed in-battle pet level to that controller;
the leader continues to use its real character level and its original fighting pet.
"""
import _bootstrap  # noqa: F401
import struct
import os
import sys
import time

import maze_train as m
import pp_chain
import r4_util
from common import APPRENTICES, MASTERS
from lunhui15 import LEADER
from provisioner import world as w

PET_SLOT = 1
PET_LEVEL_START = int(os.environ.get("SHITU_PET_LEVEL_START", "1"))
PET_LEVEL_END = 40
OP_SET_FIGHTING_PET = 0x0105

PET_ROUTE = (
    ("阴森古井", 651, 10),
    ("轮回之城", 555, 12),
    ("暗影迷城", 600, 16),
    ("八阵图", 700, 23),
    ("遗忘洞穴", 750, 28),
    ("通天塔一区", 280, 33),
    ("通天塔二区", 281, 40),
)

WELL = dict(name="阴森古井", maze=651, until=10,
            patrol_a=(2214, 1653), patrol_b=(1000, 260),
            legs={1: ("walk", 130, (2544, 2904)),
                  130: ("click", 10152, (2596, 2880))})
MAZE_STAGES = (
    dict(name="轮回之城", maze=555, until=12, patrol_a=(2754, 291), patrol_b=(2550, 616),
         legs={81: ("click", 10158, (1635, 3041))}),
    dict(name="暗影迷城", maze=600, until=16, patrol_a=(786, 771), patrol_b=(1136, 771), land=(786, 771),
         legs={555: ("click", 10157, (2880, 360)),
               81: ("walk", 82, (1724, 2489)),
               82: ("click", 10160, (1724, 2489))}),
    dict(name="八阵图", maze=700, until=23, patrol_b=(1200, 1800),
         legs={600: ("click", 10159, (672, 756)),
               82: ("walk", 140, (831, 2257)),
               140: ("click", 10164, (831, 2257))}),
    dict(name="遗忘洞穴", maze=750, until=28, patrol_a=(1590, 3369), patrol_b=(1946, 2430),
         legs={700: ("click", 10163, (672, 1608)),
               140: ("walk", 20, (4398, 2553)),
               20: ("walk", 141, (3410, 252)),
               141: ("click", 10166, (3410, 252))}),
)
TOWER1 = dict(name="通天塔一区", maze=280, until=33, patrol_a=(414, 4893), patrol_b=(106, 4467),
              legs={279: ("click", 952, (935, 290), "一区")})
TOWER2 = dict(name="通天塔二区", maze=281, until=40, patrol_a=(600, 500), patrol_b=(1200, 400),
              legs={279: ("click", 952, (935, 290), "二区")})


def main():
    if len(MASTERS) != 1 or len(APPRENTICES) != 4:
        raise m.t.Stop("需要 1 个队长和 4 个小号")
    names = (LEADER,) + APPRENTICES
    clients = {name: m.t.Client(name) for name in names}
    lead = clients[LEADER]
    pet_levels = {clients[name].pid: PET_LEVEL_START for name in APPRENTICES}
    original_read_level = w.read_level

    def read_pet_level(mem):
        if mem.pid not in pet_levels:
            return original_read_level(mem)
        battle = w.read_battle(mem)
        if battle and battle.pet:
            levels = w.read_fighter_levels(mem, (battle.pet.pos,))
            if levels and levels[0] > 0:
                pet_levels[mem.pid] = levels[0]
        return pet_levels[mem.pid]

    def ensure_pet_slot():
        for name in APPRENTICES:
            c = clients[name]
            s = c.world()
            p = w._player_data(c.mem)
            first, last = w._vector(c.mem, p + w.PET_VECTOR, 4 * 50)
            count = (last - first) // 4
            index = struct.unpack("<i", c.mem.read(p + w.PET_FIGHTING, 4))[0]
            if s.verification or (s.busy and not s.in_battle):
                raise m.t.Stop(f"{name} 不在安全待命状态，未切换（map={s.map_id} 战斗={s.in_battle} 忙={s.busy} 验证={s.verification}）")
            if count <= PET_SLOT:
                raise m.t.Stop(f"{name} 没有预期的囧盒仔宠物槽位{PET_SLOT}（宠物数={count}）")
            if index != PET_SLOT:
                if s.in_battle:
                    raise m.t.Stop(f"{name} 正在战斗且囧盒仔未出战，暂不切换")
                body = struct.pack("<I", 0) + bytes((PET_SLOT,))
                c.game.send(OP_SET_FIGHTING_PET, body)
                m.t.wait(lambda: struct.unpack("<i", c.mem.read(p + w.PET_FIGHTING, 4))[0] == PET_SLOT,
                         5, f"{name} 囧盒仔出战")
            m.t.say(f"[{name}] 囧盒仔出战已核验（宠物数={count}，索引={PET_SLOT}）")

    ensure_pet_slot()
    lead_map = lead.world().map_id
    for name in APPRENTICES:
        c = clients[name]
        s = c.world()
        if s.map_id != lead_map or s.verification or (s.busy and not s.in_battle):
            raise m.t.Stop(f"{name} 与队长不同图或未待命，停止练级")
    expected_team = {clients[name].char_id for name in names}
    existing_team = set(lead.team())
    if existing_team and existing_team != expected_team:
        raise m.t.Stop(f"当前队伍与目标五人不符：{lead.team()}")
    if not existing_team and any(clients[name].team() for name in names):
        raise m.t.Stop("队伍状态不一致，停止以免误改队伍")

    w.read_level = read_pet_level
    try:
        def min_pet_level():
            return min(read_pet_level(clients[name].mem) for name in APPRENTICES)

        m.t.say(f"继续按宠物等级练级：{dict((name, PET_LEVEL_START) for name in APPRENTICES)}；"
                "人物等级只用于组队，大号保留原宠物")
        if min_pet_level() < 10:
            m.STAGES = (WELL,)
            m.main()

        if min_pet_level() < 28:
            if lead.world().map_id not in (555, 81, 82, 600, 140, 700, 141, 750, 20):
                r4_util.home()
                pp_chain.main("平静海岸2区", [])
            m.STAGES = MAZE_STAGES
            m.main()

        if min_pet_level() < 33:
            if lead.world().map_id not in (279, 280):
                r4_util.home()
                pp_chain.main("通天塔", ["平静海岸2区"])
            m.STAGES = (TOWER1,)
            m.main()

        if min_pet_level() < PET_LEVEL_END:
            if lead.world().map_id not in (279, 281):
                r4_util.home()
                pp_chain.main("通天塔", ["平静海岸2区"])
            m.STAGES = (TOWER2,)
            m.main()

        final = {name: read_pet_level(clients[name].mem) for name in APPRENTICES}
        if any(level < PET_LEVEL_END for level in final.values()):
            raise m.t.Stop(f"终点宠物等级未达标：{final}")
        m.t.say(f"四只囧盒仔宠物均到40级：{final}；停在通天塔二区")
    finally:
        w.read_level = original_read_level


if __name__ == "__main__":
    try:
        main()
    except m.t.Stop as exc:
        m.t.say(f"停止：{exc}")
        raise SystemExit(1)
