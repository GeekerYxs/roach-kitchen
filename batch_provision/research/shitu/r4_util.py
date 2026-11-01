"""Round 4 helpers for the shell stages (team per SHITU_MASTERS / SHITU_APPRENTICES).

    python -X utf8 research/shitu/r4_util.py home                 everybody leaves the team, 回城卷 unless on map 1
    python -X utf8 research/shitu/r4_util.py restock [N]          apprentices: free portal to 自由市场, 回城卷 up to N
                                                                  (default 20) at 铁公鸡, back to 逍遥村
    python -X utf8 research/shitu/r4_util.py restock_master [N]   the master: 回城卷 up to N (default 100) at 铁公鸡
    python -X utf8 research/shitu/r4_util.py supply               apprentices back to the master, 回城卷 + gold from him
    python -X utf8 research/shitu/r4_util.py double               double exp running out: 散福 3 小时 (in 逍遥村) or one 地瓜
    python -X utf8 research/shitu/r4_util.py double_due           epoch to break off for the 3 小时 (0 = all claimed)
    python -X utf8 research/shitu/r4_util.py steps QID            print every apprentice's steps of QID
    python -X utf8 research/shitu/r4_util.py need QID N           stop unless every apprentice has QID done or N steps
                                                                  (names short of it -> logs/<LOGID>_short.txt)
    python -X utf8 research/shitu/r4_util.py windows capNN:亿万M ...  master window missing -> exit 2; a missing
                                                                  apprentice window is logged in again
    python -X utf8 research/shitu/r4_util.py space [N]            apprentices: drop 0-quality junk until N free slots
    python -X utf8 research/shitu/r4_util.py relog capNN:亿万M ...    close every apprentice window, log them in again
"""
import sys
import time

import buy_scroll
import trial_run as t
from common import APPRENTICES, MASTERS
from provisioner import world as w
from quanshou import scroll
from zhuanzhi_finish import gate

MARKET = 300


def home():
    cs = [t.Client(n) for n in (MASTERS[0],) + APPRENTICES]
    for c in cs:
        c.game.cancel_navigation()
        if c.team():
            c.game.team_leave()
    time.sleep(1)

    def one(c):                        # everybody scrolls at once (user 2026-11-01)
        t.wait(lambda: not c.team(), 5, f'{c.name} 离队')
        if c.world().map_id != 1:
            scroll(c)
    t.each(cs, one)
    # the master pays one 回城卷 per home() (2026-10-28 伏地魔2 ran dry in the 古迹); and its pet's mp drinks: user
    # 2026-10-30「蓝低于50个就回城去补」, every home() checks (1980 胡萝卜汁 at 50 mp each lasted 伏地魔1 ~2.5 h)
    if buy_scroll.count(cs[0]) < 10 or buy_scroll.juice_needed(cs[0]):
        restock_master(max(60, buy_scroll.count(cs[0])))


def leave():
    cs = [t.Client(n) for n in (MASTERS[0],) + APPRENTICES]
    for c in cs:
        c.game.cancel_navigation()
        if c.team():
            c.game.team_leave()
    for c in cs:
        t.wait(lambda: not c.team(), 5, f'{c.name} 离队')


def restock(n):
    def one(name):                     # each buys its own 回城卷, all at once (user 2026-11-01)
        c = t.Client(name)
        if buy_scroll.count(c) >= n:
            return
        if c.world().map_id != MARKET:
            gate(c, 10213, (1338, 1053), 1, '自由市场', MARKET)
        buy_scroll.buy(c, n)
        gate(c, 24, (1781, 1268), MARKET, '逍遥村西区', 1)
    t.each(APPRENTICES, one)


def restock_master(n):
    """The master: 回城卷 up to n at 铁公鸡 (free portal 逍遥村 <-> 自由市场), for the next batch's supply; and the pet's
    胡萝卜汁 up to 20 x 99 when below 50 (user 2026-10-30)."""
    c = t.Client(MASTERS[0])
    juice = buy_scroll.juice_needed(c)          # 2026-10-30: the pet's mp drinks (胡萝卜汁) too, < 50 -> 20 x 99
    if buy_scroll.count(c) >= n and not juice:
        return
    if c.world().map_id != 1:
        scroll(c)
    gate(c, 10213, (1338, 1053), 1, '自由市场', MARKET)
    buy_scroll.buy(c, n)
    if juice:
        buy_scroll.buy(c, juice, buy_scroll.JUICE, buy_scroll.JUICE_SHELF, '胡萝卜汁')
    gate(c, 24, (1781, 1268), MARKET, '逍遥村西区', 1)


def supply():
    """Apprentices walk back to the master in 逍遥村, then supply_go.supply: 回城卷 + gold (state.json, once)."""
    import supply_go
    m = t.Client(MASTERS[0])
    from bai_shi import done
    need = sum(supply_go.SCROLLS for n in APPRENTICES if not done(n, 'supply_scroll'))
    if buy_scroll.count(m) < need + 5:        # 2026-10-30 曾经不曾 ran dry handing out the 3rd apprentice's 20
        restock_master(max(100, need + 5))
    for name in APPRENTICES:
        if done(name, 'supply_scroll') and done(name, 'supply_gold'):
            continue
        a = t.Client(name)
        st, ms = a.world(), m.world()
        if st.map_id != ms.map_id:
            a.game.navigate(ms.map_id, int(ms.x), int(ms.y))
            t.wait(lambda: a.world().map_id == ms.map_id and not a.world().moving, 60, f'{name} 走回 map {ms.map_id}')
        supply_go.supply(m, a)


YAM = 32004          # (御)加钙地瓜: 1 小时双倍 each
HOUR = 3600


def _when(text):
    return time.mktime(time.strptime(text, '%Y-%m-%d %H:%M:%S'))


def double_end(name):
    """Epoch when this apprentice's double exp runs out, from state.json: well10's 地瓜 (eat_32004_*), our yam_* (1 h
    each) and double3h (散福老人, its hours). Eaten / claimed while running = added on top (user: 两个地瓜 = 2 小时)."""
    from bai_shi import load_state
    ev = []
    for k, v in load_state().get(name, {}).items():
        if k.startswith('eat_32004_') or k.startswith('yam_'):
            ev.append((_when(v['time']), 1))
        elif k == 'double3h':
            ev.append((_when(v['time']), v.get('hours', 3)))
    end = 0
    for at, h in sorted(ev):
        end = max(end, at) + h * HOUR
    return end


def double_due():
    """Earliest time (epoch) an apprentice that has not claimed the 3 小时 yet can claim it (< 10 min left); 0 = none."""
    from bai_shi import done
    due = [double_end(n) - 600 for n in APPRENTICES if not done(n, 'double3h')]
    return max(min(due), time.time() + 60) if due else 0


def yam_due():
    """Earliest time (epoch) an apprentice that has claimed the 3 小时 and still has a 加钙地瓜 runs out of double exp
    (eat then, anywhere: no trip home); 0 = nobody (2026-10-28 team a: double ran out at 18:12 in the middle of
    通天塔二区, exp per battle 7300 -> 4100 for the last 35 minutes, the yams stayed in the bags)."""
    from bai_shi import done
    due = [double_end(n) for n in APPRENTICES
           if done(n, 'double3h') and w.item_count(w.read_bag(t.Client(n).mem), YAM)]
    return max(min(due), time.time() + 60) if due else 0


def stop_at(*dues):
    """The earliest of the non-zero due times (double_due / yam_due), 0 = none."""
    return min((d for d in dues if d), default=0)


def double():
    """User 2026-10-28: when the double time is (nearly) over, claim 3 小时 at 散福老人 (only from 逍遥村), afterwards
    eat one 加钙地瓜 at a time whenever the double time has run out."""
    import double_exp
    from bai_shi import done, load_state, mark

    def one(name):                     # each claims / eats for itself, all at once (user 2026-11-01)
        c = t.Client(name)
        if time.time() < double_end(name) - 600:
            return
        if not done(name, 'double3h'):
            if c.world().map_id == 1:
                double_exp.claim(c)
            return
        slot = next((s for s in w.read_bag(c.mem) if s.item_id == YAM), None)
        if slot is None:
            t.say(f'[{name}] 双倍时间到了，背包没有加钙地瓜')
            return
        c.game.use_item(slot.slot)
        try:
            t.wait(lambda: w.item_count(w.read_bag(c.mem), YAM) < slot.quantity, 5, f'{name} 吃加钙地瓜')
        except t.Stop as e:
            t.say(f'[{name}] {e}')
            return
        n = sum(k.startswith('yam_') for k in load_state().get(name, {}))
        mark(name, f'yam_{n + 1}', item=YAM)
        t.say(f'[{name}] 双倍时间到了，吃了 1 个加钙地瓜（还剩 {w.item_count(w.read_bag(c.mem), YAM)}）')
    t.each(APPRENTICES, one)


def steps(qid):
    for name in APPRENTICES:
        q = w.read_quest(t.Client(name).mem, qid)
        t.say(f'[{name}] {qid} {q}')


def _short_file():
    import os
    from pathlib import Path
    return Path(__file__).resolve().parent / 'logs' / f"{os.environ.get('LOGID', 'r4')}_short.txt"


def keep_tap(name, pid):
    """Remember a window about to be closed: mail_sell reads its tap too (mail ids are announced once)."""
    from bai_shi import mark
    mark(name, f'tap_{pid}', pid=pid)


def close_window(name, pid):
    """Close one role's window by pid alone: WM_CLOSE through the DLL's status block, or terminate the process when
    the DLL is not there."""
    from provisioner import native
    keep_tap(name, pid)
    if not native.has_dll(pid):
        return 'terminated' if native.kill(pid) else 'kill failed'
    st = native.read_status(pid)
    return native.close(native.Session(pid, st['hwnd'], st['game_base']))


def offline(name):
    """True when the role's window is up but it is out of the world: connection gone (socket -1, nothing can be
    sent) or no world state any more (back at the login screen)."""
    from common import find_roles, module_base
    from provisioner.game import NotSent
    from provisioner.memory import ProcessMemory
    found = find_roles((name,))
    if name not in found:
        return False                 # no window: the caller's other check
    pid = found[name][0]
    if w.read_world(ProcessMemory(pid, module_base(pid))) is None:
        return True
    try:
        t.Client(name).game._check_connection()
    except NotSent:
        return True
    return False


def pick_extra(pids, in_world):
    """pids = one role's windows (newest last): keep the newest one in the world (else the newest), the rest go."""
    live = [p for p in pids if in_world(p)]
    keep = (live or pids)[-1]
    return [p for p in pids if p != keep]


def duplicate_windows(names):
    """[(name, pid)] of extra windows of one role (2026-11-01 w1: a restart killed make_apprentices mid relog; its
    clients stayed up offline next to the new ones and find_roles kept picking a dead one -> 'arm' failed 5 times)."""
    from common import module_base
    from provisioner.memory import ProcessMemory
    from provisioner.procs import game_window_titles
    by = {}
    for pid, titles in game_window_titles().items():
        for n in names:
            if any(f'-{n}_' in x and '什么什么大冒险2' in x for x in titles):
                by.setdefault(n, []).append(pid)

    def in_world(pid):
        try:
            with ProcessMemory(pid, module_base(pid)) as m:
                return w.read_world(m) is not None
        except OSError:
            return False
    out = []
    for n, pids in by.items():
        if len(pids) > 1:
            out += [(n, p) for p in pick_extra(sorted(pids, key=_started), in_world)]
    return out


def _started(pid):
    """Process creation time (FILETIME ticks), 0 when unreadable: orders a role's windows oldest first."""
    import ctypes
    from ctypes import wintypes as W
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    h = k.OpenProcess(0x1000, False, pid)            # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return 0
    try:
        c, e, kt, ut = W.FILETIME(), W.FILETIME(), W.FILETIME(), W.FILETIME()
        if not k.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(kt), ctypes.byref(ut)):
            return 0
        return (c.dwHighDateTime << 32) | c.dwLowDateTime
    finally:
        k.CloseHandle(h)


def windows(accounts):
    """Before a supervisor run: the master's and the apprentices' game windows must exist. A missing apprentice is
    logged in again with make_apprentices (accounts = the batch's 'capNN:亿万M' pairs, the role already exists so it
    only enters the world); a missing master cannot be (its account is not in our config) -> Stop (exit 2)."""
    import subprocess
    from common import find_roles
    from provisioner import native
    names = (MASTERS[0],) + APPRENTICES
    found = find_roles(names)
    if MASTERS[0] not in found:
        t.say(f'师傅 {MASTERS[0]} 的窗口不在，需要人工登录')
        raise SystemExit(2)
    if offline(MASTERS[0]):          # 2026-10-28 16:16 伏地魔1: window still there, socket -1 -> every step failed
        t.say(f'师傅 {MASTERS[0]} 掉线了（窗口在、网络断开），需要人工关窗重新登录')
        raise SystemExit(2)
    extra = duplicate_windows(APPRENTICES)
    for n, pid in extra:
        t.say(f'[{n}] 多开了一个窗口 pid {pid}（重启时打断的登录留下的），关掉: {close_window(n, pid)}')
    if extra:
        time.sleep(3)
        found = find_roles(names)
    dead = [n for n in APPRENTICES if n in found and offline(n)]
    for n in dead:                   # no t.Client here: it reads char_id from the world, gone when offline (2026-10-31 亿万A4)
        t.say(f'[{n}] 掉线了，关窗重登 {close_window(n, found[n][0])}')
    if dead:
        time.sleep(3)
    lost = [n for n in APPRENTICES if n not in found or n in dead]
    if not lost:
        return
    pairs = [p for p in accounts if p.split(':')[1] in lost]
    t.say(f'徒弟窗口不在: {lost}，重新登录 {pairs}')
    subprocess.run([sys.executable, '-X', 'utf8', 'make_apprentices.py', '--anywhere', *pairs], check=True)
    for n in lost:
        c = t.Client(n)
        st = native.read_status(c.pid)
        native.arm(native.Session(c.pid, st['hwnd'], st['game_base']))
    t.say(f'徒弟重新登录好了: {lost}')


def relog(accounts, names=None):
    """Close the apprentices' windows (all, or names) and log them in again (windows()): the runner's recovery, for
    clients that look fine but are frozen (2026-10-28 亿万34 stuck mid map change for 20 minutes); team_npc uses it
    for one apprentice an NPC keeps ignoring."""
    from common import find_roles
    names = tuple(names or APPRENTICES)
    found = find_roles(names)
    for n in names:
        if n in found:
            t.say(f'[{n}] 关窗重登: {close_window(n, found[n][0])}')
    time.sleep(3)
    windows(accounts)


def need(qid, n):
    """Gate at the end of a quest step: every apprentice has qid done or at least n steps; else Stop, so the
    supervisor reruns the step (2026-10-28 亿万13 stayed at 181 step 4 through three later steps unnoticed)."""
    short = {}
    for name in APPRENTICES:
        q = w.read_quest(t.Client(name).mem, qid)
        if not q.done and len(q.steps) < n:
            short[name] = q.steps
    if short:
        _short_file().write_text(' '.join(short), encoding='utf-8')   # r4_line.py may leave these out
        raise t.Stop(f'任务 {qid} 没到第 {n} 步: {short}')
    t.say(f'任务 {qid} 全员已到第 {n} 步')


def space(n):
    t.each(APPRENTICES, lambda name: space_one(t.Client(name), n))      # each its own bag, at once (2026-11-01)


JUNK, PRANK = 0x1000, (0x802, 0x803)        # 杂物; 整人道具 (定身丸, 就看你不爽, 变身卡 ..., drop_prank.py)


def drop_order(bag, items):
    """What space_one may drop, first choice first: 0-quality 杂物, then 整人道具, then any other 杂物 (user 2026-11-01:
    蝎子王 gave no 蝎爪 to a full bag 3 times over, it held no 0-quality 杂物). Never 任务品, 辅助品 (回城卷, drinks),
    equipment or anything important."""
    def kind(s):
        it = items.get(s.item_id)
        if not it or it.important:
            return None
        if it.type == JUNK and it.quality == 0:
            return 0
        if it.type in PRANK:
            return 1
        if it.type == JUNK:
            return 2
        return None
    return sorted((s for s in bag if kind(s) is not None), key=kind)


def space_one(c, n):
    """c: drop junk (drop_order) until n free slots (battle loot refills the bag on the way: 2026-10-28 team A's
    「拾取情报」 got 物品栏已满 although the step had made 3 free)."""
    import struct
    from factory.items import load_items
    items = load_items()
    name = c.name
    from quanshou import flee
    for _ in range(10):
        flee(c)                         # 2026-10-28 亿万14: drops sent during a battle were ignored (空格 0)
        t.wait(lambda: not (s := c.world()).moving and not s.busy, 10, f'{name} 站稳')
        bag = w.read_bag(c.mem)
        free = w.read_bag_capacity(c.mem) - len(bag)
        if free >= n:
            break
        junk = drop_order(bag, items)
        if not junk:
            t.say(f'[{name}] 只剩 {free} 格空，没有杂物 / 整人道具可丢')
            break
        s = junk[0]
        t.say(f'[{name}] 空格 {free} < {n}，丢 {items[s.item_id].name} x{s.quantity}')
        c.game.send(0x48, struct.pack('<IBBH', 0, 0, s.slot, s.quantity))
        time.sleep(0.6)
    t.say(f'[{name}] 空格 {w.read_bag_capacity(c.mem) - len(w.read_bag(c.mem))}')


if __name__ == '__main__':
    a = sys.argv[1:]
    try:
        {'home': lambda: home(), 'leave': lambda: leave(), 'restock_master': lambda: restock_master(int(a[1]) if len(a) > 1 else 100), 'restock': lambda: restock(int(a[1]) if len(a) > 1 else 20),
         'steps': lambda: steps(int(a[1])), 'need': lambda: need(int(a[1]), int(a[2])), 'windows': lambda: windows(a[1:]), 'relog': lambda: relog(a[1:]), 'double': lambda: double(), 'double_due': lambda: print(int(double_due())), 'supply': lambda: supply(), 'space': lambda: space(int(a[1]) if len(a) > 1 else 3)}[a[0]]()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
