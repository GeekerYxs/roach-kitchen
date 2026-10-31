"""七一矿渣领工资: walk the team from the return-scroll point in 龙之都外城 along ROUTE to a goal map.

    python -X utf8 research/qiyi/go.py [--to MAP] 飞天把你射成蜂窝 舔尊 ...      (default goal: 3120 星灵神域)

ROUTE has one row per map: how to leave it. Each row was first done by hand on 飞天把你射成蜂窝 (see FLOW.md):
  map 20 龙之都外城    -> walk onto exit 10227 (663,166), crosses to map 25
  map 25 龙之都交叉口  -> 飞行平台特警 14673 (1912,180)  「请求进入」 -> map 3100
  map 3100 龙之都飞行平台 -> 阿尔法机组机长 14641 (1144,1324) 「乘坐航班」 -> map 3110 永冻群山
  map 3110 永冻群山    -> 隐藏的传送石 14616 (1016,590), stand (1112,620) 「启动传送机关」 -> map 3120 星灵神域
Restartable: every loop reads the state, does at most one action and waits for its effect.
Windows not started by our launcher get the DLL first (research/shitu/attach_tap.py, also records packets).
"""
import argparse
import sys
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'shitu'))

from common import find_roles                 # noqa: E402  (puts batch_provision/ on sys.path)
from attach_tap import attach, fresh_dll       # noqa: E402
from provisioner import native, world          # noqa: E402
from provisioner.game import Game              # noqa: E402
from provisioner.memory import ProcessMemory   # noqa: E402


@dataclass(frozen=True)
class Leg:
    stand: tuple            # where to walk in this map
    npc: int = 0            # 0 = the stand point is an exit (standing on it crosses)
    label: str = ''         # dialog option to pick
    to: int = 0             # map it leads to


# coordinates: Gemini_Prj/smsm2_game/unpacked_game_data/ResLib/AutoPath_utf8.csv / NPCDirection_utf8.csv
ROUTE = {
    20: Leg((663, 166), to=25),                              # exit 10227
    25: Leg((1912, 220), 14673, '请求进入', 3100),            # 飞行平台特警 (1912,180)
    3100: Leg((1144, 1364), 14641, '乘坐航班', 3110),         # 阿尔法机组机长 (1144,1324)
    3110: Leg((1112, 620), 14616, '启动传送机关', 3120),      # 隐藏的传送石 (1016,590); wild ground, random battles
}
GOAL = 3120
NEAR = 120                          # px: close enough to click the NPC
ON_EXIT = 30                        # px: standing on the exit, the crossing is on its way
STUCK_NAV = 5                       # s without moving while the path-finder says active


@dataclass(frozen=True)
class Action:
    kind: str           # 'done' | 'wait' | 'nav' | 'cancel' | 'click' | 'pick' | 'fail'
    args: tuple = ()
    why: str = ''


def decide(w, goal=GOAL, route=ROUTE):
    """One action from the world state (world.WorldState or None); route: map -> Leg (another stage can swap rows)."""
    if w is None:
        return Action('wait', why='角色状态读不到')
    if w.in_battle or w.verification or w.busy:
        return Action('wait', why='战斗/答题/忙')
    if w.map_id == goal:
        return Action('done', why=f'已到 map {goal}')
    if w.nav_active:
        # live 2026-10-28: a walk re-sent while standing on the exit crossed the map but stayed "active" for good
        if w.still_for >= STUCK_NAV:
            return Action('cancel', why=f'寻路 {w.still_for:.0f}s 没动，取消')
        return Action('wait', why='寻路中')
    leg = route.get(w.map_id)
    if leg is None:
        return Action('fail', why=f'不在路线上的地图 {w.map_id}')
    if not leg.npc:
        if _near(w, leg.stand, ON_EXIT):
            return Action('wait', why='站在出口上，等跨图')
        return Action('nav', (w.map_id, *leg.stand), f'去出口 -> map {leg.to}')
    if w.dialog:
        for opt, label in w.dialog.options:
            if label == leg.label:
                return Action('pick', (opt,), f'选 {leg.label}')
        return Action('fail', why=f'对话里没有「{leg.label}」: {w.dialog.options}')
    if not _near(w, leg.stand, NEAR):
        return Action('nav', (w.map_id, *leg.stand), f'去 NPC {leg.npc}')
    return Action('click', (leg.npc,), f'点 NPC {leg.npc}')


def _near(w, point, px):
    return abs(w.x - point[0]) <= px and abs(w.y - point[1]) <= px


# seconds to wait after each action before reading again; a repeat of the same click/pick means it did nothing
SETTLE = {'nav': 3, 'cancel': 1, 'click': 1.5, 'pick': 3, 'wait': 1}
MAX_REPEAT = 3
TIMEOUT = 600                       # s per window; random battles on the 永冻群山 walk add ~1 min


def run(name, pid, step):
    """Loop step(w, mem) -> Action on one window until done / fail / timeout."""
    log = lambda msg: print(f'[{name}] {msg}', flush=True)
    st = native.read_status(pid)
    session = native.Session(pid, st['hwnd'], st['game_base'])
    last, repeat, start, last_at, fight_end = None, 0, time.time(), None, 0.0
    with ProcessMemory(pid, session.base) as mem:
        game = Game(session, mem)
        try:
            while time.time() - start < TIMEOUT:
                w = world.read_world(mem)
                if w and (w.in_battle or w.busy):
                    fight_end = time.time()
                elif w:
                    # a walk stands still through a battle and goes on by itself afterwards (飞天 2026-10-28, 7 battles
                    # on the way to the 传送石): count "stuck" from the end of the last battle, not from the last step
                    w = replace(w, still_for=min(w.still_for, time.time() - fight_end))
                a = step(w, mem)
                if a.kind == 'done':
                    log(f'完成: {a.why}  map={w.map_id} ({w.x:.0f},{w.y:.0f}) 用时 {time.time() - start:.0f}s')
                    return True
                if a.kind == 'fail':
                    log(f'失败: {a.why}')
                    return False
                if a.kind != 'wait':
                    # moved or a new dialog page since the last action = it worked (the wish page repeats 「开始许愿」
                    # 8 times, only its counter text changes)
                    here = (w.x, w.y, w.dialog.text if w.dialog else '')
                    changed = last_at and (not _near(w, last_at, 50) or here[2] != last_at[2])
                    repeat = repeat + 1 if (a.kind, a.args) == last and not changed else 1
                    last_at = here
                    if repeat > MAX_REPEAT:
                        log(f'同一动作 {a.kind}{a.args} 连续 {MAX_REPEAT} 次没效果，停')
                        return False
                    last = (a.kind, a.args)
                    log(f'{a.why}: {a.kind}{a.args}  当前 map={w.map_id} ({w.x:.0f},{w.y:.0f})')
                    if a.kind == 'nav':
                        game.navigate(*a.args)
                    elif a.kind == 'cancel':
                        game.cancel_navigation()
                    elif a.kind == 'click':
                        game.click_npc(*a.args)
                    else:
                        game.select_dialog(*a.args)
                time.sleep(SETTLE[a.kind])
            log(f'超时 {TIMEOUT}s')
            return False
        finally:
            game.close()


def run_all(names, make_step):
    """Attach the DLL where missing, then run make_step() (a fresh step per window) on all windows at once."""
    found = find_roles(names)
    missing = [n for n in names if n not in found]
    if missing:
        print('没找到窗口:', missing)
        return 1
    dll = fresh_dll()
    for n in names:
        attach(n, found[n][0], dll)           # no-op re-arm when the DLL is already there
    results = {}
    threads = [threading.Thread(target=lambda n=n: results.__setitem__(n, run(n, found[n][0], make_step())))
               for n in names]
    for t in threads:
        t.start()
        time.sleep(0.5)
    for t in threads:
        t.join()
    print('结果:', {n: ('成功' if ok else '失败') for n, ok in results.items()})
    return 0 if all(results.values()) else 1


def main(argv):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--to', type=int, default=GOAL, help='goal map id (a map on ROUTE or the last one)')
    p.add_argument('names', nargs='+')
    args = p.parse_args(argv)
    return run_all(args.names, lambda: lambda w, mem: decide(w, args.to))


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
