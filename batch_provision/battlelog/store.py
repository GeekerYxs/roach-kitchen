"""SQLite store of decoded battles (logs/battlelog/battles.sqlite). One row per battle and tap file, raw packet bodies
included, so fields decoded later can be recomputed from history. Re-importing a file replaces its rows."""
import bisect
import json
import sqlite3
from collections import Counter
from pathlib import Path

from . import decode

DECODER = 1         # bump when decode.py reads a field differently; rows keep the version they were made with

SCHEMA = """
create table if not exists sources (
    path text primary key, pid integer, size integer, mtime real, anchor real, battles integer, imported_at real
);
create table if not exists battles (
    id integer primary key,
    source text not null, pid integer, char_id integer, role text,
    start_tick integer not null, end_tick integer,
    start_time real, end_time real,     -- wall time: file mtime minus the ms to its last record
    fight_s real, patrol_s real,        -- 0x4100 -> own 0x472A; previous 0x472A -> 0x4100 (null for a file's first)
    map_id integer, x integer, y integer,
    level integer, level_after integer,     -- level: from a teammate's lineup (null when solo / no teammate file)
    own_pos integer, own_pet_pos integer,
    exp integer, pet_exp integer, pet_training integer, potential integer,
    monster_count integer, monster_levels text,     -- 'a b c' ascending
    monsters text, pets text, players text, items text,   -- json
    packet_count integer, opcodes text,             -- json {hex opcode: count} of the packets inside the battle
    raw_map blob, raw_lineup blob, raw_result blob, packets blob,   -- packets: decode.pack_packets, t0 = start_tick
    errors text, decoder integer,
    unique (source, start_tick)
);
create index if not exists battles_role on battles (role, start_time);
create index if not exists battles_map on battles (map_id, level);
"""

COLUMNS = ('source', 'pid', 'char_id', 'role', 'start_tick', 'end_tick', 'start_time', 'end_time', 'fight_s',
           'patrol_s', 'map_id', 'x', 'y', 'level', 'level_after', 'own_pos', 'own_pet_pos', 'exp', 'pet_exp', 'pet_training', 'potential',
           'monster_count', 'monster_levels', 'monsters', 'pets', 'players', 'items', 'packet_count', 'opcodes',
           'raw_map', 'raw_lineup', 'raw_result', 'packets', 'errors', 'decoder')


def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    return db


def _units(units):
    return json.dumps([[u.npc_id, u.level, u.pos, u.hp_max] for u in units])


def to_row(b, source, pid, anchor):
    """Battle -> {column: value}. anchor = wall time of tick 0 (None = unknown)."""
    wall = (lambda t: None if t is None or anchor is None else anchor + t / 1000)
    lu, r = b.lineup, b.result
    monsters = lu.monsters if lu else ()
    return {
        'source': source, 'pid': pid, 'char_id': b.own_id, 'role': None,
        'start_tick': b.start_tick, 'end_tick': b.end_tick,
        'start_time': wall(b.start_tick), 'end_time': wall(b.end_tick),
        'fight_s': None if b.end_tick is None else (b.end_tick - b.start_tick) / 1000,
        'patrol_s': None if b.patrol_ms is None else b.patrol_ms / 1000,
        'map_id': b.map_id, 'x': b.x, 'y': b.y,
        'level': None, 'level_after': b.level_after,
        'own_pos': lu.own_pos if lu else None, 'own_pet_pos': lu.own_pet_pos if lu else None,
        'exp': r.exp if r else None, 'pet_exp': r.pet_exp if r else None,
        'pet_training': r.pet_training if r else None, 'potential': r.potential if r else None,
        'monster_count': len(monsters) if lu else None,
        'monster_levels': ' '.join(str(x) for x in sorted(m.level for m in monsters)) if lu else None,
        'monsters': _units(monsters) if lu else None,
        'pets': _units(u for u in lu.units if u.kind == decode.UNIT_PET) if lu else None,
        'players': json.dumps([[p.char_id, p.name, p.level, p.pos, p.hp_max] for p in lu.players],
                              ensure_ascii=False) if lu else None,
        'items': json.dumps([[i.item_id, i.qty, i.slot] for i in r.items]) if r else None,
        'packet_count': len(b.packets),
        'opcodes': json.dumps(dict(sorted(Counter(f'{p.direction}:{p.opcode:#06x}' for p in b.packets).items()))),
        'raw_map': b.raw_map or None, 'raw_lineup': b.raw_lineup or None, 'raw_result': b.raw_result or None,
        'packets': decode.pack_packets(b.packets, b.start_tick) if b.packets else None,
        'errors': '; '.join(b.errors) or None, 'decoder': DECODER,
    }


def save(db, rows):
    db.executemany(f'insert or replace into battles ({",".join(COLUMNS)}) values ({",".join("?" * len(COLUMNS))})',
                   [tuple(r[c] for c in COLUMNS) for r in rows])


def source_unchanged(db, path, size, mtime):
    row = db.execute('select size, mtime from sources where path = ?', (str(path),)).fetchone()
    return row is not None and row[0] == size and row[1] == mtime


def mark_source(db, path, pid, size, mtime, anchor, battles, now):
    db.execute('insert or replace into sources values (?, ?, ?, ?, ?, ?, ?)',
               (str(path), pid, size, mtime, anchor, battles, now))


def fill_from_teammates(db, window_s=3.0):
    """Fill role (name) and level where the own role shows up in another file's lineup: same char id, start within
    window_s seconds (the tap files of one machine share its clock). Names come from any lineup."""
    seen = {}
    for t, players in db.execute('select start_time, players from battles where players is not null'):
        for char_id, name, level, *_ in json.loads(players):
            seen.setdefault(char_id, [name, []])[1].append((t, level))
    for v in seen.values():
        v[1].sort(key=lambda x: x[0] or 0)
    names, levels = [], []
    for rid, char_id, t, role, level in db.execute(
            'select id, char_id, start_time, role, level from battles where role is null or level is null'):
        if char_id not in seen:
            continue
        name, hits = seen[char_id]
        if role is None:
            names.append((name, rid))
        if level is None and t is not None:
            i = bisect.bisect_left(hits, t - window_s, key=lambda x: x[0] or 0)
            near = [h for h in hits[i:i + 8] if h[0] is not None and abs(h[0] - t) <= window_s]
            if near:
                levels.append((min(near, key=lambda h: abs(h[0] - t))[1], rid))
    db.executemany('update battles set role = ? where id = ?', names)
    db.executemany('update battles set level = ? where id = ?', levels)
    db.commit()
    return len(names), len(levels)
