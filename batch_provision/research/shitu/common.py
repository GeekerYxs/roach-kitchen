"""Shared helpers for the 师徒考验 research tools: find game windows by role name, module base, paths.

Read-only except attach_tap.py (which injects a copy of bin/provision_native.dll, see there).
"""
import ctypes
import os
import sys
from ctypes import wintypes as W
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent                     # batch_provision/
sys.path.insert(0, str(ROOT))

from provisioner.procs import game_window_titles   # noqa: E402

LOGS = HERE / 'logs'
RUNTIME = HERE / 'runtime'                    # the DLL copy in HERE/bin writes tap_<pid>.jsonl here (bin\..\runtime)
BIN = HERE / 'bin'
DEFAULT_ROLES = ('mm01', '欧皇')              # title match: '-<role>' (欧皇's full name is 欧皇丨花花乀)
# this round's apprentices: env SHITU_APPRENTICES="百万1,百万2,百万3" (default = the 2026-10-27 00:25 round)
APPRENTICES = tuple(os.environ.get('SHITU_APPRENTICES', '十万1,十万2,十万3').split(','))
# the 70s in this team: env SHITU_MASTERS="伏地魔1" (round 3 runs two teams, one master each); first = the master
MASTERS = tuple(os.environ.get('SHITU_MASTERS', '伏地魔1,伏地魔2').split(','))
# progress file: env SHITU_STATE="state_r3a.json" so two teams running at once never rewrite each other's file
STATE_FILE = os.environ.get('SHITU_STATE', 'state.json')

_k = ctypes.WinDLL('kernel32', use_last_error=True)
_ps = ctypes.WinDLL('psapi', use_last_error=True)
_k.OpenProcess.restype = W.HANDLE
_k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
_k.CloseHandle.argtypes = [W.HANDLE]
_ps.EnumProcessModulesEx.argtypes = [W.HANDLE, ctypes.c_void_p, W.DWORD, ctypes.POINTER(W.DWORD), W.DWORD]
_ps.GetModuleFileNameExW.argtypes = [W.HANDLE, W.HMODULE, W.LPWSTR, W.DWORD]


def find_roles(roles=DEFAULT_ROLES):
    """{role: (pid, full window title)} for windows whose title contains '-<role>_' (the name, then _<build date>)."""
    out = {}
    for pid, titles in game_window_titles().items():
        for role in roles:
            for t in titles:
                if f'-{role}_' in t and '什么什么大冒险2' in t:      # '-亿万1' must not match '-亿万10_'
                    out[role] = (pid, t)
    return out


def modules(pid):
    """[(base, path)] of the 32-bit modules of a game process."""
    h = _k.OpenProcess(0x0410, False, pid)
    if not h:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        mods, need = (W.HMODULE * 1024)(), W.DWORD()
        if not _ps.EnumProcessModulesEx(h, mods, ctypes.sizeof(mods), ctypes.byref(need), 0x1):  # LIST_MODULES_32BIT
            raise ctypes.WinError(ctypes.get_last_error())
        out = []
        for m in mods[:need.value // ctypes.sizeof(W.HMODULE)]:
            buf = ctypes.create_unicode_buffer(520)
            _ps.GetModuleFileNameExW(h, m, buf, 520)
            out.append((m or 0, buf.value))
        return out
    finally:
        _k.CloseHandle(h)


def module_base(pid):
    return modules(pid)[0][0]
