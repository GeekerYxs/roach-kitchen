"""Find running game clients that carry our DLL and are in the world."""
import ctypes
import re
from ctypes import wintypes as W
from dataclasses import dataclass

from . import native
from .memory import ProcessMemory
from .world import read_world

GAME_EXE = 'waatclient.exe'
TITLE_NAME = re.compile(r'\)-(.+?)_')   # "什么什么大冒险2(①逍遥村敬老院)-mw01r1_Sep 24 2026..."


class _Entry(ctypes.Structure):
    _fields_ = [('dwSize', W.DWORD), ('cntUsage', W.DWORD), ('th32ProcessID', W.DWORD),
                ('th32DefaultHeapID', ctypes.c_size_t), ('th32ModuleID', W.DWORD), ('cntThreads', W.DWORD),
                ('th32ParentProcessID', W.DWORD), ('pcPriClassBase', ctypes.c_long), ('dwFlags', W.DWORD),
                ('szExeFile', ctypes.c_wchar * 260)]


_k = ctypes.WinDLL('kernel32', use_last_error=True)
_k.CreateToolhelp32Snapshot.restype = W.HANDLE
_k.Process32FirstW.argtypes = [W.HANDLE, ctypes.POINTER(_Entry)]
_k.Process32NextW.argtypes = [W.HANDLE, ctypes.POINTER(_Entry)]
_k.CloseHandle.argtypes = [W.HANDLE]


def game_pids():
    snap = _k.CreateToolhelp32Snapshot(0x2, 0)
    entry = _Entry(dwSize=ctypes.sizeof(_Entry))
    pids = []
    try:
        ok = _k.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == GAME_EXE:
                pids.append(entry.th32ProcessID)
            ok = _k.Process32NextW(snap, ctypes.byref(entry))
    finally:
        _k.CloseHandle(snap)
    return sorted(pids)


_u = ctypes.WinDLL('user32', use_last_error=True)
_ENUM = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
_u.EnumWindows.argtypes = [_ENUM, W.LPARAM]
_u.GetWindowThreadProcessId.argtypes = [W.HWND, ctypes.POINTER(W.DWORD)]
_u.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, ctypes.c_int]


def game_window_titles():
    """{pid: [titles]} of all game windows. Only window titles are read; no process is opened."""
    pids = set(game_pids())
    titles = {}

    def visit(hwnd, _):
        pid = W.DWORD()
        _u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids:
            buf = ctypes.create_unicode_buffer(512)
            _u.GetWindowTextW(hwnd, buf, 512)
            if buf.value:
                titles.setdefault(pid.value, []).append(buf.value)
        return True

    _u.EnumWindows(_ENUM(visit), 0)
    return titles


@dataclass(frozen=True)
class Client:
    session: native.Session
    char_id: int
    name: str
    map_id: int
    x: float
    y: float


def discover(log):
    """All in-world clients with our DLL. Others are logged and skipped."""
    found = []
    for pid in game_pids():
        if not native.has_dll(pid):
            log.warning('pid=%d 没有加载本工具的 DLL（不是用本工具启动的），跳过', pid)
            continue
        try:
            st = native.read_status(pid)
        except OSError as e:
            log.warning('pid=%d 读 DLL 状态失败（旧版 DLL？请用新版重新启动）: %s', pid, e)
            continue
        if st['stage'] != native.WORLD_STAGE:
            log.warning('pid=%d 不在游戏世界中 (stage=%d %s)，跳过', pid, st['stage'], native.STAGE.get(st['stage'], '?'))
            continue
        session = native.Session(pid, st['hwnd'], st['game_base'])
        with ProcessMemory(pid, session.base) as mem:
            w = read_world(mem)
        if not w:
            log.warning('pid=%d 读不到角色状态，跳过', pid)
            continue
        m = TITLE_NAME.search(native.window_title(session.hwnd))
        name = m.group(1) if m else f'id{w.char_id}'
        found.append(Client(session, w.char_id, name, w.map_id, w.x, w.y))
        log.info('发现 %s pid=%d 角色ID=%d 地图=%d 坐标=(%.0f,%.0f)', name, pid, w.char_id, w.map_id, w.x, w.y)
    return found
