"""Stage 11a: the supervisor's decisions, pure and unit-tested (tests/test_factory_schedule.py).

The supervisor owns the alt windows (at most `max_windows`, user 2026-10-13: 20, stations not counted).
It only answers three questions; the stations do the work with the existing stage code:
  1. which side is short of alts -> pull one more role:   decide_pull()
  2. which role is that:                                   pick_roles()
  3. may a station start a batch with who is waiting now:  team_ready()
and closes windows whose alt is finished or quarantined:   close_reason().

Roles are named <account>r<slot at creation> (mw09r1 ...). After a deleted role's slot frees, the later
roles of that account move up in the selection list, so roles are always picked and entered BY NAME.
"""
import re
from dataclasses import dataclass

from .phase import (ACCEPT_QUEST, DELETE, DELETED, EAT_MEAT, FARMING, HANDIN, LEAVE_TEAM, LEVELING, NOVICE,
                    QUARANTINED, QUEUE_COAST, QUEUE_RECEIVER, QUEUE_TRANSPORT, QUEUE_WELL, RECORD_SHOE, RETURN_HOME,
                    TARGET_LEVEL, TRANSPORTING, UNKNOWN, WAIT_DISBAND)

# ---- where an open alt is in the line ----------------------------------------------------------------

UPSTREAM = 'upstream'       # below 11, waiting for the well team (novice, meat, shoe, queue)
WELL = 'well'               # in the well team
COAST_WAIT = 'coast_wait'   # 11+, on its way to / waiting for a coast team (transport, quest accept, queue)
FARMING_SIDE = 'farming'    # in a coast team
DOWNSTREAM = 'downstream'   # hand-in, receiver, delete
FINISHED = 'finished'       # deleted or quarantined: its window should close
OTHER = 'other'             # leave team / lost / unknown: still holds a window

_SIDE = {
    NOVICE: UPSTREAM, EAT_MEAT: UPSTREAM, RECORD_SHOE: UPSTREAM, QUEUE_WELL: UPSTREAM,
    LEVELING: WELL,
    QUEUE_TRANSPORT: COAST_WAIT, TRANSPORTING: COAST_WAIT, WAIT_DISBAND: COAST_WAIT, ACCEPT_QUEST: COAST_WAIT,
    QUEUE_COAST: COAST_WAIT,
    FARMING: FARMING_SIDE,
    HANDIN: DOWNSTREAM, QUEUE_RECEIVER: DOWNSTREAM, DELETE: DOWNSTREAM,
    DELETED: FINISHED, QUARANTINED: FINISHED,
}


def side(phase, level=None):
    """Which part of the line an alt in `phase` belongs to. Lost alts (return home, leave team, unknown)
    count by level once it is known: below 11 they will queue for the well, at 11+ for transport."""
    s = _SIDE.get(phase)
    if s is not None:
        return s
    if phase in (RETURN_HOME, LEAVE_TEAM, UNKNOWN) and level is not None:
        return UPSTREAM if level < TARGET_LEVEL else COAST_WAIT
    return OTHER


def count_sides(alts):
    """alts: iterable of (phase, level or None) for the OPEN alt windows -> {side: n}."""
    out = {}
    for phase, level in alts:
        s = side(phase, level)
        out[s] = out.get(s, 0) + 1
    return out


# ---- 1: pull one more role? ---------------------------------------------------------------------------

PULL_COAST = 'coast'        # a role last seen at 11+ (mostly already on 81): feeds the coast teams at once
PULL_FRESH = 'fresh'        # a role below 11 (or never seen): feeds the well team


@dataclass(frozen=True)
class PullPolicy:
    max_windows: int = 20       # open alt windows (user, 2026-10-13)
    coast_buffer: int = 4       # keep this many alts waiting for the coast teams (one team's worth)
    well_buffer: int = 4        # keep this many alts waiting for the well team (one team's worth)
    coast_backlog: int = 8      # stop feeding the well while this many already wait for the coast


@dataclass(frozen=True)
class Pull:
    kind: str | None            # PULL_COAST / PULL_FRESH / None
    reason: str


def decide_pull(counts, open_windows, policy, have_coast, have_fresh):
    """counts: count_sides() of the open alts; have_*: whether a candidate of that kind exists.
    Downstream first: the coast teams are the bottleneck, so their queue is refilled before the well's.
    The well is not fed while the coast queue is long (backpressure: windows would pile up at the coast)."""
    if open_windows >= policy.max_windows:
        return Pull(None, f'窗口已满 {open_windows}/{policy.max_windows}')
    coast_wait = counts.get(COAST_WAIT, 0)
    upstream = counts.get(UPSTREAM, 0)
    if coast_wait < policy.coast_buffer and have_coast:
        return Pull(PULL_COAST, f'海岸队列 {coast_wait} < {policy.coast_buffer}，拉一个已到 11 级的角色')
    if coast_wait >= policy.coast_backlog:
        return Pull(None, f'海岸队列已有 {coast_wait} 个（≥ {policy.coast_backlog}），暂停往古井送人')
    if upstream < policy.well_buffer and have_fresh:
        return Pull(PULL_FRESH, f'古井队列 {upstream} < {policy.well_buffer}，拉一个新角色')
    if coast_wait < policy.coast_buffer or upstream < policy.well_buffer:
        return Pull(None, '队列缺人，但没有可拉的角色')
    return Pull(None, '队列够人')


# ---- 2: which role ------------------------------------------------------------------------------------

# Last-known phases of roles worth resuming, most useful first (a role near the end frees its window soonest).
COAST_ORDER = (DELETE, QUEUE_RECEIVER, HANDIN, FARMING, QUEUE_COAST, ACCEPT_QUEST, WAIT_DISBAND, TRANSPORTING,
               QUEUE_TRANSPORT)
FRESH_ORDER = (LEVELING, QUEUE_WELL, RECORD_SHOE, EAT_MEAT, NOVICE)


@dataclass(frozen=True)
class Known:
    """A role factory.db has seen (alts row)."""
    name: str
    account: str
    phase: str
    level: int | None = None
    quarantined: bool = False
    deleted: bool = False
    since: float = 0.0          # phase_since: older first within the same phase


def _rank(k, kind):
    """Sort key of a known role for `kind`, or None when it is not a candidate of that kind."""
    if k.quarantined or k.deleted or k.phase in (DELETED, QUARANTINED):
        return None
    order = COAST_ORDER if kind == PULL_COAST else FRESH_ORDER
    if k.phase in order:
        return order.index(k.phase), k.since
    s = side(k.phase, k.level)
    if (kind == PULL_COAST and s == COAST_WAIT) or (kind == PULL_FRESH and s == UPSTREAM):
        return len(order), k.since
    return None


def pick_roles(kind, known, names_in_order, open_accounts, skip, n):
    """Up to n role names to log in, at most one per account, none of an account that already has a window.
    known: {name: Known}; names_in_order: (name, account) of every configured role, slot-major (mw09r1,
    mw10r1 ... mw100r1, mw01r2 ...); skip: names to leave alone this run (e.g. failed logins).
    PULL_COAST takes only known roles; PULL_FRESH takes known roles below 11 first, then never-seen ones."""
    ranked = sorted((r, name) for name, k in known.items() if (r := _rank(k, kind)) is not None)
    order = [name for _, name in ranked]
    if kind == PULL_FRESH:
        order += [name for name, _ in names_in_order if name not in known]
    account_of = {name: acct for name, acct in names_in_order}
    account_of.update({name: k.account for name, k in known.items()})
    out, taken = [], set(open_accounts)
    for name in order:
        if len(out) >= n:
            break
        acct = account_of.get(name)
        if acct is None or acct in taken or name in skip:
            continue
        out.append(name)
        taken.add(acct)
    return out


def has_candidate(kind, known, names_in_order, open_accounts, skip):
    return bool(pick_roles(kind, known, names_in_order, open_accounts, skip, 1))


# ---- 3: may a station start? --------------------------------------------------------------------------

def team_ready(waiting, team_size, oldest_wait, max_wait):
    """waiting: alts in the station's queue now; oldest_wait: seconds the longest of them has waited.
    A full team goes at once; a partial one after max_wait (no point idling while the queue is dry)."""
    if waiting <= 0:
        return False
    return waiting >= team_size or oldest_wait >= max_wait


# ---- 4: delete one finished role? ---------------------------------------------------------------------

def pick_delete(rows, busy_accounts, skip, open_windows, max_windows):
    """rows: (name, account) of roles in phase delete, oldest first. A delete logs the account in on the selection
    screen, which would kick any role of that account that is online, so an account with a window open (or a
    login on its way) is never touched. It also needs one window, so only when the cap leaves room.
    -> name or None."""
    if open_windows >= max_windows:
        return None
    for name, account in rows:
        if account not in busy_accounts and name not in skip:
            return name
    return None


# ---- 5: rebuild a released slot ------------------------------------------------------------------------

REBUILD_STEP = 4            # user, 2026-10-13: the role that takes a deleted rN's slot is r(N+4): r1 -> r5 -> r9


def successor(name):
    """mw01r1 -> mw01r5 (the name of the role rebuilt in the deleted role's place)."""
    m = re.match(r'^(.+?)r(\d+)$', name)
    if not m:
        raise ValueError(f'角色名不是 <账号>r<编号> 格式: {name}')
    return f'{m[1]}r{int(m[2]) + REBUILD_STEP}'


def rebuild_names(deleted, existing, free):
    """Names to create in one login. deleted: this account's deleted roles, oldest deletion first; existing: names
    already in the server's list or factory.db; free: empty slots in the server's list. A deleted role whose
    successor exists was rebuilt already."""
    out = []
    for name in deleted:
        if len(out) >= free:
            break
        new = successor(name)
        if new not in existing and new not in out:
            out.append(new)
    return out


def pick_rebuild(deleted, known_names, busy_accounts, skip_accounts, now, release_after, open_windows, max_windows):
    """deleted: (name, account, deleted_at wall time), oldest first. The account of the oldest deleted role whose
    slot should be free by now (release_after, user: ~3 h) and that has no successor yet. The login needs the
    account logged out and one window. -> account or None."""
    if open_windows >= max_windows:
        return None
    for name, account, deleted_at in deleted:
        if deleted_at is None or now - deleted_at < release_after:
            continue
        if account in busy_accounts or account in skip_accounts or successor(name) in known_names:
            continue
        return account
    return None


# ---- 6: a second chance for quarantined roles ---------------------------------------------------------

def retry_quarantined(rows, now, after):
    """Decision (2026-10-13, user asked me to choose): most quarantines are one-off glitches (mw13r1: one invite
    never arrived), so each quarantined role is released ONCE, `after` seconds after it was quarantined, and goes
    back into the line from its observed state. Quarantined a second time, it stays parked for good: never deleted
    automatically (the delete check needs a finished quest and a delivered dish, and deleting cannot be undone),
    it only costs one slot. rows: (char_id, quarantined since, earlier releases). -> char_ids to release."""
    if not after:
        return []
    return [cid for cid, since, releases in rows if releases == 0 and since is not None and now - since >= after]


# ---- closing windows ----------------------------------------------------------------------------------

def close_reason(phase, quarantined):
    """Why the supervisor should close this alt's window now, or None to keep it."""
    if phase == DELETED:
        return '已删除'
    if quarantined or phase == QUARANTINED:
        return '已隔离，关窗让出位置（解除隔离后会再被拉起）'
    return None
