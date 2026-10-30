"""Small team operations the route needs (they were inline `python -c` blocks in r4_batch/r4_early/r4_late.sh).

    python -X utf8 -m line.ops <op> [args]        (cwd research/shitu, team from SHITU_MASTERS / SHITU_APPRENTICES)

ops: close NAME..        close these roles' windows (previous batch, same accounts)
     arm NAME..          arm the tap of these apprentices' windows
     master_up           exit 2 when the master's window is missing (nobody can log it in: not in our config)
     home_village        everybody leaves the team, 回城卷 unless already in 逍遥村 (map 1 / 8)
     q94                 apprentices with task 94 open: hand it in at NPC 308
     take224_master      the master takes task 224 at the boss (he gathers the 9 花 + 3 石 in the cave)
     gather              the master gathers 9 遗忘之花, then 暗·遗忘之花 until 3 遗忘之石 (up to 5 rounds)
     fairy               apprentices with 183 open: 梦幻岛 神仙姐姐 finishes it (转勇者), back to 逍遥村西区
     when COND..         exit 0 when COND holds, 1 when not: lv_lt N | lv_ge N | exp_ge L+E | lacks QID | master_on MAP |
                         master_off MAP.. | kills5
     level               print the lowest apprentice level
Exit: 0 ok, 1 failed (trial_run.Stop), 2 master window missing.
"""
import subprocess
import sys
import time

import trial_run as t
from common import APPRENTICES, MASTERS
from provisioner import world as w

M = MASTERS[0]


def level():
    return min(w.read_level(t.Client(n).mem) for n in APPRENTICES)


SESSION_EXP = 0xEF0          # own exp i64 into the current level (expwatch, live-checked 2026-10-18)


def read_exp(mem):
    import struct
    session = mem.u32(mem.base + w.SESSION_MGR_RVA)
    return struct.unpack('<q', mem.read(session + SESSION_EXP, 8))[0] if session else None


def reached(mem, lv, e):
    """Level above lv, or lv with >= e exp into it."""
    level = w.read_level(mem)
    return level > lv or (level == lv and (read_exp(mem) or 0) >= e)


def cond(name, *args):
    """Route conditions (Cmd.when / Step.unless)."""
    if name == 'lv_lt':
        return level() < int(args[0])
    if name == 'lv_ge':
        return level() >= int(args[0])
    if name == 'exp_ge':      # 'L+E' or 'L': every apprentice above L, or at L with >= E exp into it (route B+)
        lv, _, e = args[0].partition('+')
        return all(reached(t.Client(n).mem, int(lv), int(e or 0)) for n in APPRENTICES)
    if name == 'lacks':       # somebody has quest N neither active nor done (B+: 181 / 183 refused below 40?)
        qs = [w.read_quest(t.Client(n).mem, int(args[0])) for n in APPRENTICES]
        return any(not q.active and not q.done for q in qs)
    if name == 'master_on':
        return t.Client(M).world().map_id == int(args[0])
    if name == 'master_off':  # on none of these maps
        return t.Client(M).world().map_id not in {int(a) for a in args}
    if name == 'kills5':      # somebody still needs the 5 拳手 of 任务 24 (state mark kills5 = already counted)
        from bai_shi import done
        return any(tuple(w.read_quest(t.Client(n).mem, 24).steps) == (0, 0, 1) and not done(n, 'kills5')
                   for n in APPRENTICES)
    raise SystemExit(f'unknown condition {name}')


def close(names):
    from common import find_roles
    from provisioner import native
    found = find_roles(tuple(names))
    for n in names:
        if n in found:
            c = t.Client(n)
            st = native.read_status(c.pid)
            t.say(f'{n} close {native.close(native.Session(c.pid, st["hwnd"], st["game_base"]))}')
    time.sleep(3)


def arm(names):
    from provisioner import native
    for n in names:
        c = t.Client(n)
        st = native.read_status(c.pid)
        native.arm(native.Session(c.pid, st['hwnd'], st['game_base']))
        t.say(f'{n} armed')


def master_up():
    from common import find_roles
    from r4_util import offline
    if M not in find_roles((M,)):
        t.say(f'师傅 {M} 的窗口不在，需要人工登录')
        raise SystemExit(2)
    if offline(M):
        t.say(f'师傅 {M} 掉线了（窗口在、网络断开），需要人工关窗重新登录')
        raise SystemExit(2)


def home_village():
    from quanshou import scroll
    cs = [t.Client(n) for n in (M,) + APPRENTICES]
    for c in cs:
        c.game.cancel_navigation()
        if c.team():
            c.game.team_leave()
    time.sleep(1)
    for c in cs:
        t.wait(lambda: not c.team(), 5, f'{c.name} 离队')
        if c.world().map_id not in (1, 8):
            scroll(c)


def q94():
    from take224 import talk
    from zhuanzhi_finish import walk
    for n in APPRENTICES:
        c = t.Client(n)
        if w.read_quest(c.mem, 94).active:
            walk(c, 1, (1278, 1135), 'NPC 308')
            d = talk(c, 308, ['村庄的希望'])
            t.say(f'[{n}] 任务 94 {w.read_quest(c.mem, 94)} 对话 {t.body(d)[:40] if d else None}')
            if d:
                c.game.select_dialog(0)


def take224_master():
    import take224
    c = t.Client(M)
    take224.to_boss(c)
    take224.take(c)


def gather():
    def run(*args):
        subprocess.run([sys.executable, '-X', 'utf8', 'gather.py', M, *map(str, args)], check=True)
    run(9)
    for _ in range(5):
        stones = w.item_count(w.read_bag(t.Client(M).mem), 11151)      # 遗忘之石
        t.say(f'遗忘之石 {stones}')
        if stones >= 3:
            return
        run(3 - stones, 'dark')
    raise t.Stop('5 轮暗·遗忘之花后遗忘之石还不到 3 个')


def fairy():
    from take224 import talk
    from zhuanzhi_finish import gate, walk
    for n in APPRENTICES:
        c = t.Client(n)
        if w.read_quest(c.mem, 183).active:
            gate(c, 10213, (1338, 1053), 1, '梦幻岛', 270)
            walk(c, 270, (1374, 628), '神仙姐姐')
            talk(c, 1, ['勇者的考验', '继续', '继续', '完成转职礼', '接受奖励'])
            t.wait(lambda: w.read_quest(c.mem, 183).done, 5, f'{n} 任务 183 完成')
            t.say(f'[{n}] 183 {w.read_quest(c.mem, 183)}')
            if c.dialog():
                c.game.select_dialog(0)
            time.sleep(0.5)
        if c.world().map_id == 270:
            gate(c, 23, (954, 507), 270, '逍遥村西区', 1)


def main(argv):
    op, args = argv[0], argv[1:]
    if op == 'when':
        raise SystemExit(0 if cond(*args) else 1)
    if op == 'level':
        print(level())
        return
    fn = {'close': lambda: close(args), 'arm': lambda: arm(args), 'master_up': master_up,
          'home_village': home_village, 'q94': q94, 'take224_master': take224_master, 'gather': gather,
          'fairy': fairy}[op]
    fn()


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
