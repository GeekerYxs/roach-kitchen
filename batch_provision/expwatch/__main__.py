"""Exp monitor: python -m expwatch expwatch.toml (一键经验监测.cmd). Runs until closed.

Read-only (ReadProcessMemory), works on windows without our DLL. Per role it logs every battle (exp gained, fight
seconds, cycle seconds = start to next start incl. walking), the average of the last N battles and the time to the
next levels; every few minutes a summary with each level's measured rate and the estimated hours for each range.

Own exp: i64 at session+0xEF0 (TGamePlayer = session+0xE90, so player+0x60; level u16 is player+0x70). Found live
2026-10-18 on cap07-09 (level 46): the only field that rose exactly once per battle end, +3571 per battle each,
below the 816708 the table gives for 46. Level-up reset of the field is checked by the monitor (warning if exp
ever exceeds the level's need).
"""
import ctypes
import logging
import struct
import sys
import time
import tomllib
from collections import deque
from ctypes import wintypes as W
from pathlib import Path

from provisioner import log as plog
from provisioner.memory import ProcessMemory
from provisioner.procs import game_window_titles
from provisioner.world import read_battle, read_fighter_levels
from provisioner.world import (FLAG_IN_BATTLE, ROW_FLAGS, SCENE_FIRST, SCENE_INDEX, SCENE_LAST, SCENE_ROW,
                               SESSION_LEVEL, SESSION_MAP_ID, SESSION_MGR_RVA)

from . import core

SESSION_EXP = 0xEF0
HERE = Path(__file__).resolve().parent
log = logging.getLogger('prov.expwatch')

_ps = ctypes.WinDLL('psapi', use_last_error=True)
_k = ctypes.WinDLL('kernel32', use_last_error=True)
_k.OpenProcess.restype = W.HANDLE
_k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
_k.CloseHandle.argtypes = [W.HANDLE]
_ps.EnumProcessModulesEx.argtypes = [W.HANDLE, ctypes.c_void_p, W.DWORD, ctypes.POINTER(W.DWORD), W.DWORD]


def module_base(pid):
    """Load address of the game exe (first module), without our DLL."""
    h = _k.OpenProcess(0x0410, False, pid)
    if not h:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        mods, need = (W.HMODULE * 1)(), W.DWORD()
        if not _ps.EnumProcessModulesEx(h, mods, ctypes.sizeof(mods), ctypes.byref(need), 0x1):  # LIST_MODULES_32BIT
            raise ctypes.WinError(ctypes.get_last_error())
        return mods[0]
    finally:
        _k.CloseHandle(h)


def find_pids(roles):
    """{role: pid} for roles whose window title carries '-<role>_'."""
    out = {}
    for pid, titles in game_window_titles().items():
        for role in roles:
            if any(f'-{role}_' in t for t in titles):
                out[role] = pid
    return out


def read_sample(mem):
    session = mem.u32(mem.base + SESSION_MGR_RVA)
    if not session:
        return None
    index = struct.unpack('<i', mem.read(session + SCENE_INDEX, 4))[0]
    first, last = mem.u32(session + SCENE_FIRST), mem.u32(session + SCENE_LAST)
    if not first or index < 0 or index >= (last - first) // SCENE_ROW:
        return None
    flags = mem.u32(first + index * SCENE_ROW + ROW_FLAGS)
    level = struct.unpack('<H', mem.read(session + SESSION_LEVEL, 2))[0]
    exp = struct.unpack('<q', mem.read(session + SESSION_EXP, 8))[0]
    if not level:
        return None
    in_battle = bool(flags & FLAG_IN_BATTLE)
    enemies, levels = 0, ()
    if in_battle:
        try:
            b = read_battle(mem)
            if b:
                enemies = len(b.enemies)
                levels = tuple(sorted(lv for lv in read_fighter_levels(mem, b.enemies) or () if lv))
        except Exception:              # battle object half built / torn down: nothing read in this sample
            enemies, levels = 0, ()
    return core.Sample(time.time(), in_battle, level, exp, mem.u32(session + SESSION_MAP_ID), enemies, levels)


def hours(h):
    if h is None:
        return '?'
    return f'{h * 60:.0f}分' if h < 1 else f'{h:.2f}时'


def wan(n):
    return f'{n / 10000:.1f}万'


class Role:
    def __init__(self, name, table, window, history):
        self.name, self.table = name, table
        self.tracker = core.Tracker(name, table)
        self.recent = deque(history[-window:], maxlen=window)
        self.mem = None
        self.count = 0
        self.last = None
        self.warned_exp = False


def battle_line(r, b, ranges):
    table = r.table
    rt = core.rate(r.recent)
    cyc = '暂停' if b.cycle is None else f'{b.cycle:.1f}s'
    up = f' 升到{b.level_after}级!' if b.level_after > b.level else ''
    s = (f'{r.name} {b.level}级 第{r.count}场 +{b.gain} 经验 战斗{b.fight:.1f}s 一场{cyc}{up} 地图{b.map_id}'
         f'{core.enemy_text(b.enemy_levels)} | '
         f'本级 {b.exp_after}/{table[b.level_after]} ({b.exp_after / table[b.level_after]:.1%})')
    if rt and rt.per_hour > 0:      # 0 when the recent battles gave no exp (lv41 after 出师): no estimate
        s += (f' | 近{rt.battles}场 均{rt.avg_gain:.0f}/场 战斗{rt.avg_fight:.1f}s 一场{rt.avg_cycle:.1f}s '
              f'{wan(rt.per_hour)}/时')
        need = table[b.level_after] - b.exp_after
        s += f' | 升{b.level_after + 1}还要 {hours(need / rt.per_hour)}'
        for _, end in ranges:
            if end > b.level_after + 1:
                s += f' 到{end}级 {hours(core.remaining(table, b.level_after, b.exp_after, end) / rt.per_hour)}'
    return s


def summary(table, battles, ranges, roles):
    lines = ['==== 汇总（全部历史，三个号合计）====']
    rates = core.level_rates(battles)
    for lv in sorted(rates):
        r = rates[lv]
        lines.append(f'  {lv}级: {r.battles}场 均{r.avg_gain:.0f}/场 战斗{r.avg_fight:.1f}s 一场{r.avg_cycle:.1f}s '
                     f'{wan(r.per_hour)}/时 -> 这一级从0升满 {hours(table[lv] / r.per_hour)}')
    ups = core.level_ups(battles)
    for start, end in ranges:
        est = core.estimate_hours(table, rates, start, end)
        need = core.range_need(table, start, end)
        if est is None:
            lines.append(f'  {start}->{end}级 (共{wan(need)}经验): 还没数据')
            continue
        h, measured, borrowed = est
        note = '全部实测' if not borrowed else (
            '借用: ' + ' '.join(f'{lv}级用{src}级的速度' for lv, src in borrowed.items()))
        lines.append(f'  {start}->{end}级 (共{wan(need)}经验): 预计 {hours(h)}  [{note}]')
        real = core.measured_hours(ups, start, end)
        if real:
            lines.append('    实际用时: ' + ' '.join(f'{k} {hours(v)}' for k, v in sorted(real.items())))
    for r in roles:
        if r.last:
            lines.append(f'  {r.name}: 现在 {r.last.level}级 {r.last.exp}/{table[r.last.level]} '
                         f'({r.last.exp / table[r.last.level]:.1%}) 地图{r.last.map_id}')
    return '\n'.join(lines)


def run(cfg_path):
    cfg = tomllib.loads(Path(cfg_path).read_text(encoding='utf-8'))
    base = Path(cfg_path).resolve().parent
    plog.setup(base / 'logs', 'expwatch')
    table = core.load_table(HERE / 'explib.csv')
    csv_path = base / cfg.get('battles_csv', 'logs/expwatch/battles.csv')
    ranges = [tuple(x) for x in cfg.get('ranges', [[45, 50], [50, 55]])]
    window, poll = int(cfg.get('window', 15)), float(cfg.get('poll_seconds', 0.5))
    every = float(cfg.get('summary_minutes', 10)) * 60
    history = core.read_battles(csv_path)
    log.info('经验监测启动: %s, 近%d场均值, 历史 %d 场 (%s)', ' '.join(cfg['roles']), window, len(history), csv_path)
    roles = [Role(n, table, window, [b for b in history if b.role == n]) for n in cfg['roles']]
    for r in roles:
        r.count = sum(1 for b in history if b.role == r.name)
    next_find, next_summary = 0.0, time.time() + 60
    while True:
        now = time.time()
        if now >= next_find and any(r.mem is None for r in roles):
            pids = find_pids([r.name for r in roles if r.mem is None])
            for r in roles:
                if r.mem is None and r.name in pids:
                    pid = pids[r.name]
                    try:
                        r.mem = ProcessMemory(pid, module_base(pid))
                        r.tracker = core.Tracker(r.name, table)   # start clean: the old battle is unknown
                        log.info('%s 找到窗口 pid=%d', r.name, pid)
                    except OSError as e:
                        log.warning('%s pid=%d 打不开: %s', r.name, pid, e)
            next_find = now + 10
        done = []
        for r in roles:
            if r.mem is None:
                continue
            try:
                s = read_sample(r.mem)
            except (RuntimeError, OSError) as e:
                log.warning('%s 读内存失败（窗口关了？）: %s，10 秒后重新找', r.name, e)
                r.mem.close()
                r.mem = None
                continue
            if s is None:
                continue
            if not r.warned_exp and s.exp > table.get(s.level, 1 << 62):
                log.warning('%s 经验 %d 超过 %d 级所需 %d：经验地址可能不对', r.name, s.exp, s.level, table[s.level])
                r.warned_exp = True
            if r.last and s.level > r.last.level:
                log.info('%s 升级 %d -> %d，升级后经验 %d', r.name, r.last.level, s.level, s.exp)
            r.last = s
            for b in r.tracker.feed(s):
                r.count += 1
                r.recent.append(b)
                done.append(b)
                history.append(b)
                log.info(battle_line(r, b, ranges))
        if done:
            core.append_battles(csv_path, done)
        if now >= next_summary:
            log.info(summary(table, history, ranges, roles))
            next_summary = now + every
        time.sleep(poll)


if __name__ == '__main__':
    try:
        run(sys.argv[1] if len(sys.argv) > 1 else 'expwatch.toml')
    except KeyboardInterrupt:
        pass
