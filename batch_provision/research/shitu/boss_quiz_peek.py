"""Read-only peek at the two quiz panels (see BOSS_QUIZ.md).

    python -X utf8 research/shitu/boss_quiz_peek.py [--watch] role [role ...]

  ui+0x10C4 "Question"       S->C 0x46f4 (quiz in battle, quizbot answers it)    answer C->S 0x1f04
  ui+0x10C8 "QuestionOnMap"  S->C 0x46f5 (quiz on 「开打」 at a boss, by hand)      answer C->S 0x1f05
Panel fields: +0x1C visible, +0x1CC -> QOnlyReadText (its +0x108 = char* GBK rich text),
+0x1A4 question id, +0x1AC chosen option (0-based, -1 = none), +0x1B4 1 = answer with 0x1f05.
--watch prints a line whenever one of these changes (every 0.2 s). Never writes memory, never sends.
"""
import struct
import sys
import time

from common import find_roles, module_base
from provisioner.memory import ProcessMemory
from provisioner import world as w

PANELS = {'Question': 0x10C4, 'QuestionOnMap': 0x10C8}


def read_cstr(mem, at, limit=600):
    """Read a 0-terminated string in 32-byte steps, so the read never runs past readable memory."""
    out = b''
    while len(out) < limit:
        try:
            chunk = mem.read(at + len(out), 32)
        except RuntimeError:
            break
        end = chunk.find(b'\0')
        if end >= 0:
            return out + chunk[:end]
        out += chunk
    return out


def peek(mem):
    ui = mem.u32(mem.base + w.UI_RVA)
    out = {}
    for name, off in PANELS.items():
        p = mem.u32(ui + off) if ui else 0
        if not p:
            continue
        row = {'visible': mem.u32(p + 0x1C), 'qid': mem.u32(p + 0x1A4), 'chosen': struct.unpack('<i', mem.read(p + 0x1AC, 4))[0],
               'map_mode': mem.u32(p + 0x1B4)}
        text_box = mem.u32(p + 0x1CC)
        text = mem.u32(text_box + 0x108) if text_box else 0
        if text:
            row['text'] = read_cstr(mem, text).decode('gbk', 'replace')
        out[name] = row
    return out


def main(argv):
    watch = '--watch' in argv
    roles = [a for a in argv if not a.startswith('--')]
    mems = {}
    for role, (pid, _title) in find_roles(roles).items():
        mems[role] = ProcessMemory(pid, module_base(pid))
    last = {}
    while True:
        for role, mem in mems.items():
            now = peek(mem)
            if now != last.get(role):
                print(time.strftime('%H:%M:%S'), role, now, flush=True)
                last[role] = now
        if not watch:
            return
        time.sleep(0.2)


if __name__ == '__main__':
    main(sys.argv[1:])
