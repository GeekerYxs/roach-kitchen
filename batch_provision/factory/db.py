"""factory.db: the single source of truth shared by every worker process (FACTORY_DESIGN.md section 7).

- alts:     one row per alt character: last observation, derived phase, ledger facts, lease, retries
- stations: resident station characters and their heartbeat
- events:   human-readable log
- stores:   料理 store characters (box07仓1 ..): one row per account + slot, filled by factory/store.py

Workers never keep "what step am I in" in memory: they write observations and read queues here.
A station claims alts with a lease; if the station stops renewing (crash, disconnect) the lease runs
out and the alts are free for another station. All times are time.time() passed in as `now`.
"""
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from .phase import DELETED, QUARANTINED, AltObs, Ledger

MAX_RETRIES = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS alts (
    char_id          INTEGER PRIMARY KEY,
    account          TEXT NOT NULL,
    slot             INTEGER NOT NULL,
    name             TEXT NOT NULL,
    phase            TEXT NOT NULL DEFAULT 'unknown',
    phase_since      REAL NOT NULL,
    reason           TEXT NOT NULL DEFAULT '',
    needs_gold       INTEGER NOT NULL DEFAULT 0,
    obs_json         TEXT,
    obs_at           REAL,
    meat_at          REAL,
    shoe_recorded_at REAL,
    shoe_used_at     REAL,
    potato_at        REAL,
    sold_at          REAL,
    pending_action   TEXT,
    pending_at       REAL,
    station_id       TEXT,
    lease_until      REAL,
    failures         INTEGER NOT NULL DEFAULT 0,
    last_error       TEXT,
    quarantined      INTEGER NOT NULL DEFAULT 0,
    created_at       REAL NOT NULL,
    deleted_at       REAL,
    release_ms       INTEGER
);
CREATE INDEX IF NOT EXISTS alts_phase ON alts(phase, phase_since);
CREATE TABLE IF NOT EXISTS stations (
    station_id   TEXT PRIMARY KEY,
    role         TEXT NOT NULL,
    char_id      INTEGER NOT NULL,
    status       TEXT NOT NULL DEFAULT '',
    heartbeat_at REAL NOT NULL,
    account      TEXT,
    name         TEXT,
    pid          INTEGER
);
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    at         REAL NOT NULL,
    char_id    INTEGER,
    station_id TEXT,
    kind       TEXT NOT NULL,
    message    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stores (
    account    TEXT NOT NULL,
    slot       INTEGER NOT NULL,
    name       TEXT NOT NULL,
    char_id    INTEGER,
    status     TEXT NOT NULL,
    free_slots INTEGER,
    capacity   INTEGER,
    map_id     INTEGER,
    x          INTEGER,
    y          INTEGER,
    error      TEXT,
    updated_at REAL NOT NULL,
    PRIMARY KEY (account, slot)
);
"""

LEDGER_FIELDS = ('meat_at', 'shoe_recorded_at', 'shoe_used_at', 'potato_at', 'sold_at')

# Columns added after a table first shipped: (table, column, type). connect() adds them to older files.
ADDED_COLUMNS = (
    ('alts', 'pending_action', 'TEXT'), ('alts', 'pending_at', 'REAL'),
    ('stations', 'account', 'TEXT'), ('stations', 'name', 'TEXT'), ('stations', 'pid', 'INTEGER'),
    ('alts', 'deleted_at', 'REAL'), ('alts', 'release_ms', 'INTEGER'), ('alts', 'sold_at', 'REAL'),
    ('stores', 'gold', 'INTEGER'), ('stores', 'potato_at', 'REAL'), ('stores', 'dishes', 'INTEGER'),
)


def _migrate(conn):
    for table, column, kind in ADDED_COLUMNS:
        have = {r['name'] for r in conn.execute(f'PRAGMA table_info({table})')}
        if column not in have:
            conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {kind}')


def connect(path):
    """One connection per thread. WAL lets readers and one writer from different processes work together."""
    if str(path) != ':memory:':
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=10000')    # first: the next statements may meet another opener's lock
    if conn.execute('PRAGMA journal_mode').fetchone()[0] != 'wal':
        conn.execute('PRAGMA journal_mode=WAL')   # persistent in the file; only the first opener switches
    conn.executescript(SCHEMA)
    with _Tx(conn):
        _migrate(conn)
    return conn


class _Tx:
    """BEGIN IMMEDIATE ... COMMIT: takes the write lock up front so check-then-update is atomic across processes."""

    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        self.conn.execute('BEGIN IMMEDIATE')
        return self.conn

    def __exit__(self, exc_type, *_):
        self.conn.execute('ROLLBACK' if exc_type else 'COMMIT')


def log_event(conn, now, kind, message, char_id=None, station_id=None):
    conn.execute('INSERT INTO events(at, char_id, station_id, kind, message) VALUES (?,?,?,?,?)',
                 (now, char_id, station_id, kind, message))


# ---- alts -------------------------------------------------------------------------------------------

def register_alt(conn, char_id, account, slot, name, now):
    conn.execute('INSERT OR IGNORE INTO alts(char_id, account, slot, name, phase_since, created_at) '
                 'VALUES (?,?,?,?,?,?)', (char_id, account, slot, name, now, now))


def alt(conn, char_id):
    return conn.execute('SELECT * FROM alts WHERE char_id=?', (char_id,)).fetchone()


def ledger(conn, char_id):
    row = alt(conn, char_id)
    if row is None:
        raise KeyError(f'alt {char_id} not registered')
    return Ledger(**{k: row[k] for k in LEDGER_FIELDS}, quarantined=bool(row['quarantined']))


def set_ledger(conn, char_id, now, **fields):
    """Record a verified action result, e.g. set_ledger(conn, cid, now, meat_at=now)."""
    bad = set(fields) - set(LEDGER_FIELDS)
    if bad:
        raise ValueError(f'unknown ledger fields {bad}')
    sets = ', '.join(f'{k}=?' for k in fields)
    conn.execute(f'UPDATE alts SET {sets} WHERE char_id=?', (*fields.values(), char_id))
    log_event(conn, now, 'ledger', json.dumps(fields), char_id=char_id)


def mark_pending(conn, char_id, action, now):
    """Written BEFORE a one-shot request is sent. If we crash before verifying, the next run knows a
    request may have gone out and checks the game instead of assuming nothing happened."""
    conn.execute('UPDATE alts SET pending_action=?, pending_at=? WHERE char_id=?', (action, now, char_id))
    log_event(conn, now, 'pending', action, char_id=char_id)


def clear_pending(conn, char_id, now, why):
    """The request was certainly not sent (stopped by the pre-send checks)."""
    conn.execute('UPDATE alts SET pending_action=NULL, pending_at=NULL WHERE char_id=?', (char_id,))
    log_event(conn, now, 'not_sent', why, char_id=char_id)


def complete_action(conn, char_id, now, **ledger_fields):
    """Verified: clear the pending mark and record the ledger facts in one transaction."""
    bad = set(ledger_fields) - set(LEDGER_FIELDS)
    if bad:
        raise ValueError(f'unknown ledger fields {bad}')
    with _Tx(conn):
        sets = ''.join(f', {k}=?' for k in ledger_fields)
        conn.execute(f'UPDATE alts SET pending_action=NULL, pending_at=NULL{sets} WHERE char_id=?',
                     (*ledger_fields.values(), char_id))
        log_event(conn, now, 'verified', json.dumps(ledger_fields), char_id=char_id)


def save_observation(conn, obs, plan, now):
    """Store the latest read and its phase. A phase change resets the retry counter."""
    with _Tx(conn):
        row = conn.execute('SELECT phase FROM alts WHERE char_id=?', (obs.char_id,)).fetchone()
        if row is None:
            raise KeyError(f'alt {obs.char_id} not registered')
        changed = row['phase'] != plan.phase
        conn.execute(
            'UPDATE alts SET obs_json=?, obs_at=?, phase=?, reason=?, needs_gold=?'
            + (', phase_since=?, failures=0, last_error=NULL' if changed else '') + ' WHERE char_id=?',
            (json.dumps(asdict(obs)), now, plan.phase, plan.reason, int(plan.needs_gold),
             *((now,) if changed else ()), obs.char_id))
        if changed:
            log_event(conn, now, 'phase', f'{row["phase"]} -> {plan.phase}: {plan.reason}', char_id=obs.char_id)
    return changed


def last_observation(conn, char_id):
    row = alt(conn, char_id)
    return AltObs(**json.loads(row['obs_json'])) if row and row['obs_json'] else None


def record_failure(conn, char_id, error, now, max_retries=MAX_RETRIES):
    """One failed attempt in the current phase. Returns True when the alt is now quarantined.
    Quarantine also drops its lease, so its team / queue slot goes to someone else."""
    with _Tx(conn):
        row = conn.execute('SELECT failures, phase FROM alts WHERE char_id=?', (char_id,)).fetchone()
        failures = row['failures'] + 1
        quarantine = failures >= max_retries
        conn.execute('UPDATE alts SET failures=?, last_error=?, quarantined=?' +
                     (', phase=?, phase_since=?, station_id=NULL, lease_until=NULL' if quarantine else '') +
                     ' WHERE char_id=?',
                     (failures, error, int(quarantine), *((QUARANTINED, now) if quarantine else ()), char_id))
        log_event(conn, now, 'quarantine' if quarantine else 'failure',
                  f'{row["phase"]} 第 {failures} 次失败: {error}', char_id=char_id)
    return quarantine


def mark_deleted(conn, char_id, now, release_ms):
    """Stage 10: the server accepted the delete. The slot really frees ~3 h later (user, 2026-10-12),
    although the server reports release_ms = 72 h."""
    with _Tx(conn):
        conn.execute('UPDATE alts SET phase=?, phase_since=?, reason=?, deleted_at=?, release_ms=?, '
                     'pending_action=NULL, pending_at=NULL, station_id=NULL, lease_until=NULL, failures=0, '
                     'last_error=NULL WHERE char_id=?',
                     (DELETED, now, '已删除，等槽位释放', now, release_ms, char_id))
        log_event(conn, now, 'deleted', f'服务器接受删除，报告 {release_ms} ms 后释放', char_id=char_id)


def mark_gone(conn, char_id, now):
    """The role is not in the server's role list any more (deleted earlier, slot already released): same record as a
    delete, so the supervisor rebuilds its successor."""
    with _Tx(conn):
        conn.execute('UPDATE alts SET phase=?, phase_since=?, reason=?, deleted_at=COALESCE(deleted_at, ?), '
                     'pending_action=NULL, pending_at=NULL, station_id=NULL, lease_until=NULL, failures=0, '
                     'last_error=NULL WHERE char_id=?', (DELETED, now, '已不在选角列表里', now, char_id))
        log_event(conn, now, 'gone', '选角列表里已没有这个角色，记为已删除', char_id=char_id)


def received(conn, char_id):
    """True when stage 9 verified that this alt's 料理 reached the receiver."""
    return conn.execute("SELECT 1 FROM events WHERE kind='receive' AND char_id=? LIMIT 1",
                        (char_id,)).fetchone() is not None


def release_quarantine(conn, char_id, now, event='release'):
    """Manual: after a human fixed the alt. Its phase is re-derived on the next observation.
    event 'release' counts as the alt's one automatic second chance (schedule.retry_quarantined); a release after a
    program fault uses another kind (factory/unquarantine.py) so the alt keeps that chance."""
    conn.execute("UPDATE alts SET quarantined=0, failures=0, last_error=NULL, phase='unknown', phase_since=? "
                 'WHERE char_id=?', (now, char_id))
    log_event(conn, now, event, '解除隔离', char_id=char_id)


# ---- queues and leases --------------------------------------------------------------------------------

def _free(now):
    return '(station_id IS NULL OR lease_until IS NULL OR lease_until < ?)', (now,)


def waiting(conn, phase, now, need_gold=None, limit=None):
    """Alts in a queue phase that no station holds, oldest first. need_gold=False -> only funded ones."""
    cond, args = _free(now)
    sql = f'SELECT * FROM alts WHERE phase=? AND quarantined=0 AND {cond}'
    params = [phase, *args]
    if need_gold is not None:
        sql += ' AND needs_gold=?'
        params.append(int(need_gold))
    sql += ' ORDER BY phase_since, char_id'
    if limit:
        sql += f' LIMIT {int(limit)}'
    return conn.execute(sql, params).fetchall()


def claim(conn, station_id, char_ids, lease_seconds, now):
    """Atomically take the given alts if they are still free or already ours (then the lease is renewed).
    Returns the char_ids actually claimed."""
    cond, args = _free(now)
    got = []
    with _Tx(conn):
        for cid in char_ids:
            cur = conn.execute(f'UPDATE alts SET station_id=?, lease_until=? WHERE char_id=? AND quarantined=0 '
                               f'AND ({cond} OR station_id=?)', (station_id, now + lease_seconds, cid, *args,
                                                                 station_id))
            if cur.rowcount:
                got.append(cid)
        if got:
            log_event(conn, now, 'claim', f'认领 {got}', station_id=station_id)
    return got


def held(conn, station_id, now):
    return conn.execute('SELECT * FROM alts WHERE station_id=? AND lease_until>=? ORDER BY char_id',
                        (station_id, now)).fetchall()


def renew(conn, station_id, char_ids, lease_seconds, now):
    """Keep the lease of the batch's own members alive while the station is working. Only these: renewing every
    alt the station holds kept the members of a batch that had failed held forever (2026-10-14 runner: 10 of 30
    windows idle for over an hour, the station's later batches renewed them every 10 s)."""
    n = 0
    with _Tx(conn):
        for cid in char_ids:
            n += conn.execute('UPDATE alts SET lease_until=? WHERE char_id=? AND station_id=? AND lease_until>=?',
                              (now + lease_seconds, cid, station_id, now)).rowcount
    return n


def release_station(conn, station_id, now, why):
    """Free every alt a station holds (its batch failed, or the station starts afresh). Its next batch claims again
    whoever it still carries (claim takes free alts)."""
    with _Tx(conn):
        freed = [r['char_id'] for r in conn.execute('SELECT char_id FROM alts WHERE station_id=?', (station_id,))]
        if freed:
            conn.execute('UPDATE alts SET station_id=NULL, lease_until=NULL WHERE station_id=?', (station_id,))
            log_event(conn, now, 'release', f'{why}: 放开 {freed}', station_id=station_id)
    return freed


def release(conn, station_id, char_ids, now):
    with _Tx(conn):
        for cid in char_ids:
            conn.execute('UPDATE alts SET station_id=NULL, lease_until=NULL WHERE char_id=? AND station_id=?',
                         (cid, station_id))
        log_event(conn, now, 'release', f'释放 {list(char_ids)}', station_id=station_id)


# ---- stations ---------------------------------------------------------------------------------------

def heartbeat(conn, station_id, role, char_id, status, now):
    conn.execute('INSERT INTO stations(station_id, role, char_id, status, heartbeat_at) VALUES (?,?,?,?,?) '
                 'ON CONFLICT(station_id) DO UPDATE SET role=excluded.role, char_id=excluded.char_id, '
                 'status=excluded.status, heartbeat_at=excluded.heartbeat_at',
                 (station_id, role, char_id, status, now))


def register_station(conn, station_id, role, char_id, account, name, pid, now):
    """After a verified login: which character plays this station, in which process. When the same station id is
    now played by another character (leader swapped in local.toml), the alts the old one still held go back to
    their queues at once instead of waiting out the lease (up to 20 min)."""
    with _Tx(conn):
        old = conn.execute('SELECT char_id, name FROM stations WHERE station_id=?', (station_id,)).fetchone()
        if old is not None and old['char_id'] != char_id:
            freed = [r['char_id'] for r in conn.execute('SELECT char_id FROM alts WHERE station_id=?', (station_id,))]
            conn.execute('UPDATE alts SET station_id=NULL, lease_until=NULL WHERE station_id=?', (station_id,))
            log_event(conn, now, 'station', f'换人: {old["name"]} ID={old["char_id"]} -> {name} ID={char_id}，'
                      f'放开旧角色占着的小号 {freed}', station_id=station_id)
        heartbeat(conn, station_id, role, char_id, 'online', now)
        conn.execute('UPDATE stations SET account=?, name=?, pid=? WHERE station_id=?',
                     (account, name, pid, station_id))
        log_event(conn, now, 'station', f'{role} 上线: {name} ID={char_id} pid={pid}', station_id=station_id)


def prune_stations(conn, keep_ids, now):
    """Forget stations no longer enabled in stations.toml (renamed id, removed, enabled = false), so the
    supervisor does not start an idle worker for them; alts they still held go back to their queues.
    -> the removed station ids."""
    gone = [r['station_id'] for r in conn.execute('SELECT station_id FROM stations')
            if r['station_id'] not in set(keep_ids)]
    with _Tx(conn):
        for sid in gone:
            conn.execute('UPDATE alts SET station_id=NULL, lease_until=NULL WHERE station_id=?', (sid,))
            conn.execute('DELETE FROM stations WHERE station_id=?', (sid,))
            log_event(conn, now, 'station', f'{sid} 已不在 stations.toml 里，删除登记', station_id=sid)
    return gone


def station(conn, station_id):
    return conn.execute('SELECT * FROM stations WHERE station_id=?', (station_id,)).fetchone()


def station_roles(conn):
    """{char_id: role} for derive_phase()."""
    return {r['char_id']: r['role'] for r in conn.execute('SELECT char_id, role FROM stations')}


# ---- stores (料理仓库号, factory/store.py) -------------------------------------------------------------

STORE_VILLAGE_READY = 'village_ready'     # 村里已腾格: sold the novice gear, ate 小肉林 / 小酒池, free slots checked
STORE_READY = 'ready'                     # 就绪: has its gold, logged out at the receiver's post (factory/storeship.py)
STORE_FULL = 'full'                       # 装满: no empty bag slot left for a 料理 stack (factory/storeuse.py)
STORE_FAILED = 'failed'


def save_store(conn, account, slot, name, status, now, char_id=None, free_slots=None, capacity=None, map_id=None,
               x=None, y=None, error=None, gold=None, dishes=None):
    """Insert or replace the row of this account + slot. A failed run keeps the char_id / bag numbers seen before."""
    old = store(conn, account, slot)
    keep = dict(old) if old and old['name'] == name else {}
    fields = dict(char_id=char_id, free_slots=free_slots, capacity=capacity, map_id=map_id, x=x, y=y, gold=gold,
                  dishes=dishes)
    fields = {k: v if v is not None else keep.get(k) for k, v in fields.items()}
    conn.execute('INSERT OR REPLACE INTO stores(account, slot, name, char_id, status, free_slots, capacity, map_id, '
                 'x, y, error, updated_at, gold, potato_at, dishes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                 (account, slot, name, fields['char_id'], status, fields['free_slots'], fields['capacity'],
                  fields['map_id'], fields['x'], fields['y'], error, now, fields['gold'], keep.get('potato_at'),
                  fields['dishes']))


def mark_store_potato(conn, account, slot, now):
    """The store role ate its one 地瓜 (stage 2b, before the well): never again."""
    conn.execute('UPDATE stores SET potato_at=? WHERE account=? AND slot=?', (now, account, slot))


def store(conn, account, slot):
    return conn.execute('SELECT * FROM stores WHERE account=? AND slot=?', (account, slot)).fetchone()


def stores(conn, account=None):
    if account is None:
        return conn.execute('SELECT * FROM stores ORDER BY account, slot').fetchall()
    return conn.execute('SELECT * FROM stores WHERE account=? ORDER BY slot', (account,)).fetchall()
