"""Train the four 元素使 to level 48 in map 1100, then fly to 龙之都内城 and enter 惊魂监狱.

This wrapper composes the existing 43->48 route (target overridden by SHITU_TARGET_LEVEL) with the prison patrol.
Existing characters need a valid map-24 shoe record. A fresh character without one must first use the user's
new-account route: outer-city teleporter -> 龙之都交叉口 -> stand on (666,155) to enter the inner city ->
talk to 铁男; if the 龙之都公民 quest is incomplete, pay 60,000 gold, then record the shoe before using this flow.
We stop safely instead of sending a shoe-return request for a character without that prerequisite.
"""
import _bootstrap  # noqa: F401
import math
import os
import sys
import time

os.environ.setdefault("SHITU_TARGET_LEVEL", "48")
os.environ.setdefault("SHITU_PLAYER_SKILL", "354")
os.environ.setdefault("SHITU_PLAYER_SKILL_LEVEL", "7")

import ruin_east_43_48 as training
import shoe_point
import trial_run as t
from common import APPRENTICES, MASTERS
from provisioner import world as w
from well10 import form_team

LEADER = os.environ.get("SHITU_LEADER", MASTERS[0])
ROLES = (LEADER,) + APPRENTICES
CITY_MAP, CITY_SHOE = 24, (2982, 3303)
PRISON_MAP, PRISON_NPC, PRISON_XY = 264, 1339, (5660, 3258)
PICKUP = (2369, 2000)


def say(msg):
    t.say(f"[{LEADER}] {msg}")


def home_and_fly(cs):
    from line.ops import home_village
    import sell_tradable
    import tour_level_maps_two_battles as supplies

    home_village()
    sell_tradable.main(list(ROLES), "junk-stones-white")
    supplies.top_up_scrolls_at_home()
    supplies.top_up_master_sweets_at_home()
    soda = w.item_count(w.read_bag(cs[LEADER].mem) or (), 8456)
    say(f"回城清理/补给后队长劲爆汽水 {soda}")
    if soda == 0:
        raise t.Stop("队长劲爆汽水为0；全队已回城，须先到荒芜之地一区汉尼拔补给")
    if soda < 599:
        raise t.Stop(f"队长劲爆汽水 {soda}<599；须到荒芜之地一区汉尼拔补到1485后再飞鞋")
    for name, c in cs.items():
        st = c.world()
        if not st or st.map_id not in (1, 8) or st.in_battle or st.verification:
            raise t.Stop(f"{name} 回城后状态异常: {st}")
    missing_records = [n for n, c in cs.items()
                       if not shoe_point.record_ok(w.read_shoe_record(c.mem), CITY_MAP, CITY_SHOE)]
    if missing_records:
        raise t.Stop("没有内城飞鞋记录，不能飞鞋: " + ", ".join(missing_records) +
                     "。新号须先按外城传送员→交叉口→(666,155)→铁男路线进内城；未完成龙之都公民任务者交6万，"
                     "到内城后先记录飞鞋。")

    while True:
        why = [shoe_point.why_not(n, w.read_shoe_record(c.mem), shoe_point.used_at(n),
                                  time.time(), CITY_MAP, CITY_SHOE) for n, c in cs.items()]
        cooling = [x for x in why if x and "飞鞋还要" in x]
        if not cooling:
            break
        say("飞鞋冷却中，留在村里等冷却结束：" + "；".join(cooling))
        time.sleep(60)
    shoe_point.fly(CITY_MAP, CITY_SHOE, list(ROLES))


def enter_prison(cs):
    lead = cs[LEADER]
    form_team(lead, [cs[n] for n in APPRENTICES])
    expected = {c.char_id for c in cs.values()}
    t.wait(lambda: set(lead.team()) == expected, 10, "内城飞鞋后五人组队")
    for name, c in cs.items():
        if w.item_count(w.read_bag(c.mem) or (), 9801) < 1:
            raise t.Stop(f"{name} 没带回城卷；监狱入口提示无法从里面出来，不进入")

    st = lead.world()
    if st.map_id != CITY_MAP:
        raise t.Stop(f"队长飞鞋后不在龙之都内城: map={st.map_id}")
    lead.game.navigate(CITY_MAP, *PRISON_XY)
    end = time.monotonic() + 240
    while time.monotonic() < end:
        st = lead.world()
        if st.map_id != CITY_MAP:
            raise t.Stop(f"走向监狱入口时意外切图: map={st.map_id}")
        if not st.in_battle and not st.verification and math.dist((st.x, st.y), PRISON_XY) <= 80 and not st.moving:
            break
        time.sleep(0.2)
    else:
        raise t.Stop(f"没走到惊魂监狱入口: {lead.world()}")

    lead.game.click_npc(PRISON_NPC)
    d = t.wait(lambda: lead.dialog(), 6, "NPC 1339 的入监狱提示")
    prompt = t.plain(d.text)
    say(f"监狱入口提示: {prompt.strip()}")
    confirm = [(o, label) for o, label in d.options if o and "确认" in t.plain(label)]
    if len(confirm) != 1:
        raise t.Stop(f"NPC 1339 的确认项不唯一: {[(o, t.plain(l)) for o,l in d.options]}")
    lead.game.select_dialog(confirm[0][0])
    t.wait(lambda: lead.world().map_id == PRISON_MAP, 10, "队长进入惊魂监狱")
    t.wait(lambda: all(c.world().map_id == PRISON_MAP for c in cs.values()),
           15, "五人全部进入惊魂监狱")
    t.wait(lambda: set(lead.team()) == expected, 5, "进入监狱后五人队伍仍完整")
    say(f"五人到达地图 {PRISON_MAP} 接人点 {PICKUP}；开始监狱巡逻")


def main():
    training.main()
    cs = {n: t.Client(n) for n in ROLES}
    levels = {n: w.read_level(c.mem) for n, c in cs.items() if n != LEADER}
    if not all(level >= int(os.environ["SHITU_TARGET_LEVEL"]) for level in levels.values()):
        raise t.Stop(f"訓练未达到目标级别，拒绝切图: {levels}")
    say(f"四个小号达到 {os.environ['SHITU_TARGET_LEVEL']} 级: {levels}；回城并使用内城飞鞋")
    home_and_fly(cs)
    enter_prison(cs)
    import prison_patrol
    prison_patrol.main()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        say("收到停止指令")
    except t.Stop as e:
        say(f"停止: {e}")
        raise SystemExit(1)
