"""Stage B4a: a leader station that finishes no batch for too long while alts wait in its queue is closed, and the
station relogin (stage A, factory/relogin.py) logs it in again.

Why: 2026-10-20 production, a leader fell back to the login screen after a network fault with its process alive and
nobody closed it; the user stopped everything and logged in by hand. Stage A watches what the game's memory shows;
this watches what the station gets DONE, so it also catches states nobody foresaw (stuck dialog, frozen client...).

Progress = the station's own completion events in factory.db (coast_farm / well_train / well_team / transport).
The clock for a station starts at the latest of: its last completion, the supervisor start / its last relogin or
close / the last moment its window was gone or the line was draining (maintenance), and the moment alts started to
wait in its queue without a break. Limits are longer than the batch's own timeouts (coast_farm_timeout,
well_train_timeout: 30 min): a batch that runs out of time fails on its own first.
The receiver is not watched here (a full bag stops it on purpose).
Decisions are pure (tests/test_factory_progress.py).
"""
from dataclasses import dataclass

from .phase import COAST, DISPATCHER, QUEUE_COAST, QUEUE_TRANSPORT, QUEUE_WELL, WELL

KINDS = {COAST: ('coast_farm',), WELL: ('well_train', 'well_team'), DISPATCHER: ('transport',)}
QUEUES = {COAST: QUEUE_COAST, WELL: QUEUE_WELL, DISPATCHER: QUEUE_TRANSPORT}
MARGIN = 600.0          # limit = the batch's own timeouts + this
CHECK_EVERY = 30.0


@dataclass
class Track:
    since: float                        # wall time the clock was last reset (start, relogin, close, offline, drain)
    waiting_since: float | None = None  # wall time alts started to wait in the queue without a break


def default_limits(fs):
    """Seconds without progress per station role, from factory.toml batch timeouts (fs: factory.config.Settings)."""
    return {COAST: fs.coast_form_timeout + fs.coast_farm_timeout + MARGIN,
            WELL: fs.well_form_timeout + fs.well_train_timeout + MARGIN,
            DISPATCHER: fs.transport_timeout + MARGIN}


def load_limits(s, fs):
    """[supervisor] stall_minutes_coast / _well / _dispatcher (0 = off for that role) -> {role: seconds or None}."""
    floor = default_limits(fs)
    out = {}
    for role, key in ((COAST, 'stall_minutes_coast'), (WELL, 'stall_minutes_well'),
                      (DISPATCHER, 'stall_minutes_dispatcher')):
        if key not in s:
            out[role] = floor[role]
            continue
        minutes = float(s[key])
        if minutes <= 0:
            out[role] = None
            continue
        if minutes * 60 < floor[role] - MARGIN:
            raise ValueError(f'[supervisor] {key} = {minutes:g} 比这个工位一批的超时（factory.toml，'
                             f'共 {(floor[role] - MARGIN) / 60:.0f} 分钟）还短，会和批次自己的超时打架')
        out[role] = minutes * 60
    return out


def observe(track, now, alive, draining, waiting):
    """One look: the station's process alive, the line draining, how many alts wait in its queue."""
    if not alive or draining:
        track.since, track.waiting_since = now, None
        return
    if waiting <= 0:
        track.waiting_since = None
    elif track.waiting_since is None:
        track.waiting_since = now


def stalled(track, last_done, now, limit):
    """Seconds without progress while alts waited the whole time, when that reached limit; else None."""
    if limit is None or track.waiting_since is None:
        return None
    idle = now - max(last_done or 0.0, track.since, track.waiting_since)
    return idle if idle >= limit else None
