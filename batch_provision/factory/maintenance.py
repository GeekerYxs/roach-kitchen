"""Stage B2: planned server maintenance. The guard stops the line before it and brings it back afterwards.

Official notices (https://docs.qq.com/doc/DRFF6RElKd0ZETWFO, read 2026-10-21): routine maintenance every Thursday
10:00-12:00 (2026-09-30 moved to Wednesday for a holiday), login closed 5 min before, the end may be extended; logging
out before it avoids a position rollback. Ad-hoc maintenance (~1 h, e.g. 2026-10-16 18:00-19:00) can be added as a
`once` entry when announced.

Timeline of one window [start, end) (local time of this PC):
  start - drain_minutes   DRAIN  the guard writes state/drain.json; the supervisor stops pulling, logging in, deleting
                                 and rebuilding, and its leaders start no new batch (running ones go on)
  start - close_minutes   CLOSED the guard closes the supervisor and every game window of this tool (factory/guard.py)
  end                            the guard logs one alt account in to the selection screen (canary) every
                                 canary_every_minutes; the first success removes drain.json and starts the supervisor
Decisions are pure (tests/test_factory_maintenance.py).
"""
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DRAIN_PATH = ROOT / 'state' / 'drain.json'
RUN, DRAIN, CLOSED = 'run', 'drain', 'closed'
DAYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
_WEEKLY = re.compile(r'^\s*([a-z]{3})\s+(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$', re.I)
_ONCE = re.compile(r'^\s*(\d{4}-\d{1,2}-\d{1,2})\s+(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$')


@dataclass(frozen=True)
class MaintSettings:
    weekly: tuple = ()          # ((weekday 0=Mon, (h, m), (h, m)), ...)
    once: tuple = ()            # ((start datetime, end datetime), ...)
    drain: float = 600.0        # seconds before start
    close: float = 300.0        # seconds before start
    canary_every: float = 1200.0


def _hm(h, m, text):
    h, m = int(h), int(m)
    if h > 24 or m > 59 or (h == 24 and m):
        raise ValueError(f'时间不对: {text!r}')
    return h, m


def parse_weekly(text):
    """'thu 10:00-12:00' -> (3, (10, 0), (12, 0))."""
    m = _WEEKLY.match(text)
    if not m or m[1].lower() not in DAYS:
        raise ValueError(f'[maintenance] weekly 格式应为 "thu 10:00-12:00"，不是 {text!r}')
    start, end = _hm(m[2], m[3], text), _hm(m[4], m[5], text)
    if end <= start:
        raise ValueError(f'[maintenance] 结束时间要晚于开始: {text!r}')
    return DAYS.index(m[1].lower()), start, end


def parse_once(text):
    """'2026-10-16 18:00-19:00' -> (datetime, datetime)."""
    m = _ONCE.match(text)
    if not m:
        raise ValueError(f'[maintenance] once 格式应为 "2026-10-16 18:00-19:00"，不是 {text!r}')
    day = datetime.strptime(m[1], '%Y-%m-%d')
    (sh, sm), (eh, em) = _hm(m[2], m[3], text), _hm(m[4], m[5], text)
    start, end = day + timedelta(hours=sh, minutes=sm), day + timedelta(hours=eh, minutes=em)
    if end <= start:
        raise ValueError(f'[maintenance] 结束时间要晚于开始: {text!r}')
    return start, end


def load_maintenance(data):
    """[maintenance] of supervisor.toml -> MaintSettings, None when the section is missing or enabled = false."""
    m = data.get('maintenance')
    if not m or not bool(m.get('enabled', True)):
        return None
    s = MaintSettings(tuple(parse_weekly(t) for t in m.get('weekly', [])),
                      tuple(parse_once(t) for t in m.get('once', [])),
                      float(m.get('drain_minutes', 10)) * 60, float(m.get('close_minutes', 5)) * 60,
                      float(m.get('canary_every_minutes', 20)) * 60)
    if s.close > s.drain:
        raise ValueError('[maintenance] close_minutes 不能大于 drain_minutes')
    if s.canary_every < 60:
        raise ValueError('[maintenance] canary_every_minutes 至少 1')
    return s


def windows(now, s):
    """Maintenance windows (start, end) that can matter around `now` (a naive local datetime): the weekly ones of
    last, this and next week, and every once entry."""
    out = []
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    for week in (-1, 0, 1):
        for day, (sh, sm), (eh, em) in s.weekly:
            base = monday + timedelta(days=7 * week + day)
            out.append((base + timedelta(hours=sh, minutes=sm), base + timedelta(hours=eh, minutes=em)))
    out.extend(s.once)
    return sorted(out)


def phase(now, s):
    """(RUN | DRAIN | CLOSED, (start, end) of that window or None). Overlapping windows: the strongest wins."""
    best = (RUN, None)
    for start, end in windows(now, s):
        if start - timedelta(seconds=s.close) <= now < end:
            return CLOSED, (start, end)
        if start - timedelta(seconds=s.drain) <= now < end and best[0] == RUN:
            best = (DRAIN, (start, end))
    return best


def next_window(now, s):
    """The next window (start, end) that has not ended, or None."""
    return next(((a, b) for a, b in windows(now, s) if b > now), None)


# ---- state/drain.json: guard -> supervisor

def write_drain(path, until, reason):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps({'until': until, 'reason': reason}, ensure_ascii=False), encoding='utf-8')
    os.replace(tmp, path)


def clear_drain(path):
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass


def read_drain(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get('until'), (int, float)) else None


def drain_reason(data, now=None):
    """Why the supervisor must not start new work now, or None. An expired file counts as none (a crashed guard
    must not block the line forever)."""
    if data is None or (time.time() if now is None else now) >= data['until']:
        return None
    return str(data.get('reason') or '维护前收尾')
