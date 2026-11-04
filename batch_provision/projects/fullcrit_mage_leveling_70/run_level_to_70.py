"""Supervise the whole no-task leveling line, level 1 -> 70, choosing the stage from the lowest apprentice level.

    python -X utf8 batch_provision/projects/fullcrit_mage_leveling_70/run_level_to_70.py

Stages (policy.LADDER): 古井10 轮回14 暗影18 八阵图24 遗忘洞穴28 通天一33 通天二43 东部遗址48 监狱53 陷阱囚牢58 禁锢之地70.
Every stage ends on the four apprentices' real levels; nothing is assumed after a fixed number of battles.

Recovery: outside prison, a knockout / missing member / split team, an empty captain soda bag or a stuck path-finder
recalls everybody, sells, refills (scrolls, pet sweets, Hannibal soda) and re-runs the active stage. At most three
recoveries per stage in a row; the count restarts as soon as the team gained a level since the last failure.
In prison, a full team is recalled the same way; a partial team stays with prison_patrol's own pickup logic.
"""
import _bootstrap  # noqa: F401
import os
import time
from datetime import datetime
from pathlib import Path

import trial_run as t
from common import APPRENTICES
from provisioner import world as w

import guards
import home_supply
from policy import LADDER, FINAL_LEVEL, RetryBook, classify_stop, stage_index
from route import ROUTES

LEADER = os.environ["SHITU_LEADER"]
ROLES = (LEADER,) + tuple(APPRENTICES)
PRISON_MAP = 264
RUNTIME = Path(__file__).with_name("runtime")
RUNTIME.mkdir(exist_ok=True)
LOG = RUNTIME / f"level_to_70_{datetime.now():%Y%m%d_%H%M%S}.log"


def say(message):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def levels():
    out = {}
    for n in APPRENTICES:
        lv = w.read_level(t.Client(n).mem)
        if lv is None:
            raise t.Stop(f"{n} 读不到等级（客户端未登录或掉线）")
        out[n] = lv
    return out


def cancel_leader_nav():
    try:
        st = t.Client(LEADER).world()
        if st and st.nav_active:
            t.Client(LEADER).game.cancel_navigation()
    except Exception as exc:          # never hide the original failure behind a second one
        say(f"取消队长寻路失败：{exc!r}")


def run_field(name, until):
    """Stages 1-7: recall + refill unless the full team is already in the map, PP鸡, then patrol to `until`."""
    import maze_train as m

    maze, legs, patrol_a, patrol_b, pp, via = ROUTES[name]
    cs = {n: t.Client(n) for n in ROLES}
    lead = cs[LEADER]
    expected = {c.char_id for c in cs.values()}
    resume = all((s := c.world()) and s.map_id == maze for c in cs.values()) and set(lead.team()) == expected
    if resume:
        say(f"完整队伍已在 {name}（map {maze}），原地续跑")
    else:
        home_supply.home_and_restock(ROLES)
        if pp:
            home_supply.pp_go(pp, via)
    m.CASTERS = (LEADER,)
    m.STAGES = (dict(name=f"{name}至{until}", maze=maze, until=until, patrol_a=patrol_a, patrol_b=patrol_b,
                     legs=legs, done_when=guards.soda_guard),)
    m.main()


def run_stage(index):
    name, _map, until = LADDER[index]
    if index < 7:
        return run_field(name, until)
    if name == "巨石之城东部遗址":
        import ruin_east_43_48 as stage
    elif name == "惊魂监狱":
        import ruin_east_to_prison as stage
    elif name == "陷阱囚牢":
        import trap_cage_53_58 as stage
    else:
        import jingu_47_70 as stage
    return stage.main()


def main():
    book = RetryBook(limit=3)
    say(f"启动 1→{FINAL_LEVEL} 练级监督；队长 {LEADER}，小号 {list(APPRENTICES)}；日志 {LOG}")
    while True:
        lv = levels()
        index = stage_index(min(lv.values()))
        if index is None:
            say(f"全员到{FINAL_LEVEL}级：{lv}；停止自动化")
            return
        name, _map, until = LADDER[index]
        label = f"{name}至{until}"
        say(f"当前阶段：{label}；四小号等级 {lv}")
        guards.configure_revive()
        try:
            run_stage(index)
            book.succeeded(label)
        except KeyboardInterrupt:
            cancel_leader_nav()
            say("收到停止信号；已取消队长寻路")
            return
        except t.Stop as exc:
            cancel_leader_nav()
            states = {n: t.Client(n).world() for n in ROLES}
            maps = {n: s.map_id if s else None for n, s in states.items()}
            party = set(t.Client(LEADER).team())
            expected = {t.Client(n).char_id for n in ROLES}
            split = len(set(maps.values())) > 1
            kind = classify_stop(exc, maps_split=split, party_incomplete=party != expected)
            say(f"阶段异常：{label}: {exc}; 类型={kind}; maps={maps}; party_missing={sorted(expected - party)}")
            if PRISON_MAP in maps.values() and (split or party != expected):
                say("异常发生在惊魂监狱且队伍不完整；保留监狱专用接人流程，不执行全员回城")
                raise
            if kind is None:
                say("该异常不属于可自动恢复的类型，停队等人工处理")
                raise
            if not book.failed(label, sum(levels().values())):
                say(f"{label} 连续自动恢复超过 {book.limit} 次且没有升级进展，停队")
                raise
            say(f"恢复流程（{kind}）：全员回城，卖物，补回城券/甜点/汽水后重走 {label}"
                f"（第 {book.count[label]} 次）")
            home_supply.home_and_restock(ROLES)
            continue
        except Exception as exc:
            cancel_leader_nav()
            say(f"未预期异常，已停队：{exc!r}")
            raise
        time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except t.Stop as exc:
        say(f"停止：{exc}")
        raise SystemExit(1)
