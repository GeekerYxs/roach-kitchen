"""Junk-drop watcher: one per PC, double-click 丢垃圾.bat (user 2026-11-07).

Every game window on this PC (any line, any project, a role played by hand) drops what data/drop_names.txt names,
right after each battle (the server drops the same junk into every bag) and every FALLBACK s as a fallback.
Roles in data/drop_skip_roles.txt are never touched. Both files are re-read when edited.

    python -X utf8 research/shitu/junk_watch.py            watch and drop (Ctrl+C or close the window to stop)
    python -X utf8 research/shitu/junk_watch.py --check    one pass, every window: what would be dropped, nothing sent

Safety:
  - exact names only, protected kinds only as !name (trash.check_names); no 整人道具 by type here (trash.py keeps that
    for the apprentices)
  - never in a battle, with a dialog / shop open, while busy, during a quiz (WorldState flags)
  - each drop is checked 1.5 s later; one that stays is logged 丢不掉 and left alone for STUCK_QUIET s
  - every drop sent is a row in logs/drop_log.tsv
  - drops go through the game's own sender (0x48, like trash.py); provisioner.native.CallLock makes the lines' calls
    and ours take turns on a window, so neither reads the other's call result.
A window without our DLL gets it loaded (as every line script does through trial_run.Client).
"""
import ctypes
import re
import struct
import sys
import time
from pathlib import Path

import trash
import trial_run as t
from common import game_window_titles
from provisioner import world as w

SKIP_FILE = trash.HERE / 'data' / 'drop_skip_roles.txt'
TICK = 0.5                  # s between polls of every window (memory reads only)
SCAN_EVERY = 5.0            # s between looks for new / closed windows
AFTER_BATTLE = 1.0          # s after a battle ends: the loot lands in the bag
FALLBACK = 300.0            # s: a role that fought no battle is still checked this often
VERIFY_AFTER = 1.5          # s before a sent drop is checked
STUCK_QUIET = 600.0         # s an item the server would not drop is left alone
RETRY_ATTACH = 60.0         # s before a window that failed to connect is tried again
TITLE = re.compile(r'-(.+?)_[A-Z][a-z]{2} +\d{1,2} \d{4}')

_skip = (None, frozenset())


def role_of(titles):
    """The role name in a game window title '什么什么大冒险2(..)-<role>_Oct 27 2026...', or None."""
    for x in titles:
        if '什么什么大冒险2' in x:
            m = TITLE.search(x)
            if m:
                return m.group(1)
    return None


def skip_roles(path=None):
    """Role names never touched (data/drop_skip_roles.txt, one a line, # comments), re-read when edited."""
    global _skip
    path = Path(path or SKIP_FILE)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return frozenset()
    if _skip[0] != mtime:
        _skip = (mtime, frozenset(n for n, _ in trash.parse(path.read_text(encoding='utf-8'))))
    return _skip[1]


def ready(st):
    return (st is not None and not st.in_battle and not st.busy and not st.verification
            and st.dialog is None)


class Role:
    def __init__(self, name, c):
        self.name, self.c = name, c
        self.was_battle, self.due = False, 0.0          # due 0: checked at once when first seen
        self.sent, self.sent_at = [], 0.0               # [(slot, name, map)] waiting for the check
        self.quiet = {}                                 # item id -> time it may be tried again

    def step(self, now, table, say=None, log=None):
        """One poll: note battle ends, check sent drops, drop when due and the role is free."""
        say, log = say or t.say, log or trash.log_drops
        st = self.c.world()
        if st is None:
            return
        if st.in_battle:
            self.was_battle = True
            return
        if self.was_battle:
            self.was_battle = False
            self.due = min(self.due, now + AFTER_BATTLE)
        if self.sent:
            if now - self.sent_at >= VERIFY_AFTER:
                self.verify(now, say, log)
            return
        if now < self.due or not ready(st):
            return
        self.due = now + FALLBACK
        hits = [s for s in w.read_bag(self.c.mem)
                if trash.is_named(table.get(s.item_id)) and self.quiet.get(s.item_id, 0) <= now]
        for s in hits:
            self.c.game.send(trash.OP_DROP, struct.pack('<IBBH', 0, 0, s.slot, s.quantity))
        self.sent = [(s, table[s.item_id].name, st.map_id) for s in hits]
        self.sent_at = now

    def verify(self, now, say, log):
        left = {(x.slot, x.item_id) for x in w.read_bag(self.c.mem)}
        rows, stuck = [], []
        for s, name, _ in self.sent:
            bad = (s.slot, s.item_id) in left
            if bad:
                stuck.append(name)
                self.quiet[s.item_id] = now + STUCK_QUIET
            rows.append((s.slot, s.item_id, name, s.quantity, '丢不掉' if bad else '已丢'))
        map_id = self.sent[0][2]
        self.sent = []
        try:
            log(self.name, map_id, rows)
        except OSError as e:
            say(f'[{self.name}] 丢弃记录写不进去: {e!r}')
        say(f'[{self.name}] 丢掉 {[f"{n}x{q}" for _, _, n, q, r in rows if r == "已丢"]}'
            + (f'；丢不掉（{int(STUCK_QUIET // 60)} 分钟内不再试）: {stuck}' if stuck else ''))


class Watch:
    def __init__(self, connect=None, windows=None, say=None):
        self.connect = connect or t.Client
        self.windows = windows or game_window_titles
        self.say = say or t.say
        self.roles = {}                                 # pid -> Role
        self.failed = {}                                # pid -> time to try again
        self.scanned = -1e9

    def scan(self, now):
        self.scanned = now
        skip = skip_roles()
        seen = {pid: role_of(ts) for pid, ts in self.windows().items()}
        for pid in list(self.roles):
            if seen.get(pid) != self.roles[pid].name or self.roles[pid].name in skip:
                self.say(f'[{self.roles[pid].name}] 窗口关了 / 换了角色 / 进了不碰名单，不再管')
                del self.roles[pid]
        for pid, name in seen.items():
            if not name or pid in self.roles or name in skip or self.failed.get(pid, 0) > now:
                continue
            try:
                self.roles[pid] = Role(name, self.connect(name))
                self.say(f'[{name}] 开始盯（共 {len(self.roles)} 个窗口）')
            except Exception as e:                      # not in the world yet, window closing ...
                self.failed[pid] = now + RETRY_ATTACH
                self.say(f'[{name}] 连不上，{int(RETRY_ATTACH)} 秒后再试: {e}')

    def tick(self, now, table):
        if now - self.scanned >= SCAN_EVERY:
            self.scan(now)
        for pid, r in list(self.roles.items()):
            try:
                r.step(now, table, self.say)
            except Exception as e:                      # never stop the watch for one window
                self.say(f'[{r.name}] 出错，先不管它，{int(RETRY_ATTACH)} 秒后重连: {e!r}')
                del self.roles[pid]
                self.failed[pid] = now + RETRY_ATTACH


def single_instance():
    """False when another junk_watch already runs on this PC (named mutex, like the quiz bot: one per PC)."""
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.CreateMutexW.restype = ctypes.c_void_p
    global _instance
    _instance = k.CreateMutexW(None, False, 'Local\\smsm2_junk_watch')
    return ctypes.get_last_error() != 183           # ERROR_ALREADY_EXISTS


def check_all():
    table = trash.items()
    got, skip = trash.names(), skip_roles()
    for pid, ts in game_window_titles().items():
        name = role_of(ts)
        if not name:
            continue
        if name in skip:
            t.say(f'[{name}] 在不碰名单里，跳过')
            continue
        try:
            bag = w.read_bag(t.Client(name).mem)
        except Exception as e:
            t.say(f'[{name}] 连不上: {e}')
            continue
        rows = [f'第 {s.slot} 格 {table[s.item_id].name}x{s.quantity}' for s in bag if trash.is_named(table.get(s.item_id))]
        t.say(f'[{name}] 试运行（不丢）：' + ('；'.join(rows) if rows else '没有要丢的'))
    t.say(f'丢弃名单 {sorted(got)}；不碰名单 {sorted(skip)}')


def main(argv):
    if argv[:1] == ['--check']:
        check_all()
        return
    if not single_instance():
        t.say('丢垃圾工具已经开着了（一台电脑一个），这个窗口不用开')
        return
    table = trash.items()
    got = trash.names()
    t.say(f'丢垃圾工具开始：丢 {sorted(got)}；不碰 {sorted(skip_roles())}；关掉这个窗口就停')
    t.say(f'名单在 {trash.NAMES_FILE}，不碰名单在 {SKIP_FILE}，记录在 {trash.DROP_LOG}')
    watch = Watch()
    while True:
        watch.tick(time.monotonic(), table)
        time.sleep(TICK)


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except KeyboardInterrupt:
        t.say('丢垃圾工具停了')
