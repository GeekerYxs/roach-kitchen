"""Stage A: a station that dropped out of the game is closed and logged in again by the supervisor itself.

2026-10-14 live: 伏地魔1 (well leader) fell back to the account/password screen after a network fault with its
process alive. The running batch only saw "leader loading" and waited out well_train_timeout (30 min); the
station stayed down until the user logged it in by hand.

Two halves, both in factory/supervisor.py:
  - watch (main thread, every few s): the station's registered process alive but no character of its own readable
    for `lost_after` s -> close that window (identity checked). The stage code of the running batch then fails at
    once ("process exited") instead of waiting.
  - relogin (the station's worker thread): its process is gone -> log in with stations.toml (+ local.toml
    passwords), enter its slot, check char id and name, register it again; failures back off up to 10 min.
Never logs in when the same character shows in a window without our DLL (that would kick the user's window), and
never while 一键登录工位.cmd is logging that station in (status 'relogin', fresh heartbeat; both sides check it).
Decisions are pure (tests/test_factory_relogin.py).
"""
from dataclasses import dataclass

from provisioner import native
from provisioner.memory import ProcessMemory
from provisioner.world import read_world

GONE, FOREIGN, LOST, OK = 'gone', 'foreign', 'lost', 'ok'
RELOGIN_STATUS = 'relogin'      # stations.status while a login of that station is in progress
RELOGIN_FRESH = 300.0           # ... trusted for this long (a crashed login must not block the station forever)
KILL_SETTLE = 5.0               # after closing a lost window, give the server this long to drop the old session
DELAYS = (30.0, 60.0, 120.0, 240.0, 600.0)


@dataclass
class Watch:
    """Per station, shared by the watcher (main thread) and the station's worker thread."""
    hwnd: int | None = None         # window of the process last seen healthy (identity check before a kill)
    lost_since: float | None = None
    fails: int = 0                  # relogins failed in a row
    next_try: float = 0.0           # monotonic; no relogin before this
    blocked: str | None = None      # relogin refused for this run (wrong character, not configured)
    warned: float = 0.0


def health(alive, has_dll, stage, char_id, expected):
    """One look at a station's registered process. char_id: what read_world shows, None = nothing readable."""
    if not alive:
        return GONE
    if not has_dll:
        return FOREIGN              # pid reused by a process we did not start: never touch it
    if stage != native.WORLD_STAGE or char_id != expected:
        return LOST
    return OK


def decide_watch(h, lost_since, now, lost_after):
    """'ok' | 'gone' | 'foreign' | 'lost' (start the clock) | 'wait' | 'kill'."""
    if h in (OK, GONE, FOREIGN):
        return h
    if lost_since is None:
        return 'lost'
    return 'kill' if now - lost_since >= lost_after else 'wait'


def may_kill(recorded_hwnd, status_hwnd, owned_by_alts):
    """The window to close must still be the station's: not one of our alt windows (pid reuse), and the same window
    we last saw healthy (when we saw it at all)."""
    if owned_by_alts:
        return False
    return recorded_hwnd is None or recorded_hwnd == status_hwnd


def relogin_delay(fails):
    """Seconds before the next relogin after `fails` failures in a row."""
    return 0.0 if fails <= 0 else DELAYS[min(fails, len(DELAYS)) - 1]


def relogin_due(h, watch, now):
    """The worker may log the station in: its process is gone (or the pid now belongs to something else),
    no back-off pending, not blocked. A live but unreadable window is the watcher's (it closes it first)."""
    return h in (GONE, FOREIGN) and watch.blocked is None and now >= watch.next_try


def other_login_running(status, heartbeat_at, now):
    """Someone (一键登录工位.cmd or the supervisor) is logging this station in right now."""
    return status == RELOGIN_STATUS and now - (heartbeat_at or 0) < RELOGIN_FRESH


def check_entered(summary, expected_char_id, expected_name):
    """EnterJob summary -> (error or None, permanent). permanent = do not try again this run (wrong character:
    the slot or the config changed; a human decides, e.g. with 一键登录工位.cmd)."""
    if not summary.get('ok'):
        return summary.get('error') or '登录/进入失败', False
    if expected_char_id and summary.get('char_id') != expected_char_id:
        return (f'进去的是 {summary.get("role")} ID={summary.get("char_id")}，不是这个工位登记的 ID={expected_char_id}'
                f'（换人请停总大脑后用 一键登录工位.cmd）'), True
    if expected_name and summary.get('role') != expected_name:
        return f'进去的是 {summary.get("role")}，不是配置的 {expected_name}', True
    return None, False


def probe(pid, expected):
    """(health, hwnd) of a station's registered process."""
    if not pid or not native.alive(pid):
        return GONE, None
    if not native.has_dll(pid):
        return FOREIGN, None
    try:
        st = native.read_status(pid)
    except OSError:
        return LOST, None
    char_id = None
    if st['stage'] == native.WORLD_STAGE:
        try:
            with ProcessMemory(pid, st['game_base']) as mem:
                w = read_world(mem)
            char_id = w.char_id if w else None
        except Exception:           # noqa: BLE001 - half-torn-down client: unreadable is the answer
            char_id = None
    return health(True, True, st['stage'], char_id, expected), st['hwnd']
