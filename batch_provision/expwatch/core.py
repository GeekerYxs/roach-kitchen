"""Pure logic of the exp monitor: exp table, per-battle tracking, rolling averages, time estimates. No game access.

Exp table = client ResLib/expLib.csv, soulshift 0, column playerexp = exp needed to go from that level to the next
(46 needs 816708; the own exp read live on 2026-10-18 was 0.7-0.75 M at level 46). Copied into explib.csv.
"""
import csv
from dataclasses import dataclass
from pathlib import Path

IDLE_CLOSE = 60.0   # an ended battle with no new one this long = a pause; its cycle time is not counted


def load_table(path):
    """{level: exp needed for level -> level+1}."""
    with open(path, encoding='utf-8', newline='') as f:
        return {int(r['level']): int(r['playerexp']) for r in csv.DictReader(f)}


def gained(table, level0, exp0, level1, exp1):
    """Exp earned between two readings, across level-ups (exp restarts from the leftover). None if impossible."""
    if level1 < level0:
        return None
    if level1 == level0:
        return exp1 - exp0 if exp1 >= exp0 else None
    total = table[level0] - exp0 + exp1
    for lv in range(level0 + 1, level1):
        total += table[lv]
    return total


def remaining(table, level, exp, target):
    """Exp still needed from (level, exp) to reach level `target` with 0 exp."""
    if level >= target:
        return 0
    return table[level] - exp + sum(table[lv] for lv in range(level + 1, target))


def range_need(table, start, end):
    """Exp from start level (0 exp) to end level (0 exp)."""
    return sum(table[lv] for lv in range(start, end))


@dataclass(frozen=True)
class Sample:
    t: float            # wall time (time.time())
    in_battle: bool
    level: int
    exp: int
    map_id: int
    enemies: int = 0    # live enemies read in this sample (0 outside battle / unreadable)


@dataclass(frozen=True)
class Battle:
    role: str
    start: float        # battle start (wall time)
    fight: float        # seconds inside the battle
    cycle: float | None  # start -> next battle start (fight + walking); None = followed by a pause
    level: int          # level at battle start
    exp_before: int
    level_after: int
    exp_after: int
    gain: int
    map_id: int
    enemies: int = 0    # most live enemies seen during the battle (0 = not read)


class Tracker:
    """Feed one role's samples in time order; returns finished battles.

    A battle is finished when the next one starts (exp is credited at the battle end, before that) or after
    IDLE_CLOSE seconds without a new one. A battle already running when monitoring starts is skipped (start unknown).
    """

    def __init__(self, role, table):
        self.role, self.table = role, table
        self.last = None        # previous sample
        self.cur = None         # Sample at the start of the battle being tracked
        self.end = None         # end time of that battle, None while it runs
        self.enemies = 0        # most live enemies seen in the battle being tracked

    def feed(self, s):
        out = []
        prev, self.last = self.last, s
        if prev is None:
            return out
        if s.in_battle and not prev.in_battle:          # battle starts
            if self.cur is not None and self.end is not None:
                b = self._close(s, cycle=s.t - self.cur.t)
                if b:
                    out.append(b)
            self.cur, self.end, self.enemies = s, None, s.enemies
        elif s.in_battle and self.cur is not None and self.end is None:   # battle runs
            self.enemies = max(self.enemies, s.enemies)
        elif prev.in_battle and not s.in_battle:        # battle ends
            if self.cur is not None:
                self.end = s.t
        elif not s.in_battle and self.cur is not None and self.end is not None and s.t - self.end >= IDLE_CLOSE:
            b = self._close(s, cycle=None)
            if b:
                out.append(b)
            self.cur = self.end = None
        return out

    def _close(self, s, cycle):
        c = self.cur
        g = gained(self.table, c.level, c.exp, s.level, s.exp)
        if g is None:
            return None
        return Battle(self.role, c.t, self.end - c.t, cycle, c.level, c.exp, s.level, s.exp, g, c.map_id,
                      self.enemies)


@dataclass(frozen=True)
class Rate:
    battles: int
    avg_gain: float
    avg_fight: float
    avg_cycle: float
    per_hour: float     # exp per hour (sum gain / sum cycle)


def rate(battles):
    """Average over battles that have a cycle time; None when there are none."""
    bs = [b for b in battles if b.cycle]
    if not bs:
        return None
    cyc = sum(b.cycle for b in bs)
    gain = sum(b.gain for b in bs)
    return Rate(len(bs), gain / len(bs), sum(b.fight for b in bs) / len(bs), cyc / len(bs), gain / cyc * 3600)


def level_rates(battles):
    """{level: Rate} from battles grouped by their start level (all roles together)."""
    by = {}
    for b in battles:
        by.setdefault(b.level, []).append(b)
    return {lv: r for lv, bs in by.items() if (r := rate(bs))}


def estimate_hours(table, rates, start, end):
    """Hours from start (0 exp) to end (0 exp) using each level's own measured rate.

    Levels without data use the nearest measured level (ties -> the higher one). Returns (hours, measured levels,
    borrowed {level: from_level}) or None without any data.
    """
    if not rates:
        return None
    hours, borrowed = 0.0, {}
    for lv in range(start, end):
        src = lv if lv in rates else min(rates, key=lambda k: (abs(k - lv), -k))
        if src != lv:
            borrowed[lv] = src
        hours += table[lv] / rates[src].per_hour
    measured = [lv for lv in range(start, end) if lv not in borrowed]
    return hours, measured, borrowed


def level_ups(battles):
    """{role: {level reached: wall time}} from battles that ended with a higher level (time = battle end)."""
    out = {}
    for b in sorted(battles, key=lambda b: b.start):
        for lv in range(b.level + 1, b.level_after + 1):
            out.setdefault(b.role, {}).setdefault(lv, b.start + b.fight)
    return out


def measured_hours(ups, start, end):
    """{role: hours} for roles whose level-ups to both `start` and `end` were seen (the real elapsed time)."""
    return {role: (lv[end] - lv[start]) / 3600 for role, lv in ups.items() if start in lv and end in lv}


# ---- battles.csv (kept across runs so per-level rates use all history) ----

FIELDS = ('role', 'start', 'fight', 'cycle', 'level', 'exp_before', 'level_after', 'exp_after', 'gain', 'map_id',
          'enemies')


def to_row(b):
    return {'role': b.role, 'start': f'{b.start:.1f}', 'fight': f'{b.fight:.1f}',
            'cycle': '' if b.cycle is None else f'{b.cycle:.1f}', 'level': b.level, 'exp_before': b.exp_before,
            'level_after': b.level_after, 'exp_after': b.exp_after, 'gain': b.gain, 'map_id': b.map_id,
            'enemies': b.enemies}


def from_row(r):
    return Battle(r['role'], float(r['start']), float(r['fight']), float(r['cycle']) if r['cycle'] else None,
                  int(r['level']), int(r['exp_before']), int(r['level_after']), int(r['exp_after']), int(r['gain']),
                  int(r['map_id']), int(r.get('enemies') or 0))


def read_battles(path):
    path = Path(path)
    if not path.exists():
        return []
    with open(path, encoding='utf-8', newline='') as f:
        return [from_row(r) for r in csv.DictReader(f)]


def append_battles(path, battles):
    path = Path(path)
    new = not path.exists()
    if not new:                                   # an older file without the newer columns: rewrite it once
        with open(path, encoding='utf-8', newline='') as f:
            head = f.readline().strip().split(',')
        if tuple(head) != FIELDS:
            old = read_battles(path)
            path.unlink()
            append_battles(path, old)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, FIELDS)
        if new:
            w.writeheader()
        for b in battles:
            w.writerow(to_row(b))
