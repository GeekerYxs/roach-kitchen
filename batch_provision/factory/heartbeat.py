"""The supervisor's heartbeat file: the guard (factory/guard.py) restarts a supervisor whose heartbeat stops.

state/supervisor_heartbeat.json = {"pid": <supervisor pid>, "at": <time.time()>, "started": <time.time()>,
                                   "info": {"dishes_hour", "waiting", "bag_full"} or null (stage B4b, guard)}
Written by the supervisor's main thread (the window manager loop): a stalled main thread (2026-10-14: 35 min with no
log line) stops the heartbeat too. Also stops a second supervisor on the same machine (two brains would pull the same
roles).
"""
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / 'state' / 'supervisor_heartbeat.json'
EVERY = 10.0            # seconds between writes
OTHER_FRESH = 600.0     # another live supervisor whose heartbeat is younger than this blocks a start


def write(path, pid, started, now=None, info=None):
    """Atomic replace; a reader holding the file a moment just skips this beat."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    try:
        tmp.write_text(json.dumps({'pid': pid, 'at': time.time() if now is None else now, 'started': started,
                                   'info': info}),
                       encoding='utf-8')
        os.replace(tmp, path)
    except OSError:
        pass


def read(path):
    """The last heartbeat as a dict, None when missing or unreadable."""
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get('pid'), int) or not isinstance(data.get('at'), (int, float)):
        return None
    return data


def other_running(beat, my_pid, now, alive):
    """pid of another supervisor that is still running (alive, heartbeat fresh), else None."""
    if beat is None or beat['pid'] == my_pid or now - beat['at'] >= OTHER_FRESH:
        return None
    return beat['pid'] if alive(beat['pid']) else None
