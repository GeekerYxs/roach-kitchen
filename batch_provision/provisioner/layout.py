"""Lay the station windows (dispatcher, well, coast, receiver leaders) out on the primary screen so they can be
watched side by side: 一键登录工位.cmd does it after its logins, the supervisor at start and after a relogin
([batch] arrange = true, the default).

Windows keep their size; only their position changes. When they do not all fit (e.g. 11 windows of 800x600 on a
2560x1440 screen) they overlap evenly and are stacked in screen order (each one above the one before it), so every
window shows its top-left part, the last one all of it. grid() prefers a grid whose visible part reaches the
window's centre (where the character stands), then the largest visible part. The user is free to move them
afterwards: nothing moves them back, except a relogin putting the new window of that one station into its slot.

The Win32 calls are bound on first use, so grid() / order() load and test on any OS (tests/test_layout.py).
"""
import ctypes
import math
import threading
from ctypes import wintypes as W

SW_SHOWNOACTIVATE = 4
SWP_NOSIZE, SWP_NOACTIVATE = 0x1, 0x10
HWND_TOP = None
MOVE_TIMEOUT = 10.0     # seconds to wait for the moves; a hung window only holds up the helper thread
SPI_GETWORKAREA = 0x30
GW_OWNER = 4
ROLE_ORDER = ('dispatcher', 'well', 'coast', 'receiver')    # left to right, top to bottom


def order(rows):
    """Station rows (station_id, role, ...) in screen order: by role, then by station id."""
    rank = {r: i for i, r in enumerate(ROLE_ORDER)}
    return sorted(rows, key=lambda r: (rank.get(r['role'], len(ROLE_ORDER)), r['station_id']))


def _steps(count, size, room):
    """Distance between neighbours: no overlap when they fit, else spread evenly over the room."""
    if count <= 1:
        return size
    return max(0, min(size, (room - size) // (count - 1)))


def grid(n, size, area):
    """Top-left corners for n windows of size (w, h) in area (left, top, right, bottom), row by row."""
    if n <= 0:
        return []
    w, h = size
    left, top, right, bottom = area
    best = None
    for cols in range(1, n + 1):
        rows = math.ceil(n / cols)
        dx, dy = _steps(cols, w, right - left), _steps(rows, h, bottom - top)
        dx, dy = min(dx, w), min(dy, h)
        score = (dx * 2 >= w and dy * 2 >= h, dx * dy, -rows)   # centre shows; visible part; fewer rows
        if best is None or score > best[0]:
            best = (score, cols, dx, dy)
    _, cols, dx, dy = best
    return [(left + (i % cols) * dx, top + (i // cols) * dy) for i in range(n)]


# ---- Win32 ----------------------------------------------------------------------------------------------

class _Placement(ctypes.Structure):
    _fields_ = [('length', W.UINT), ('flags', W.UINT), ('showCmd', W.UINT), ('ptMinPosition', W.POINT),
                ('ptMaxPosition', W.POINT), ('rcNormalPosition', W.RECT)]


_user32 = None


def _u():
    global _user32
    if _user32 is None:
        u = ctypes.WinDLL('user32', use_last_error=True)
        try:            # physical pixels on a scaled (125 % / 150 %) 2K screen, like the game windows' real size
            u.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass
        enum = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
        u.EnumWindows.argtypes = [enum, W.LPARAM]
        u.GetWindowThreadProcessId.argtypes = [W.HWND, ctypes.POINTER(W.DWORD)]
        u.IsWindowVisible.argtypes = [W.HWND]
        u.IsIconic.argtypes = [W.HWND]
        u.GetWindow.argtypes = [W.HWND, W.UINT]
        u.GetWindow.restype = W.HWND
        u.GetWindowPlacement.argtypes = [W.HWND, ctypes.POINTER(_Placement)]
        u.ShowWindow.argtypes = [W.HWND, ctypes.c_int]
        u.SetWindowPos.argtypes = [W.HWND, W.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, W.UINT]
        u.SystemParametersInfoW.argtypes = [W.UINT, W.UINT, ctypes.c_void_p, W.UINT]
        u._enum = enum
        _user32 = u
    return _user32


def main_window(pid):
    """The game's visible top-level window without an owner (not its dialogs), or None."""
    u, found = _u(), []

    def visit(hwnd, _):
        p = W.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and u.IsWindowVisible(hwnd) and not u.GetWindow(hwnd, GW_OWNER):
            found.append(hwnd)
            return False
        return True

    u.EnumWindows(u._enum(visit), 0)
    return found[0] if found else None


def _normal_size(hwnd):
    """(w, h) of the window when not minimized."""
    p = _Placement(length=ctypes.sizeof(_Placement))
    _u().GetWindowPlacement(hwnd, ctypes.byref(p))
    r = p.rcNormalPosition
    return r.right - r.left, r.bottom - r.top


def work_area():
    """(left, top, right, bottom) of the primary screen without the taskbar."""
    r = W.RECT()
    _u().SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(r), 0)
    return r.left, r.top, r.right, r.bottom


def arrange(pids, only=None):
    """Move the main windows of pids (screen order) into their grid slots; a minimized one is restored first
    (without taking the focus). A None pid (station offline) keeps its slot empty, so the others do not shift.
    only = the pids to move (default all); the slots still count every pid. Each moved window is put on top, in
    screen order, so a later one overlaps an earlier one by the grid's step only.
    -> [(pid, x, y)] moved. Waits at most MOVE_TIMEOUT: a hung window does not block the caller."""
    u = _u()
    wins = [(pid, main_window(pid) if pid else None) for pid in pids]
    sizes = [_normal_size(h) for _, h in wins if h]
    if not sizes:
        return []
    size = (max(w for w, _ in sizes), max(h for _, h in sizes))
    moves = [(pid, hwnd, x, y) for (pid, hwnd), (x, y) in zip(wins, grid(len(wins), size, work_area()))
             if hwnd and (only is None or pid in only)]

    def move():     # synchronous, one after another: the stacking order is the screen order
        for _, hwnd, x, y in moves:
            if u.IsIconic(hwnd):
                u.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
            u.SetWindowPos(hwnd, HWND_TOP, x, y, 0, 0, SWP_NOSIZE | SWP_NOACTIVATE)

    t = threading.Thread(target=move, name='layout', daemon=True)
    t.start()
    t.join(MOVE_TIMEOUT)
    return [(pid, x, y) for pid, _, x, y in moves]
