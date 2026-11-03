"""Supervise the real level 43-70 route and recover non-prison party deaths.

The earlier stages (1-43) are already complete for the current team. Route order is
1100 (to 48) -> 惊魂监狱 (to 53) -> 陷阱囚牢 (to 58) -> 禁锢之地 (to 70).
Outside prison, a knockout means recall everyone, sell the agreed junk/stones/white gear,
check supplies, then re-enter the active level band. Prison uses its dedicated re-entry logic.
"""
import _bootstrap  # noqa: F401
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
os.environ.setdefault("SHITU_LEADER", "曾经不曾")
os.environ.setdefault("SHITU_MASTERS", "曾经不曾")
os.environ.setdefault("SHITU_CASTERS", "曾经不曾")
os.environ.setdefault("SHITU_APPRENTICES", "元素使01,元素使02,元素使03,元素使04")
os.environ.setdefault("SHITU_PLAYER_SKILL", "354")
os.environ.setdefault("SHITU_PLAYER_SKILL_LEVEL", "7")
os.environ.setdefault("SHITU_STAT", "敏捷")
os.environ.setdefault("SHITU_MAX_FALLS", "1")
os.environ.setdefault("SHITU_PET_MAGIC_ONLY", "1")

import trial_run as t
from common import APPRENTICES
from provisioner import world as w

LEADER = os.environ["SHITU_LEADER"]
ROLES = (LEADER,) + tuple(APPRENTICES)
RUNTIME = Path(__file__).with_name("runtime")
RUNTIME.mkdir(exist_ok=True)
LOG = RUNTIME / f"level_43_to_70_{datetime.now():%Y%m%d_%H%M%S}.log"


def say(message):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def levels():
    return {n: w.read_level(t.Client(n).mem) for n in APPRENTICES}


def snapshots():
    return {n: t.Client(n).world() for n in ROLES}


def home_sell_and_restock():
    from line.ops import home_village
    import buy_scroll
    import sell_tradable
    import tour_level_maps_two_battles as supplies

    say("恢复流程：全员回城，卖杂物/残骸/技能石/配方/葫芦/白装")
    home_village()
    sell_tradable.main(ROLES, "junk-stones-white")

    # Count all bag slots together; helper returns every buyer to the village after topping up.
    supplies.top_up_scrolls_at_home()
    for name in ROLES:
        c = t.Client(name)
        total = buy_scroll.count(c)
        say(f"[{name}] 回城券总数={total}")
        if total < 20 and total < 50:
            raise t.Stop(f"{name} 回城券补给核验失败")

    # Keep the user's requested captain loyalty-item reserve when it falls below 250.
    c = t.Client(LEADER)
    sweets = w.item_count(w.read_bag(c.mem) or (), 8573)
    say(f"队长甜点总数={sweets}")
    if sweets < 250:
        from factory.supply import PETSHOP, ShopClient
        import log as plog
        plog.setup(t.HERE / "logs", prefix="level70_supply")
        shop = ShopClient(c.game, c.mem, plog.for_account(LEADER))
        try:
            need = 5 * 99 - sweets
            while need > 0:
                qty = min(99, need)
                if not shop.buy(PETSHOP, PETSHOP.shelf[8573], 8573, qty):
                    raise t.Stop("队长甜点购买未确认")
                need -= qty
        finally:
            shop.close()

    soda = w.item_count(w.read_bag(c.mem) or (), 8456)
    say(f"队长劲爆汽水总数={soda}")
    if soda == 0:
        raise t.Stop("队长劲爆汽水为0；已回城，须到荒芜之地一区汉尼拔补给后才能续跑")
    if soda < 599:
        raise t.Stop(f"队长劲爆汽水 {soda}<599；已回城，须到荒芜之地一区汉尼拔补到1485后才能续跑")


def run_stage(min_level):
    if min_level < 48:
        import ruin_east_43_48 as stage
        return "巨石之城东部遗址至48", stage.main
    if min_level < 53:
        import ruin_east_to_prison as stage
        return "惊魂监狱至53", stage.main
    if min_level < 58:
        import trap_cage_53_58 as stage
        return "陷阱囚牢至58", stage.main
    import jingu_47_70 as stage
    return "禁锢之地至70", stage.main


def main():
    retries = {}
    say(f"启动真实练级链；日志 {LOG}")
    while True:
        lv = levels()
        minimum = min(lv.values())
        if minimum >= 70:
            say(f"全员到70级：{lv}；停止自动化")
            return
        label, fn = run_stage(minimum)
        say(f"当前阶段：{label}；四小号等级 {lv}")
        try:
            fn()
            retries[label] = 0
        except KeyboardInterrupt:
            try:
                lead = t.Client(LEADER)
                if lead.world().nav_active:
                    lead.game.cancel_navigation()
            except Exception:
                pass
            say("收到停止信号；已取消队长寻路")
            return
        except t.Stop as exc:
            states = snapshots()
            maps = {n: s.map_id if s else None for n, s in states.items()}
            party = set(t.Client(LEADER).team())
            expected = {t.Client(n).char_id for n in ROLES}
            death_stop = any(word in str(exc) for word in ("倒下", "倒地", "knocked out"))
            fallen_or_missing = (death_stop or party != expected or len(set(maps.values())) > 1)
            say(f"阶段异常：{label}: {exc}; maps={maps}; party_missing={sorted(expected-party)}")
            if fallen_or_missing and 264 not in maps.values():
                retries[label] = retries.get(label, 0) + 1
                if retries[label] > 3:
                    raise
                home_sell_and_restock()
                say(f"全队恢复后重走阶段 {label}（第 {retries[label]} 次）")
                continue
            if 264 in maps.values():
                say("异常发生在惊魂监狱；保留监狱专用接人流程，不执行全员回城")
            raise
        except Exception as exc:
            lead = t.Client(LEADER)
            if lead.world().nav_active:
                lead.game.cancel_navigation()
            say(f"未预期异常，已停队：{exc!r}")
            raise
        time.sleep(1)


if __name__ == "__main__":
    main()
