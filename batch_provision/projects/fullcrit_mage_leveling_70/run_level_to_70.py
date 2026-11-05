"""Supervise the whole no-task leveling line, level 1 -> 70, choosing the stage from the lowest apprentice level.

    python -X utf8 batch_provision/projects/fullcrit_mage_leveling_70/run_level_to_70.py

Stages (policy.LADDER): 古井10 轮回14 暗影18 八阵图24 遗忘洞穴28 通天一33 通天二43 东部遗址48 监狱53 陷阱囚牢58 禁锢之地70.
Every stage ends on the four apprentices' real levels; nothing is assumed after a fixed number of battles.

The supervisor does not give up on a failing stage. Any failure (knockout, missing member, empty soda, stuck
path-finder, a menu or shop that did not answer, an unexpected exception) leads to: recall everybody, sell,
refill, then run the stage again. Repeated failures without a level gained wait longer each time (back-off,
capped) and every third one in a row first trains one level on the next easier map (policy.RetryBook).
The recovery step itself is retried the same way.

It stops only for:
  - a client that stays unreadable (window gone / disconnected) longer than team.toml offline_wait_seconds;
  - not enough gold for a required purchase or fee (nothing automatic can fix that);
  - Ctrl+C.
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
from policy import (LADDER, FINAL_LEVEL, OFFLINE, RetryBook, backoff, classify_stop, fallback_index,
                    stage_index)
from route import ROUTES

LEADER = os.environ["SHITU_LEADER"]
ROLES = (LEADER,) + tuple(APPRENTICES)
PRISON_MAP = 264
OFFLINE_WAIT = int(os.environ.get("SHITU_OFFLINE_WAIT", "900"))
BACKOFF_BASE = int(os.environ.get("SHITU_RETRY_BACKOFF_BASE", "30"))
BACKOFF_CAP = int(os.environ.get("SHITU_RETRY_BACKOFF_CAP", "600"))
FALLBACK_AFTER = int(os.environ.get("SHITU_FALLBACK_AFTER", "3"))
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
            raise t.Stop(f"{n} 读不到等级（{OFFLINE}）")
        out[n] = lv
    return out


def offline_roles():
    """Roles whose client window / memory cannot be read right now."""
    out = []
    for n in ROLES:
        try:
            c = t.Client(n)
            if c.world() is None or w.read_level(c.mem) is None:
                out.append(n)
        except Exception:
            out.append(n)
    return out


class GiveUp(Exception):
    """The only way out of the supervisor besides Ctrl+C: offline too long, or out of gold."""


def wait_for_clients():
    """Poll every 30 s until every client is readable again; GiveUp after OFFLINE_WAIT seconds."""
    end = time.monotonic() + OFFLINE_WAIT
    while True:
        gone = offline_roles()
        if not gone:
            say("所有客户端已恢复可读，继续")
            return
        if time.monotonic() >= end:
            raise GiveUp(f"客户端 {gone} 离线超过 {OFFLINE_WAIT // 60} 分钟（网络/掉线），停止")
        say(f"客户端 {gone} 读不到（掉线或网络问题），等待恢复，最多再等 {int(end - time.monotonic())} 秒")
        time.sleep(30)


def failure_kind(exc):
    """classify_stop plus live state; non-Stop exceptions are 'offline' when a client is gone, else 'other'."""
    try:
        states = {n: t.Client(n).world() for n in ROLES}
        maps = {n: s.map_id if s else None for n, s in states.items()}
        party = set(t.Client(LEADER).team())
        expected = {t.Client(n).char_id for n in ROLES}
    except Exception as read_exc:
        say(f"读取现场状态失败：{read_exc!r}")
        return "offline", {}, set()
    if None in maps.values():
        return "offline", maps, expected - party
    if not isinstance(exc, t.Stop):
        return "other", maps, expected - party
    split = len(set(maps.values())) > 1
    return classify_stop(exc, maps_split=split, party_incomplete=party != expected), maps, expected - party


def progress():
    try:
        return sum(levels().values())
    except Exception:
        return -1


def sleep_logged(seconds, why):
    if seconds > 0:
        say(f"{why}：等待 {seconds} 秒后再试")
        time.sleep(seconds)


def recover(reason):
    """Recall, sell and refill; retried with back-off until it works (offline / out of gold excepted)."""
    attempt = 0
    while True:
        try:
            home_supply.home_and_restock(ROLES)
            return
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            cancel_leader_nav()
            kind, maps, _missing = failure_kind(exc)
            attempt += 1
            say(f"恢复步骤失败（{reason}，第 {attempt} 次）：{exc!r}；类型={kind}; maps={maps}")
            if kind == "offline":
                wait_for_clients()
                continue
            if kind == "resource":
                raise GiveUp(f"恢复时资源不足：{exc}") from exc
            sleep_logged(backoff(attempt, BACKOFF_BASE, BACKOFF_CAP), "恢复步骤重试")


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
    book = RetryBook(base=BACKOFF_BASE, cap=BACKOFF_CAP, fallback_after=FALLBACK_AFTER)
    fallback = None            # (ladder index, target level): one easier-map level before retrying
    say(f"启动 1→{FINAL_LEVEL} 练级监督；队长 {LEADER}，小号 {list(APPRENTICES)}；日志 {LOG}")
    while True:
        try:
            lv = levels()
        except t.Stop:
            wait_for_clients()
            continue
        minimum = min(lv.values())
        index = stage_index(minimum)
        if index is None:
            say(f"全员到{FINAL_LEVEL}级：{lv}；停止自动化")
            return
        if fallback and minimum >= fallback[1]:
            say(f"降档练级完成（最低等级 {minimum}），回到 {LADDER[index][0]}")
            fallback = None
        if fallback:
            name, target = LADDER[fallback[0]][0], fallback[1]
            label = f"{name}降档练至{target}"
            say(f"降档练级：{label}；四小号等级 {lv}")
            run = lambda: run_field(name, target)          # noqa: E731
        else:
            name, _map, until = LADDER[index]
            label = f"{name}至{until}"
            say(f"当前阶段：{label}；四小号等级 {lv}")
            run = lambda: run_stage(index)                  # noqa: E731
        try:
            guards.configure_revive()
            run()
            book.succeeded(label)
        except KeyboardInterrupt:
            cancel_leader_nav()
            say("收到停止信号；已取消队长寻路")
            return
        except Exception as exc:
            cancel_leader_nav()
            kind, maps, missing = failure_kind(exc)
            say(f"阶段异常：{label}: {exc!r}; 类型={kind}; maps={maps}; party_missing={sorted(missing)}")
            if kind == "offline":
                wait_for_clients()
                recover("客户端恢复后")
                continue
            if kind == "resource":
                raise GiveUp(f"资源不足，无法自动解决：{exc}") from exc
            if PRISON_MAP in maps.values() and (len(set(maps.values())) > 1 or missing):
                say("监狱接人流程自身失败且队伍不完整；兜底：全员回城后从头进入监狱")
            action = book.failed(label, progress())
            if action.fallback:
                # Failing on the easier map too goes one tier further down; the first map only backs off.
                easier = fallback_index(fallback[0] if fallback else index)
                if easier is not None:
                    fallback = (easier, minimum + 1)
                    say(f"{label} 连续 {action.streak} 次没有升级进展；先去 {LADDER[easier][0]} 练到 {minimum + 1} 级再回来")
            say(f"恢复流程（{kind}，连续第 {action.streak} 次）：全员回城，卖物，补给后重试")
            sleep_logged(action.wait, f"{label} 连续失败 {action.streak} 次")
            recover(kind)
            continue
        time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except GiveUp as exc:
        cancel_leader_nav()
        say(f"停止：{exc}")
        raise SystemExit(1)
