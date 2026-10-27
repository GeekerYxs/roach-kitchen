"""Read-only monitor for the 师徒考验 research: memory snapshots + (if armed) the DLL tap, per role.

    python -X utf8 research/shitu/monitor.py [--new] [role ...]   (default: mm01 欧皇; --new = skip old packets)

Memory (ReadProcessMemory only, every 0.2 s; a line is written only when something changed):
  map / battle flag, NPC dialog text + options (world.parse_options), the quiz panel (ui+0x10C4), team roster,
  the whole active-quest tree (quest, phase, step bytes) and the done-quest set.
Network: tails runtime/tap_<pid>.jsonl written by the DLL copy that attach_tap.py injected.
  'request' records = the client's own send function (plain opcode + body, before encoding);
  'wire_recv' records = raw socket bytes, decoded here with the codec tables the DLL dumped (same as
  provisioner.protocol.TapReader).

Output (research/shitu/logs/):  mem_<role>.jsonl, net_<role>.jsonl, monitor_<start>.log (= the console).
Never sends anything, never calls game functions.
"""
import ctypes
import json
import re
import struct
import sys
import time
from datetime import datetime

from common import LOGS, ROOT, RUNTIME, DEFAULT_ROLES, find_roles, module_base
from provisioner.memory import ProcessMemory
from provisioner import world as w

INTERVAL = 0.2
GATHER_FLOWER, GATHER_STONE = 11150, 11151     # 遗忘之花 / 遗忘之石 (ItemLib)
_k32 = ctypes.WinDLL('kernel32')
_k32.GetTickCount.restype = ctypes.c_uint32


def now_text(t=None):
    t = time.time() if t is None else t
    return datetime.fromtimestamp(t).strftime('%H:%M:%S.%f')[:-3]


# ---------------------------------------------------------------- memory

def read_string(mem, at):
    """MSVC std::string at `at` (16-byte inline buffer, size +16, capacity +20) -> bytes, or None."""
    raw = mem.read(at, 24)
    length, capacity = struct.unpack_from('<II', raw, 16)
    if length == 0 or not length <= capacity <= 100000:
        return None
    return raw[:length] if capacity < 16 else mem.read(struct.unpack_from('<I', raw)[0], length)


def read_question(mem):
    """Quiz panel ui+0x10C4: active flag +0x1C; text candidates (quizbot notes: +0x1AC, parent +0x104)."""
    ui = mem.u32(mem.base + w.UI_RVA)
    q = mem.u32(ui + w.UI_QUESTION) if ui else 0
    if not q:
        return None
    out = {'active': mem.u32(q + w.QUESTION_ACTIVE)}
    if out['active']:
        try:
            s = read_string(mem, q + 0x1AC)
            out['text_1ac'] = s.decode('gbk', 'replace') if s else None
        except Exception as e:      # layout unverified: keep going
            out['text_1ac'] = f'<{e}>'
    return out


def read_quests(mem):
    p = w._player_data(mem)
    if not p:
        return None, None
    head, done_head = mem.u32(p + w.QUEST_ACTIVE), mem.u32(p + w.QUEST_DONE)
    if not head or not done_head:
        return None, None
    active = {}
    for raw in w._tree_nodes(mem, head, w.QUEST_ACTIVE_NODE, w.QUEST_ACTIVE_NIL):
        key = struct.unpack_from('<I', raw, 0xC)[0]
        steps = raw[0x27:0x27 + min(raw[0x26], 0x3A) + 1]
        active[f'{key >> 16}/{key & 0xFFFF}'] = steps.hex()
    done = sorted(struct.unpack_from('<I', raw, 0xC)[0]
                  for raw in w._tree_nodes(mem, done_head, w.QUEST_DONE_NODE, w.QUEST_DONE_NIL))
    return active, done


def snapshot(mem):
    snap = {}
    st = None
    try:
        st = w.read_world(mem)
    except Exception as e:
        snap['world_error'] = str(e)
    if st:
        snap.update(char_id=st.char_id, map=st.map_id, battle=st.in_battle, busy=st.busy,
                    verification=st.verification)
        snap['pos'] = [int(st.x), int(st.y)]
        snap['dialog'] = st.dialog.text if st.dialog else None
        snap['options'] = [list(o) for o in st.dialog.options] if st.dialog else None
    try:
        snap['question'] = read_question(mem)
    except Exception as e:
        snap['question'] = f'<{e}>'
    try:
        team = w.read_team(mem)
        snap['team'] = [list(team.members), list(team.levels)] if team else None
    except Exception as e:
        snap['team'] = f'<{e}>'
    try:
        snap['quests'], snap['done'] = read_quests(mem)
    except Exception as e:
        snap['quests'], snap['done'] = f'<{e}>', None
    try:
        bag = w.read_bag(mem) or ()
        snap['bag'] = {f'{s.slot}:{s.item_id}': s.quantity for s in bag}
        snap['forget'] = [w.item_count(bag, GATHER_FLOWER), w.item_count(bag, GATHER_STONE)]
    except Exception as e:
        snap['bag'] = f'<{e}>'
    try:
        snap['level'] = w.read_level(mem)
        snap['gold'] = w.read_gold(mem)
    except Exception:
        pass
    return snap


def diff(old, new):
    """{field: new value} of changed fields; quests as added/changed/removed; done as added/removed."""
    out = {}
    for k, v in new.items():
        if old is not None and old.get(k) == v:
            continue
        if k == 'quests' and isinstance(v, dict) and old and isinstance(old.get(k), dict):
            o = old[k]
            out['quests'] = {'set': {q: s for q, s in v.items() if o.get(q) != s},
                             'removed': [q for q in o if q not in v]}
        elif k == 'done' and isinstance(v, list) and old and isinstance(old.get(k), list):
            o = set(old[k])
            out['done'] = {'added': [q for q in v if q not in o], 'removed': sorted(o - set(v))}
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------- network

_TEXT = re.compile(rb'(?:[\x20-\x7e]|[\x81-\xfe][\x40-\xfe]){4,}')


def texts(body):
    """Printable ASCII / GBK runs (>= 4 chars) found in a body, to make the log readable."""
    out = []
    for m in _TEXT.finditer(body):
        s = m.group().decode('gbk', 'replace')
        if any(ord(c) > 0x7f for c in s) or len(s) >= 6:
            out.append(s)
    return out


class Tap:
    def __init__(self, pid, from_end=False):
        # attach_tap.py's DLL copy writes to research/shitu/runtime; a client started by launcher.exe (its DLL is
        # batch_provision/bin) writes to batch_provision/runtime
        folder = RUNTIME if (RUNTIME / f'tap_{pid}_codec.json').is_file() else ROOT / 'runtime'
        self.path = folder / f'tap_{pid}.jsonl'
        self.from_end = from_end
        self.codec_path = folder / f'tap_{pid}_codec.json'
        self.offset, self.stream, self.tables = 0, b'', None

    def ready(self):
        if self.tables is None and self.codec_path.is_file() and self.path.is_file():
            codec = json.loads(self.codec_path.read_text())
            self.tables = [bytes.fromhex(x) for x in codec['decode']]
            self.offset = 0
            if self.from_end:          # skip the history; the recv stream is resynced on the next frame start
                self.offset = self.path.stat().st_size
                self.resync = True
        return self.tables is not None

    def poll(self):
        """[(wall time, 'C->S'|'S->C', opcode, body, caller_rva)]"""
        if not self.ready():
            return []
        with open(self.path, 'rb') as f:
            f.seek(self.offset)
            chunk = f.read()
        end = chunk.rfind(b'\n') + 1
        self.offset += end
        tick_now, t_now = _k32.GetTickCount(), time.time()
        out = []
        for line in chunk[:end].splitlines():
            r = json.loads(line)
            t = t_now - ((tick_now - r['tick']) & 0xFFFFFFFF) / 1000
            if r['kind'] == 'request':
                out.append((t, 'C->S', r['opcode'], bytes.fromhex(r['hex']), r['caller_rva']))
            elif r['kind'] == 'wire_recv':
                if getattr(self, 'resync', False):     # first recv after skipping: assume it starts a frame
                    self.stream, self.resync = b'', False
                self.stream += bytes.fromhex(r['hex'])
                out += [(t, 'S->C', op, body, None) for op, body in self._frames()]
        return out

    def _frames(self):
        packets = []
        while len(self.stream) >= 4:
            inverted, opcode = struct.unpack_from('<HH', self.stream)
            length = (~inverted) & 0xFFFF
            if len(self.stream) < 4 + length:
                break
            index = ((opcode << 8) ^ inverted) % 10
            raw = self.stream[4:4 + length]
            packets.append((opcode, bytes(self.tables[(index + i) % 10][v] for i, v in enumerate(raw))))
            self.stream = self.stream[4 + length:]
        return packets


# ---------------------------------------------------------------- main

class Role:
    def __init__(self, name, pid, title, from_end=False):
        self.name, self.pid = name, pid
        self.mem = ProcessMemory(pid, module_base(pid))
        self.tap = Tap(pid, from_end)
        self.last = None
        self.mem_log = open(LOGS / f'mem_{name}.jsonl', 'a', encoding='utf-8')
        self.net_log = open(LOGS / f'net_{name}.jsonl', 'a', encoding='utf-8')
        self.title = title


def main(roles, from_end=False):
    LOGS.mkdir(exist_ok=True)
    console = open(LOGS / f'monitor_{datetime.now():%Y%m%d_%H%M%S}.log', 'w', encoding='utf-8')

    def say(line):
        print(line, flush=True)
        console.write(line + '\n')
        console.flush()

    found = find_roles(roles)
    missing = [r for r in roles if r not in found]
    if missing:
        say(f'没找到窗口: {missing}')
    watch = [Role(r, *found[r], from_end) for r in roles if r in found]
    for r in watch:
        say(f'[{r.name}] pid {r.pid} base {r.mem.base:#x} tap {"已就绪" if r.tap.ready() else "未注入/未 arm（只记内存）"}')
    tap_seen = {r.name: r.tap.ready() for r in watch}
    while True:
        for r in watch:
            t = time.time()
            if not tap_seen[r.name] and r.tap.ready():
                tap_seen[r.name] = True
                say(f'{now_text()} [{r.name}] 网络录包已就绪')
            try:
                for pt, d, op, body, caller in r.tap.poll():
                    rec = {'t': round(pt, 3), 'time': now_text(pt), 'dir': d, 'op': f'{op:#06x}', 'len': len(body),
                           'hex': body.hex(), 'text': texts(body)}
                    if caller is not None:
                        rec['caller_rva'] = f'{caller:#x}'
                    r.net_log.write(json.dumps(rec, ensure_ascii=False) + '\n')
                    show = body[:48].hex() + ('..' if len(body) > 48 else '')
                    say(f'{rec["time"]} [{r.name}] {d} {rec["op"]} len={len(body):<4} {show} {" | ".join(rec["text"])}')
                r.net_log.flush()
            except Exception as e:
                say(f'{now_text()} [{r.name}] 网络日志读取出错: {e}')
            try:
                snap = snapshot(r.mem)
            except Exception as e:
                snap = {'error': str(e)}
            d = diff(r.last, snap)
            if d:
                r.mem_log.write(json.dumps({'t': round(t, 3), 'time': now_text(t), **d}, ensure_ascii=False) + '\n')
                r.mem_log.flush()
                say(f'{now_text(t)} [{r.name}] MEM {json.dumps(d, ensure_ascii=False)[:600]}')
            r.last = snap
        time.sleep(INTERVAL)


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if a != '--new']
    main(tuple(args) or DEFAULT_ROLES, '--new' in sys.argv)     # --new: only packets from now on
