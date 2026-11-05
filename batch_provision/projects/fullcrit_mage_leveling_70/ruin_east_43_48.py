"""Level the four 元素使 apprentices in 巨石之城东部遗址 (map 1100).

Route: team home -> PP鸡 via 平静海岸2区 and 恶人山 -> 苦无沙漠3区 (172) ->
entrance NPC 10180 at (642,1180). Once the whole team arrives in map 1100, each apprentice
uses exactly one 加钙地瓜, then the leader patrols (8562,2943) <-> (3300,600) until all
four characters reach level 48.
"""
import _bootstrap  # noqa: F401
import json
import os
from pathlib import Path

import maze_train as m
import trial_run as t
from common import APPRENTICES
from factory.items import load_items
from lunhui15 import LEADER
from provisioner import world as w

import guards
import home_supply
from policy import yam_ids

MAP_DESERT_3 = 172
MAP_RUIN_EAST = 1100
TARGET_LEVEL = int(os.environ.get("SHITU_TARGET_LEVEL", "48"))
ENTRANCE_NPC = 10180
ENTRANCE_XY = (642, 1180)
ITEMS = load_items()
# Character ids (not names: a new batch reuses 元素使01..04) that already ate their one yam in 1100.
YAM_MARKER = Path(__file__).with_name("runtime") / "ruin_east_43_48_yams_by_id.json"
YAM_IDS = yam_ids(ITEMS)


def prepare_route():
    """Recall the team to 逍遥村西区 (selling and refilling there), then take PP鸡 to the map-172 entrance."""
    lead = t.Client(LEADER)
    expected = {t.Client(name).char_id for name in (LEADER,) + APPRENTICES}
    if lead.world().map_id == MAP_RUIN_EAST and set(lead.team()) == expected:
        if lead.world().nav_active:
            lead.game.cancel_navigation()
        return
    if lead.world().map_id != MAP_DESERT_3:
        home_supply.home_and_restock()
    home_supply.pp_go("苦无沙漠3区", ["平静海岸2区", "龙之都", "恶人山"])
    m.STAGES = (
        dict(name="进入巨石之城东部遗址", goal=(MAP_RUIN_EAST, None), maze=None,
             until=None, patrol_b=None,
             legs={MAP_DESERT_3: ("click", ENTRANCE_NPC, ENTRANCE_XY)}),
    )
    m.main()


def eat_one_yam(name):
    c = t.Client(name)
    key = str(c.char_id)
    eaten = set(json.loads(YAM_MARKER.read_text(encoding="utf-8-sig"))) if YAM_MARKER.exists() else set()
    if key in eaten:
        t.say(f"[{name}] 加钙地瓜此前已使用（角色 {key}），本次不重复吃")
        return
    if c.world().map_id != MAP_RUIN_EAST or c.world().in_battle:
        raise t.Stop(f"{name} 未在巨石之城东部遗址安全待命，暂不吃地瓜")
    bag = w.read_bag(c.mem) or ()
    hit = next((s for s in bag if s.item_id in YAM_IDS), None)
    if hit is None:
        raise t.Stop(f"{name} 背包没有加钙地瓜（只认 {sorted(YAM_IDS)}，不开礼包、不吃超级/倍能地瓜）")
    slot, item_id = hit.slot, hit.item_id
    before = w.item_count(bag, item_id)
    c.game.use_item(slot)
    t.wait(lambda: w.item_count(w.read_bag(c.mem), item_id) == before - 1,
           5, f"{name} 吃一个加钙地瓜")
    t.say(f"[{name}] 已吃1个加钙地瓜（剩余 {before - 1}）")
    eaten.add(key)
    YAM_MARKER.parent.mkdir(parents=True, exist_ok=True)
    YAM_MARKER.write_text(json.dumps(sorted(eaten), ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    # The user specified 天之箭 for this 方士; the caster will stop if the server rejects the configured skill.
    os.environ.setdefault("SHITU_PLAYER_SKILL", "354")
    os.environ.setdefault("SHITU_PLAYER_SKILL_LEVEL", "7")
    prepare_route()
    names = (LEADER,) + APPRENTICES
    clients = {name: t.Client(name) for name in names}
    lead = clients[LEADER]
    expected = {clients[name].char_id for name in names}
    if lead.world().map_id != MAP_RUIN_EAST or set(lead.team()) != expected:
        raise t.Stop(f"到达后地图或队伍核验失败：map={lead.world().map_id} team={lead.team()}")
    for name in APPRENTICES:
        s = clients[name].world()
        if s.map_id != MAP_RUIN_EAST or s.in_battle or s.verification:
            raise t.Stop(f"{name} 尚未在1100安全待命，暂不使用道具")
    for name in APPRENTICES:
        eat_one_yam(name)

    # User instruction: the four apprentices and their pets stay idle; only the leader and its pet fight.
    guards.configure_revive()
    m.CASTERS = (LEADER,)
    m.STAGES = (
        dict(name="巨石之城东部遗址巡逻", maze=MAP_RUIN_EAST, until=TARGET_LEVEL,
             patrol_a=(8562, 2943), patrol_b=(3300, 600), legs={}, done_when=guards.soda_guard),
    )
    m.main()


if __name__ == "__main__":
    try:
        main()
    except t.Stop as exc:
        lead = t.Client(LEADER)
        if lead.world().nav_active:
            lead.game.cancel_navigation()
        t.say(f"停止：{exc}")
        raise SystemExit(1)
    except Exception as exc:
        lead = t.Client(LEADER)
        if lead.world().nav_active:
            lead.game.cancel_navigation()
        t.say(f"异常停止（已取消队长寻路）：{exc!r}")
        raise
