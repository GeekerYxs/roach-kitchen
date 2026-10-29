"""Boss「开打」时弹的答题（S->C 0x46F5，面板 QuestionOnMap = [ui+0x12F8]，2.100 是 ui+0x10C8）—— 师徒脚本里静默自动答。

    python -X utf8 boss_quiz.py ROLE ...      只读：打印这些窗口的 boss 题面板和会选哪项（不答）

用法（dts.py / scorpion_king.py）：点「开打」没进战斗时调 solve(client)。
  1. 面板没开 -> 返回 None（不是答题的问题）。
  2. 面板开着：先等 GRACE 秒让 启动答题器（新版，静默）去答；它答了面板就关了。
  3. 还开着（答题器没开 / 没注入）-> 这里自己答：和手动点选一样，写 面板 QUIZ_CHOSEN = 下标，
     在游戏窗口线程上调 提交函数(面板) 和 CloseDialog(父窗口, 面板, 0)（DLL 命令 106），客户端自己发 0x1F05。
     因为下标写进了面板，答题器 DLL 收到「测试通过！」时照样能读到，自动记进题库。
选哪项：和答题器 controller/boss_quiz.h 同一套规则、同一份题库文件
  （大冒险2_自动答题器_原生无感关窗版/data/boss_bank.tsv + boss_decoys.txt）：
  题库按题号命中 > 排除干扰项（书名号 / 记录过的错误选项）后只剩一个或共有字最多 > 猜第一个非干扰项。
协议和内存见 BOSS_QUIZ.md；离线测试 tests/test_boss_quiz.py（batch_provision/tests）。
"""
import ctypes
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from common import ROOT, find_roles, module_base
from provisioner import native
from provisioner import world as w
from provisioner.memory import ProcessMemory

GRACE = 4.0                     # 秒：先让答题器答（它题库命中/静默模式都在 1.5 秒左右答）
BANK_DIR = ROOT.parent / '大冒险2_自动答题器_原生无感关窗版' / 'data'

# 2.101（2026-10-29）：界面窗口类从 +0x174 起整体变大 0x230，面板指针和面板字段都跟着挪了；括号里是 2.100 的值。
UI_QUIZ_MAP = w.UI_QUESTION_MAP  # QuestionOnMap = ui+0x12F8（0x10C8）；ui+0x12F4 是战斗里的 Question（0x46F4）
QUIZ_VISIBLE, QUIZ_PARENT, QUIZ_TEXT_BOX = 0x1C, 0x104, 0x3FC          # （0x1C, 0x104, 0x1CC）
QUIZ_QNO, QUIZ_CHOSEN, QUIZ_MAP_MODE = 0x3D4, 0x3DC, 0x3E4             # （0x1A4, 0x1AC, 0x1B4）
TEXT_PTR = 0x108                # QOnlyReadText +0x108 -> char* GBK 富文本
RVA_QUIZ_SUBMIT = 0x2293A0      # thiscall(panel)：按 QUIZ_CHOSEN 发答案（QUIZ_MAP_MODE==1 时发 0x1F05）（0x224330）
RVA_CLOSE_DIALOG = 0x3D1B50     # thiscall(parent, panel, 0)（0x3C7E50）

_COLOR = re.compile(r'#[0-9A-Fa-f]{6}#')
_URL = re.compile(r'\[URL\](.*?)\[/URL\]')


@dataclass
class Panel:
    address: int
    visible: bool
    qno: int
    chosen: int
    map_mode: int
    stem: str
    options: list


def _read_cstr(mem, at, limit=600):
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


def parse_text(text):
    """面板富文本 -> (题目, [选项…])。选项保留「1、」前缀，空的第 5 项丢掉。"""
    lines = text.split('\n')
    stem = _COLOR.sub('', lines[0]).strip() if lines else ''
    options = [_COLOR.sub('', m.group(1)).strip() for m in _URL.finditer(text)]
    while options and not options[-1]:
        options.pop()
    return stem, options


def read_panel(mem):
    ui = mem.u32(mem.base + w.UI_RVA)
    p = mem.u32(ui + UI_QUIZ_MAP) if ui else 0
    if not p:
        return None
    box = mem.u32(p + QUIZ_TEXT_BOX)
    ptr = mem.u32(box + TEXT_PTR) if box else 0
    stem, options = parse_text(_read_cstr(mem, ptr).decode('gbk', 'replace')) if ptr else ('', [])
    chosen = mem.u32(p + QUIZ_CHOSEN)
    return Panel(p, bool(mem.u32(p + QUIZ_VISIBLE)), mem.u32(p + QUIZ_QNO), chosen - (1 << 32) if chosen >> 31 else chosen,
                 mem.u32(p + QUIZ_MAP_MODE), stem, options)


# ---------------------------------------------------------------- decision (same rules as controller/boss_quiz.h)

def strip_option(s):
    """去掉游戏加的编号「1、」（只去一次），再去首尾空白。"""
    m = re.match(r'^\d+(、|\.)', s)
    return (s[m.end():] if m else s).strip()


def is_decoy(decoys, option):
    t = strip_option(option)
    if not t:
        return True
    bare = t[1:-1] if len(t) >= 2 and t[0] == '《' and t[-1] == '》' else t
    return bare != t or t in decoys or bare in decoys


def shared_chars(stem, option):
    """选项和题目共有几个字（只数汉字和数字）。"""
    in_stem = set(stem)
    return len({ch for ch in strip_option(option)
                if ch in in_stem and ('一' <= ch <= '鿿' or ch.isdigit())})


def load_bank(directory=BANK_DIR):
    """-> ({题号: (答案文字, 下标)}, {干扰项})。文件不在就是空的。"""
    entries, decoys = {}, set()
    tsv, dec = Path(directory) / 'boss_bank.tsv', Path(directory) / 'boss_decoys.txt'
    if tsv.is_file():
        for line in tsv.read_text(encoding='utf-8-sig').splitlines():
            f = line.split('\t')
            if not f or not f[0].strip().isdigit():
                continue
            opt = int(f[2]) if len(f) > 2 and f[2].strip().lstrip('-').isdigit() else -1
            entries[int(f[0])] = ((f[1] if len(f) > 1 else '').strip(), opt)
    if dec.is_file():
        for line in dec.read_text(encoding='utf-8-sig').splitlines():
            t = line.strip()
            if t and not t.startswith('#'):
                decoys.add(t)
    return entries, decoys


def decide(bank, qno, stem, options):
    """-> (下标, 依据)。下标总是有效（静默模式一定要选一个）；没有选项时 (-1, ...)。"""
    entries, decoys = bank
    note = ''
    if qno in entries:
        answer, opt = entries[qno]
        if answer:
            for i, o in enumerate(options):
                if strip_option(o) == answer:
                    return i, f'题库命中（题号 {qno}）'
            note = f'题库答案「{answer}」不在选项里；'
        elif 0 <= opt < len(options):
            return opt, f'题库命中（题号 {qno}，只记了下标）'
    left = [i for i, o in enumerate(options) if not is_decoy(decoys, o)]
    if len(left) == 1:
        return left[0], note + f'排除了 {len(options) - 1} 个干扰项'
    scores = sorted(((shared_chars(stem, options[i]), i) for i in left), reverse=True)
    if scores and scores[0][0] > 0 and (len(scores) == 1 or scores[1][0] < scores[0][0]):
        return scores[0][1], note + f'排除后剩 {len(left)} 个，和题目共有 {scores[0][0]} 个字'
    if left:
        return left[0], note + '[猜的] 排除干扰项后的第一个'
    for i, o in enumerate(options):
        if strip_option(o):
            return i, note + '[猜的] 第一个非空选项'
    return -1, note + '没有选项'


# ---------------------------------------------------------------- answering

_k = ctypes.WinDLL('kernel32', use_last_error=True)
_k.OpenProcess.restype = ctypes.c_void_p
_k.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
_k.WriteProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                  ctypes.POINTER(ctypes.c_size_t)]
_k.CloseHandle.argtypes = [ctypes.c_void_p]


def _write_u32(pid, address, value):
    h = _k.OpenProcess(0x0028, False, pid)          # VM_OPERATION | VM_WRITE
    if not h:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        data = ctypes.c_uint32(value & 0xFFFFFFFF)
        done = ctypes.c_size_t()
        if not _k.WriteProcessMemory(h, address, ctypes.byref(data), 4, ctypes.byref(done)) or done.value != 4:
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        _k.CloseHandle(h)


def submit(c, panel, opt):
    """和手动点选一样：写下标 -> 提交（客户端发 0x1F05）-> 关窗。都在游戏窗口线程上执行。"""
    _write_u32(c.pid, panel.address + QUIZ_CHOSEN, opt)
    native.call(c.game.session, RVA_QUIZ_SUBMIT, ecx=panel.address)
    parent = c.mem.u32(panel.address + QUIZ_PARENT)
    if parent:
        native.call(c.game.session, RVA_CLOSE_DIALOG, panel.address, 0, ecx=parent)


def solve(c, grace=GRACE, say=print):
    """boss 题面板开着就把它答掉（先等答题器 grace 秒）。返回一句报告；面板没开返回 None。"""
    p = read_panel(c.mem)
    if not p or not p.visible:
        return None
    qno = p.qno
    say(f'[{c.name}] boss 答题 题号 {qno}：{p.stem} {p.options}')
    end = time.monotonic() + grace
    while time.monotonic() < end:
        time.sleep(0.2)
        p = read_panel(c.mem)
        if not p or not p.visible or p.qno != qno:
            report = f'答题器已经答了题号 {qno}' + (f'（选第 {p.chosen + 1} 项）' if p and p.chosen >= 0 else '')
            say(f'[{c.name}] {report}')
            return report
    if p.map_mode != 1:
        raise RuntimeError(f'boss 题面板 模式字段={p.map_mode}，不是 0x1F05 模式，不敢答')
    opt, why = decide(load_bank(), qno, p.stem, p.options)
    if opt < 0:
        raise RuntimeError(f'题号 {qno} 没有可选的选项: {p.options}')
    say(f'[{c.name}] 答题器没答，自己答：第 {opt + 1} 项 {p.options[opt]}（{why}）')
    submit(c, p, opt)
    end = time.monotonic() + 5
    while time.monotonic() < end:
        p2 = read_panel(c.mem)
        if not p2 or not p2.visible:
            break
        time.sleep(0.2)
    else:
        say(f'[{c.name}] 提交后面板 5 秒还没关')
    return f'自己答了题号 {qno}：第 {opt + 1} 项（{why}）'


def main(roles):
    bank = load_bank()
    print(f'题库 {len(bank[0])} 道，干扰项 {len(bank[1])} 个（{BANK_DIR}）')
    for role, (pid, _title) in find_roles(roles).items():
        mem = ProcessMemory(pid, module_base(pid))
        p = read_panel(mem)
        if not p:
            print(f'[{role}] 没有 boss 题面板')
            continue
        opt, why = decide(bank, p.qno, p.stem, p.options)
        print(f'[{role}] 开着={p.visible} 题号={p.qno} 选中={p.chosen} 模式={p.map_mode}\n  {p.stem}')
        for i, o in enumerate(p.options):
            print(f'  {"->" if i == opt else "  "} {o}')
        print(f'  会选第 {opt + 1} 项：{why}')


if __name__ == '__main__':
    main(sys.argv[1:])
