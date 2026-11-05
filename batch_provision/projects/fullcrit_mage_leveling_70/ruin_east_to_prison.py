"""Train the four 元素使 to level 48 in map 1100, then fly to 龙之都内城 and enter 惊魂监狱.

This wrapper composes the existing 43->48 route (target overridden by SHITU_TARGET_LEVEL) with the prison patrol.
Existing characters need a valid map-24 shoe record. A fresh character without one must first use the user's
new-account route: outer-city teleporter -> 龙之都交叉口 -> talk to 铁男; when prompted, confirm only the
observed 40,000 fee, enter each character individually, and record its shoe before using this flow.
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
from common import APPRENTICES
from provisioner import world as w
from well10 import form_team

import home_supply
from policy import shoe_plan

LEADER = os.environ["SHITU_LEADER"]
SHOE_WAIT_MAX = int(os.environ.get("SHITU_SHOE_WAIT_MAX", "600"))
ROLES = (LEADER,) + APPRENTICES
CITY_MAP, CITY_SHOE = 24, (2982, 3303)
PRISON_MAP, PRISON_NPC, PRISON_XY = 264, 1339, (5660, 3258)
PICKUP = (2369, 2000)


def say(msg):
    t.say(f"[{LEADER}] {msg}")


def register_new_city_shoes(cs):
    """A fresh character cannot use a map-24 shoe record it has never made.

    Enter as a team through the established PP route, cross from the outer city to
    龙之都交叉口, use 铁男 to enter map 24, then record the shoe at the known point.
    The map transitions and each role's fee are verified before the shoe request.
    """
    import re
    import maze_train as route
    import pp_chain

    lead = cs[LEADER]
    states = {name: c.world() for name, c in cs.items()}
    if not all(st and st.map_id in (CITY_MAP, 25) for st in states.values()):
        if not all(st and st.map_id in (1, 8) for st in states.values()):
            raise t.Stop(f"新号入城路线起点地图不一致: " +
                         str({n: (s.map_id if s else None) for n, s in states.items()}))
        say("走铁男入城路线（没有内城飞鞋记录，或飞鞋冷却太久）；逐号进城并登记飞鞋")
        for c in cs.values():
            if c.name != LEADER:
                home_supply.fund_city_fee(lead, c)
        pp_chain.main("龙之都", ["平静海岸2区"])

        # The PP landing at (4050,303) is on the north side of the chain-shop door.
        # Going directly to the crossroad exit makes this client's path-finder enter
        # map 31 at (837,588). First use the verified safe outer-city waypoint.
        lead.game.navigate(20, 3863, 2027)
        t.wait(lambda: (st := lead.world()) and st.map_id == 20 and
               math.dist((st.x, st.y), (3863, 2027)) <= 120 and not st.moving and
               not st.in_battle and not st.verification,
               240, "队长绕开连锁商店入口到外城安全路点")

        route.STAGES = (dict(
            name="新号龙之都交叉口",
            goal=(25, None), maze=None, until=None, patrol_b=None,
            legs={20: ("walk", 20, (663, 166))},
        ),)
        route.main()

    def enter_one(c):
        st = c.world()
        if st.map_id == CITY_MAP:
            return
        if st.map_id != 25 or st.in_battle or st.verification:
            raise t.Stop(f"{c.name} 不在可处理的交叉口状态: {st}")
        if c.team():
            c.game.team_leave()
            t.wait(lambda: not c.team(), 5, f"{c.name} 单独办理内城入场")
        d = c.dialog()
        if not d:
            c.game.navigate(25, 294, 171)
            t.wait(lambda: (s := c.world()) and s.map_id == 25 and
                   math.dist((s.x, s.y), (294, 171)) <= 80 and not s.moving and
                   not s.in_battle and not s.verification,
                   180, f"{c.name} 到铁男 NPC 575")
            c.game.click_npc(575)
            d = t.wait(lambda: c.dialog(), 6, f"{c.name} 铁男入城菜单")
        labels = [(o, t.plain(label)) for o, label in d.options if o]
        free = [(o, label) for o, label in labels if "免费" in label and "内城" in label]
        paid = [(o, label) for o, label in labels if "缴费进入内城" in label]
        enter = [(o, label) for o, label in labels if label == "进入内城"]
        if len(free) == 1:
            c.game.select_dialog(free[0][0])
        elif len(paid) == 1:
            c.game.select_dialog(paid[0][0])
        elif len(enter) == 1:
            c.game.select_dialog(enter[0][0])
        else:
            raise t.Stop(f"{c.name} 铁男选项无法安全判定: {labels}")

        t.wait(lambda: c.world().map_id == CITY_MAP or
               ((q := c.dialog()) and
                re.search(r"40000|40,000|4万|四万", t.plain(q.text))),
               8, f"{c.name} 内城切图或铁男费用确认")
        if c.world().map_id != CITY_MAP:
            d = c.dialog()
            prompt = t.plain(d.text)
            if not re.search(r"40000|40,000|4万|四万", prompt):
                raise t.Stop(f"{c.name} 铁男费用不符合已核实的4万标准: {prompt}")
            gold = w.read_gold(c.mem)
            if gold < 40000:
                raise t.Stop(f"{c.name} 金币不足4万，拒绝确认入城: {gold}")
            confirm = [(o, t.plain(label)) for o, label in d.options
                       if o and any(word in t.plain(label) for word in ("进入", "确认", "确定"))]
            if len(confirm) != 1:
                raise t.Stop(f"{c.name} 铁男付费确认项不唯一: {d.options}")
            say(f"{c.name} 铁男确认页明确标价4万；当前金币 {gold}，确认入城")
            c.game.select_dialog(confirm[0][0])
            t.wait(lambda: c.world().map_id == CITY_MAP, 12, f"{c.name} 付费进入内城")
            say(f"{c.name} 入城金币 {gold} -> {w.read_gold(c.mem)}")

    for name, c in cs.items():
        enter_one(c)
        c.game.navigate(CITY_MAP, *CITY_SHOE)
        t.wait(lambda: (s := c.world()) and s.map_id == CITY_MAP and
               math.dist((s.x, s.y), CITY_SHOE) <= shoe_point.NEAR and
               not s.in_battle and not s.moving and not s.verification,
               240, f"{name} 到内城飞鞋登记点")
        shoe_point.record(CITY_MAP, CITY_SHOE, [name])

    form_team(lead, [cs[n] for n in APPRENTICES])
    expected = {c.char_id for c in cs.values()}
    t.wait(lambda: set(lead.team()) == expected, 10, "新号登记飞鞋后重组五人队")


def home_and_fly(cs):
    home_supply.home_and_restock(tuple(cs))
    for name, c in cs.items():
        st = c.world()
        if not st or st.map_id not in (1, 8) or st.in_battle or st.verification:
            raise t.Stop(f"{name} 回城后状态异常: {st}")
    missing_records = [n for n, c in cs.items()
                       if not shoe_point.record_ok(w.read_shoe_record(c.mem), CITY_MAP, CITY_SHOE)]
    if missing_records:
        say("缺少内城飞鞋记录的角色: " + ", ".join(missing_records))
        register_new_city_shoes(cs)
        missing_records = [n for n, c in cs.items()
                           if not shoe_point.record_ok(w.read_shoe_record(c.mem), CITY_MAP, CITY_SHOE)]
        if missing_records:
            raise t.Stop("新号入城后仍未登记成功，拒绝使用飞鞋: " + ", ".join(missing_records))

    # Everybody flew in on the shoe at the last prison entry, so a recovery within the hour finds all shoes
    # cooling. Wait for a short cooldown; for a long one pay 铁男 (40,000 each) instead of idling up to an hour.
    while True:
        left = max(shoe_point.cooldown_left(shoe_point.used_at(n), time.time()) for n in cs)
        plan = shoe_plan(left, SHOE_WAIT_MAX, has_record=True)
        if plan == "fly":
            break
        if plan == "paid":
            say(f"飞鞋最长还要冷却 {left // 60} 分，超过 {SHOE_WAIT_MAX // 60} 分钟上限，改走铁男付费入城")
            register_new_city_shoes(cs)
            return
        say(f"飞鞋还要冷却 {left // 60} 分 {left % 60} 秒，留在村里等待")
        time.sleep(min(60, max(5, left)))
    why = [x for x in (shoe_point.why_not(n, w.read_shoe_record(c.mem), shoe_point.used_at(n),
                                         time.time(), CITY_MAP, CITY_SHOE) for n, c in cs.items()) if x]
    if why:
        raise t.Stop("内城飞鞋不可用：" + "；".join(why))
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
    cs = {n: t.Client(n) for n in ROLES}
    levels = {n: w.read_level(c.mem) for n, c in cs.items() if n != LEADER}
    target = int(os.environ["SHITU_TARGET_LEVEL"])
    if not all(level >= target for level in levels.values()):
        training.main()
        levels = {n: w.read_level(c.mem) for n, c in cs.items() if n != LEADER}
    if not all(level >= int(os.environ["SHITU_TARGET_LEVEL"]) for level in levels.values()):
        raise t.Stop(f"训练未达到目标级别，拒绝切图: {levels}")
    say(f"四个小号达到 {os.environ['SHITU_TARGET_LEVEL']} 级: {levels}；回城并使用内城飞鞋")
    expected = {c.char_id for c in cs.values()}
    states = {name: c.world() for name, c in cs.items()}
    if all(st and st.map_id == PRISON_MAP for st in states.values()) and set(cs[LEADER].team()) == expected:
        say("检测到完整队伍已在惊魂监狱，原地续跑，保留当前地图与巡逻进度")
    else:
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
