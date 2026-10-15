"""Keep the game windows this tool started minimized ([batch] minimize = true in supervisor.toml / stations.toml,
or once in local.toml's [batch] for both).

Live 2026-10-15 (client 2.98, mvp04): every window minimized from its first second - create, login, enter, novice,
stations, well (19 battles), coast (40 battles), trades, delete-login - all passed at the usual speed; nothing in
the tool uses screen coordinates (login = key messages, the rest = memory reads + calls on the game thread).
Minimized, a window used about half the CPU and its working set dropped ~700 -> ~300 MB (commit size unchanged).

Only processes that carry our DLL (native.has_dll) are touched: a window the user opened by hand is never minimized.
A window the user restores is minimized again on the next pass. pick() is pure (tests/test_minimize.py).
"""
import ctypes
import threading
from ctypes import wintypes as W
from dataclasses import dataclass

from . import native, procs

SW_MINIMIZE = 6
GW_OWNER = 4
EVERY = 2.0             # seconds between passes; a new window shows for at most this long after its DLL loads

_u = ctypes.WinDLL('user32', use_last_error=True)
_ENUM = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
_u.EnumWindows.argtypes = [_ENUM, W.LPARAM]
_u.GetWindowThreadProcessId.argtypes = [W.HWND, ctypes.POINTER(W.DWORD)]
_u.IsWindowVisible.argtypes = [W.HWND]
_u.IsIconic.argtypes = [W.HWND]
_u.GetWindow.argtypes = [W.HWND, W.UINT]
_u.GetWindow.restype = W.HWND
_u.ShowWindowAsync.argtypes = [W.HWND, ctypes.c_int]


@dataclass(frozen=True)
class Win:
    pid: int
    hwnd: int
    iconic: bool


def pick(windows, ours):
    """The windows to minimize: top-level windows of our own processes that are not minimized yet."""
    return [w for w in windows if w.pid in ours and not w.iconic]


def top_windows(pids):
    """Visible top-level windows without an owner (the game's main window, not its dialogs) of the given pids."""
    out = []

    def visit(hwnd, _):
        pid = W.DWORD()
        _u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids and _u.IsWindowVisible(hwnd) and not _u.GetWindow(hwnd, GW_OWNER):
            out.append(Win(pid.value, hwnd, bool(_u.IsIconic(hwnd))))
        return True

    _u.EnumWindows(_ENUM(visit), 0)
    return out


def our_pids():
    return {pid for pid in procs.game_pids() if native.has_dll(pid)}


def minimize_ours():
    """One pass. -> the windows it minimized (async: it does not wait for a hung window)."""
    ours = our_pids()
    done = pick(top_windows(ours), ours)
    for w in done:
        _u.ShowWindowAsync(w.hwnd, SW_MINIMIZE)
    return done


class Minimizer:
    """A daemon thread that runs minimize_ours() every `every` seconds until stop() / the stop event is set."""

    def __init__(self, logger, stop=None, every=EVERY):
        self.log, self.every = logger, every
        self.stop_event = stop or threading.Event()
        self.thread = threading.Thread(target=self._loop, name='minimize', daemon=True)
        self.seen = set()

    def start(self):
        self.log.info('游戏窗口自动最小化: 开（每 %.0f 秒检查一次，只管本工具启动的窗口）', self.every)
        self.thread.start()
        return self

    def stop(self):
        self.stop_event.set()

    def _loop(self):
        while not self.stop_event.is_set():
            try:
                for w in minimize_ours():
                    if w.pid not in self.seen:
                        self.seen.add(w.pid)
                        self.log.info('最小化游戏窗口 pid=%d', w.pid)
            except Exception as e:      # noqa: BLE001 - never take the run down for a window chore
                self.log.warning('最小化窗口出错: %s', e)
            self.stop_event.wait(self.every)
