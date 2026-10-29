"""Stage 2: the live side of the battle log. Reads each watched window's memory (read-only) and writes one row per
battle into mem_battles; every few minutes imports the tap files and merges the memory rows into battles.

What memory adds to the tap: the own level and exp (also for windows without the DLL), gold and bag changes, and
the 答题 / verification popups. A cycle = previous battle end -> this battle end, so gold / bag changes include drops,
item use and anything sold or picked up while patrolling.
"""
import json
import logging
import time
from dataclasses import dataclass, field

from expwatch import core as expcore

IDLE_CLOSE = 60.0       # an ended battle with no new one this long is closed (its cycle still counts)
log = logging.getLogger('prov.battlelog')


@dataclass(frozen=True)
class MemSample:
    t: float
    in_battle: bool
    map_id: int
    x: int
    y: int
    level: int
    exp: int
    verification: bool          # 答题 panel or the boss quiz shown
    gold: int | None = None
    bag: dict | None = None     # {item id: quantity}


@dataclass
class MemBattle:
    start_time: float
    end_time: float | None
    map_id: int
    x: int
    y: int
    level: int
    level_after: int
    exp_before: int
    exp_after: int
    exp_gain: int | None
    gold_before: int | None
    gold_after: int | None
    bag_delta: dict             # {item id: change} over the cycle
    quiz_count: int             # popups that appeared during the cycle
    quiz_s: float               # seconds a popup was shown during the cycle
    patrol_s: float | None      # previous battle end -> this start


def bag_delta(before, after):
    if before is None or after is None:
        return {}
    keys = set(before) | set(after)
    return {k: after.get(k, 0) - before.get(k, 0) for k in sorted(keys) if after.get(k, 0) != before.get(k, 0)}


class MemTracker:
    """Feed one window's samples in time order; returns finished MemBattles (closed at the next battle start, or
    IDLE_CLOSE seconds after the end). Gold / bag before = the state when the previous battle was closed."""

    def __init__(self, table):
        self.table = table
        self.prev = None            # previous sample
        self.cur = None             # MemSample at the start of the tracked battle
        self.end = None             # its end time
        self.last_close = None      # (time, gold, bag) when the previous battle was closed
        self.last_end = None        # end time of the previous battle (for the patrol time)
        self.quiz_count = 0
        self.quiz_s = 0.0

    def feed(self, s):
        out = []
        prev, self.prev = self.prev, s
        if prev is None:
            if s.gold is not None:
                self.last_close = (s.t, s.gold, s.bag)
            return out
        if prev.verification:
            self.quiz_s += s.t - prev.t
        if s.verification and not prev.verification:
            self.quiz_count += 1
        if s.in_battle and not prev.in_battle:                  # a battle starts: close the previous one
            if self.cur is not None and self.end is not None:
                out.append(self._close(s))
            if self.cur is None and self.last_close is None:
                self.last_close = (prev.t, prev.gold, prev.bag)
            self.cur, self.end = s, None
        elif prev.in_battle and not s.in_battle:
            if self.cur is not None:
                self.end = s.t
        elif not s.in_battle and self.cur is not None and self.end is not None and s.t - self.end >= IDLE_CLOSE:
            out.append(self._close(s))
            self.cur = self.end = None
        return out

    def _close(self, s):
        c, (_, gold0, bag0) = self.cur, self.last_close or (None, None, None)
        b = MemBattle(
            start_time=c.t, end_time=self.end, map_id=c.map_id, x=c.x, y=c.y, level=c.level, level_after=s.level,
            exp_before=c.exp, exp_after=s.exp, exp_gain=expcore.gained(self.table, c.level, c.exp, s.level, s.exp),
            gold_before=gold0, gold_after=s.gold, bag_delta=bag_delta(bag0, s.bag),
            quiz_count=self.quiz_count, quiz_s=round(self.quiz_s, 1),
            patrol_s=None if self.last_end is None else round(c.t - self.last_end, 1))
        self.last_close, self.last_end = (s.t, s.gold, s.bag), self.end
        self.quiz_count, self.quiz_s = 0, 0.0
        return b


MEM_SCHEMA = """
create table if not exists mem_battles (
    id integer primary key, role text, pid integer, char_id integer,
    start_time real, end_time real, map_id integer, x integer, y integer,
    level integer, level_after integer, exp_before integer, exp_after integer, exp_gain integer,
    gold_before integer, gold_after integer, bag_delta text,
    quiz_count integer, quiz_s real, patrol_s real,
    unique (pid, start_time)
);
create index if not exists mem_battles_pid on mem_battles (pid, start_time);
"""
MERGE_COLUMNS = {'gold_delta': 'integer', 'bag_delta': 'text', 'quiz_count': 'integer', 'quiz_s': 'real',
                 'mem_level': 'integer', 'mem_exp_gain': 'integer'}


def init(db):
    db.executescript(MEM_SCHEMA)
    have = {r[1] for r in db.execute('pragma table_info(battles)')}
    for name, kind in MERGE_COLUMNS.items():
        if name not in have:
            db.execute(f'alter table battles add column {name} {kind}')
    db.commit()


def save(db, role, pid, char_id, battles):
    db.executemany(
        'insert or replace into mem_battles (role, pid, char_id, start_time, end_time, map_id, x, y, level, level_after,'
        ' exp_before, exp_after, exp_gain, gold_before, gold_after, bag_delta, quiz_count, quiz_s, patrol_s)'
        ' values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        [(role, pid, char_id, b.start_time, b.end_time, b.map_id, b.x, b.y, b.level, b.level_after, b.exp_before,
          b.exp_after, b.exp_gain, b.gold_before, b.gold_after, json.dumps(b.bag_delta), b.quiz_count, b.quiz_s,
          b.patrol_s) for b in battles])
    db.commit()


def merge(db, window_s=3.0):
    """Copy the memory side into battles of the same window (pid) that started within window_s seconds; also the
    own level / role where the tap had none. Returns the number of battles updated."""
    init(db)
    rows = db.execute(
        'select b.id, m.level, m.exp_gain, m.gold_after - m.gold_before, m.bag_delta, m.quiz_count, m.quiz_s, m.role'
        ' from battles b join mem_battles m on m.pid = b.pid and abs(m.start_time - b.start_time) <= ?'
        ' where b.mem_level is null', (window_s,)).fetchall()
    db.executemany('update battles set mem_level = ?, mem_exp_gain = ?, gold_delta = ?, bag_delta = ?, quiz_count = ?,'
                   ' quiz_s = ?, level = coalesce(level, ?), role = coalesce(role, ?) where id = ?',
                   [(lv, gain, gd, bag, qc, qs, lv, role, bid) for bid, lv, gain, gd, bag, qc, qs, role in rows])
    db.commit()
    return len(rows)


def read_sample(mem, now=None):
    """MemSample of one window, or None while loading. Read-only."""
    from provisioner import world
    from expwatch.__main__ import SESSION_EXP
    import struct
    w = world.read_world(mem)
    level = world.read_level(mem)
    if w is None or not level:
        return None
    session = mem.u32(mem.base + world.SESSION_MGR_RVA)
    exp = struct.unpack('<q', mem.read(session + SESSION_EXP, 8))[0]
    bag = {}
    for slot in world.read_bag(mem) or ():
        bag[slot.item_id] = bag.get(slot.item_id, 0) + slot.quantity
    return MemSample(now or time.time(), w.in_battle, w.map_id, int(w.x), int(w.y), level, exp, w.verification,
                     world.read_gold(mem), bag), w.char_id


def run(cfg_path):
    """Watch the configured windows until closed; import the tap files every import_minutes."""
    import tomllib
    from pathlib import Path
    from provisioner import log as plog
    from provisioner.memory import ProcessMemory
    from expwatch.__main__ import find_pids, module_base
    from . import store
    from .__main__ import DB, FOLDERS, ROOT, run_import

    cfg = tomllib.loads(Path(cfg_path).read_text(encoding='utf-8'))
    plog.setup(ROOT / 'logs', 'battlelog')
    roles, poll = cfg['roles'], float(cfg.get('poll_seconds', 0.3))
    every = float(cfg.get('import_minutes', 10)) * 60
    table = expcore.load_table(ROOT / 'expwatch' / 'explib.csv')
    db = store.connect(DB)
    init(db)
    watch = {}          # role -> [mem, pid, tracker, char_id]
    next_find = next_import = 0.0
    log.info('战斗记录（实时）启动: %s，每 %.0f 分钟导入一次监听文件，数据库 %s', ' '.join(roles), every / 60, DB)
    while True:
        now = time.time()
        if now >= next_find and len(watch) < len(roles):
            for role, pid in find_pids([r for r in roles if r not in watch]).items():
                try:
                    watch[role] = [ProcessMemory(pid, module_base(pid)), pid, MemTracker(table), None]
                    log.info('%s 找到窗口 pid=%d', role, pid)
                except OSError as e:
                    log.warning('%s pid=%d 打不开: %s', role, pid, e)
            next_find = now + 10
        for role, w in list(watch.items()):
            mem, pid, tracker, _ = w
            try:
                got = read_sample(mem)
            except (RuntimeError, OSError) as e:
                log.warning('%s 读内存失败（窗口关了？）: %s', role, e)
                mem.close()
                del watch[role]
                continue
            if got is None:
                continue
            sample, w[3] = got
            done = tracker.feed(sample)
            if done:
                save(db, role, pid, w[3], done)
                for b in done:
                    log.info('%s %d级 地图%d 经验+%s 金币%+d 物品%s 答题%d次%.0fs 巡逻%ss', role, b.level, b.map_id,
                             b.exp_gain, (b.gold_after or 0) - (b.gold_before or 0), b.bag_delta or '-',
                             b.quiz_count, b.quiz_s, b.patrol_s)
        if now >= next_import:
            try:
                run_import(FOLDERS, quiet=True)
                log.info('监听文件已导入，合并内存记录 %d 场', merge(db))
            except Exception as e:                  # the import must never stop the live recording
                log.warning('导入监听文件失败: %s', e)
            next_import = now + every
        time.sleep(poll)
