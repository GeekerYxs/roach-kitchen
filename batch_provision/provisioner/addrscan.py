"""Entry: python -m provisioner.addrscan [WAATClient.exe] — finds every game address this repo uses by byte
signatures in the exe file (read-only, no game window needed) and compares them with the constants in the code.

Why: each client update (2.98, 2.100, 2.101 ...) moves globals and functions, and sometimes struct offsets. The
signatures below were cut from 2.101 and each one matches exactly once in BOTH 2.100 and 2.101 with the right value
in each (scratchpad generator, 2026-10-29), so most of them should still match after the next update. A signature
that no longer matches, or matches twice, is reported as "没找到"; nothing is guessed.

Kinds: GLOBAL = an absolute address inside the matched bytes (value = address - image base), FUNC = where the
match starts (+off), DISP = a struct offset inside the matched bytes. LUA = the function the client registers for
Lua under a name (push func; push "name"), for twin functions a byte signature cannot tell apart.
After an update: run this, put the new numbers into the files it lists, rebuild native/ and the quizbot, then check
a running client read-only (world.read_world etc.) before any write or call.
"""
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT.parent
IMAGE_BASE = 0x400000
GLOBAL, FUNC, DISP, LUA = 'global', 'func', 'disp', 'lua'


@dataclass(frozen=True)
class Sig:
    name: str
    kind: str
    off: int          # FUNC: match start -> function start; GLOBAL / DISP: where the value sits in the match
    size: int         # bytes of the value (0 for FUNC / LUA)
    v2101: int
    v2100: int
    pattern: str      # hex bytes, ?? = any byte; LUA: the registered name


SIGS = (
    Sig('UI', GLOBAL, 9, 4, 0x6aab34, 0x6959e8,
        '89 47 0C 39 5D 0C 74 ?? A1 ?? ?? ?? ??'),
    Sig('BATTLE', GLOBAL, 2, 4, 0x6aab38, 0x6959ec,
        '8B 35 ?? ?? ?? ?? 8B F9 89 7C 24 10'),
    Sig('SESSION', GLOBAL, 8, 4, 0x6aab3c, 0x6959f0,
        '8B 46 08 2B 46 0C 8B 3D ?? ?? ?? ??'),
    Sig('CONNECTION', GLOBAL, 10, 4, 0x6aab40, 0x6959f4,
        '8B 4C 24 20 8B 7C 24 2C 8B 35 ?? ?? ?? ??'),
    Sig('LOGIN', GLOBAL, 1, 4, 0x6aab2c, 0x6959e0,
        'A1 ?? ?? ?? ?? 8B 40 50 85 C0 0F 84 ?? ?? ?? ??'),
    Sig('SELECTION', GLOBAL, 8, 4, 0x6aab30, 0x6959e4,
        '89 9C 24 ?? ?? ?? ?? A1 ?? ?? ?? ?? 89 44 24 10'),
    Sig('PLAYER', GLOBAL, 1, 4, 0x6a9f00, 0x694dc0,
        'A1 ?? ?? ?? ?? 8B 70 10 83 7E 50 00'),
    Sig('BUSY0', GLOBAL, 2, 4, 0x58091c, 0x57385c,
        '8B 0D ?? ?? ?? ?? 09 08 8B 93 ?? ?? ?? ?? 8B 8D ?? ?? ?? ??'),
    Sig('BUSY1', GLOBAL, 7, 4, 0x580934, 0x573874,
        '83 E1 01 74 ?? 8B 15 ?? ?? ?? ?? 09 10'),
    Sig('BUSY2', GLOBAL, 2, 4, 0x58093c, 0x57387c,
        '85 05 ?? ?? ?? ?? 75 ?? 85 05 ?? ?? ?? ?? 75 ?? 85 05 ?? ?? ?? ?? 75 ?? 85 05 ?? ?? ?? ?? 75 ?? 85 05 ?? ?? ?? ?? 75 ?? 33 C0'),
    Sig('BUSY3', GLOBAL, 2, 4, 0x580964, 0x5738a4,
        '85 05 ?? ?? ?? ?? 75 ?? 85 05 ?? ?? ?? ?? 75 ?? 85 05 ?? ?? ?? ?? 75 ?? 85 05 ?? ?? ?? ?? 75 ?? 33 C0'),
    Sig('BUSY4', GLOBAL, 2, 4, 0x580954, 0x573894,
        '85 05 ?? ?? ?? ?? 75 ?? 85 05 ?? ?? ?? ?? 75 ?? 85 05 ?? ?? ?? ?? 75 ?? 33 C0'),
    Sig('BUSY5', GLOBAL, 2, 4, 0x580944, 0x573884,
        '85 05 ?? ?? ?? ?? 75 ?? 85 05 ?? ?? ?? ?? 75 ?? 33 C0'),
    Sig('BUSY6', GLOBAL, 10, 4, 0x58094c, 0x57388c,
        '85 05 ?? ?? ?? ?? 75 ?? 85 05 ?? ?? ?? ?? 75 ?? 33 C0'),
    Sig('CODEC_ENC', GLOBAL, 3, 4, 0x57efa0, 0x571ee4,
        '8D 3C 95 ?? ?? ?? ?? 3B C6 73 ?? 8D 49 00'),
    Sig('CODEC_DEC', GLOBAL, 3, 4, 0x57efc8, 0x571f0c,
        '8D 3C 95 ?? ?? ?? ?? 3B C6 73 ?? 0F B6 14 08'),
    Sig('SESSION_VTABLE', GLOBAL, 2, 4, 0x4e7370, 0x4dcbec,
        'C7 07 ?? ?? ?? ?? C7 45 FC ?? ?? ?? ?? E8 ?? ?? ?? ?? 83 BF ?? ?? ?? ?? 10'),
    Sig('MOVE_TO', FUNC, 0, 0, 0x11800, 0x117e0,
        '55 8B EC 51 8B 45 0C 8B 4D 08'),
    Sig('NAVIGATE', FUNC, 0, 0, 0x18f500, 0x18cc80,
        '55 8B EC 83 E4 F8 83 EC 08 56 57 8B 7D 08 3B 8F ?? ?? ?? ??'),
    Sig('CANCEL_NAV', FUNC, 0, 0, 0x18f400, 0x18cb80,
        '83 C9 FF 39 88 ?? ?? ?? ?? 75 ?? 39 88 ?? ?? ?? ??'),
    Sig('CLICK_NPC', FUNC, 0, 0, 0x111a0, 0x11180,
        '55 8B EC 83 E4 F8 83 EC 0C 53 56 8B 35 ?? ?? ?? ?? 33 C0 57 89 44 24 14'),
    Sig('SELECT_DIALOG', FUNC, 0, 0, 0x11c90, 0x11c70,
        '55 8B EC 83 EC 10 A1 ?? ?? ?? ?? 33 C5 89 45 FC A1 ?? ?? ?? ??'),
    Sig('FIGHT_CMD', FUNC, 0, 0, 0x16f4b0, 0x16d110,
        '55 8B EC 83 EC 0C 8A 4D FA'),
    Sig('SEND', FUNC, 0, 0, 0x31b080, 0x316ab0,
        '55 8B EC 83 E4 F8 83 EC 20 83 7E 20 FF'),
    Sig('TEAM_ACCEPT', FUNC, 0, 0, 0x225a10, 0x220960,
        '55 8B EC 83 E4 F8 83 EC 3C A1 ?? ?? ?? ?? 33 C4 89 44 24 38 53 56 8B F1 8B 4E 14'),
    Sig('TEAM_LEAVE', FUNC, 0, 0, 0x2a50d0, 0x2a0da0,
        '55 8B EC 83 E4 F8 83 EC 0C A1 ?? ?? ?? ?? 33 C4 89 44 24 08 53 33 C0'),
    Sig('QUIZ_SUBMIT', FUNC, 0, 0, 0x2293a0, 0x224330,
        '55 8B EC 83 E4 F8 6A FF 68 ?? ?? ?? ?? 64 A1 ?? ?? ?? ?? 50 81 EC ?? ?? ?? ?? A1 ?? ?? ?? ?? 33 C4 89 84 24 ?? ?? ?? ?? 53 56 57 A1 ?? ?? ?? ?? 33 C4 50 8D 84 24 ?? ?? ?? ?? 64 A3 ?? ?? ?? ?? 8B F1 33 DB 89 74 24 40 39 9E ?? ?? ?? ??'),
    Sig('CLOSE_DIALOG', FUNC, 0, 0, 0x3d1b50, 0x3c7e50,
        '55 8B EC 56 57 8B 7D 08 57 8B F1 E8 ?? ?? ?? ?? 85 C0'),
    Sig('UI_NAV_MGR', DISP, 2, 4, 0xfd4, 0xda4,
        '8B 90 ?? ?? ?? ?? 8B 42 08 83 C4 04'),
    Sig('UI_TEAM', DISP, 6, 4, 0xfd0, 0xda0,
        '8B 74 24 14 8B 8E ?? ?? ?? ?? 8B 79 04'),
    Sig('UI_SHOE_PANEL', DISP, 8, 4, 0xfb4, 0xd84,
        '8B 7B 4C 8B 4B 50 8B 86 ?? ?? ?? ??'),
    Sig('UI_DIALOG', DISP, 12, 4, 0x10c0, 0xe90,
        '83 78 60 00 0F 85 ?? ?? ?? ?? 8B 8B ?? ?? ?? ??'),
    Sig('UI_QUESTION', DISP, 2, 4, 0x12f4, 0x10c4,
        '8B B0 ?? ?? ?? ?? 85 F6 74 ?? 6A 01 E8 ?? ?? ?? ??'),
    Sig('NAV_READY', DISP, 2, 4, 0x3d8, 0x1a8,
        '8B B3 ?? ?? ?? ?? 8B FB 89 74 24 10'),
    Sig('NAV_ACTIVE', DISP, 2, 4, 0x404, 0x1d4,
        'C6 87 ?? ?? ?? ?? 01 E8 ?? ?? ?? ?? 8B 44 24 08'),
    Sig('SHOE_MAP', DISP, 5, 4, 0x678, 0x438,
        '8B 55 F8 89 88 ?? ?? ?? ?? 8B 4D F4'),
    Sig('BATTLE_FIGHTERS', DISP, 3, 4, 0x1dc8, 0x1dc0,
        '83 BC 33 ?? ?? ?? ?? 01 0F B6 5F 04'),
    Sig('BATTLE_SIDE', DISP, 6, 4, 0x9180, 0x9178,
        '8B 54 24 10 83 BA ?? ?? ?? ?? 00 74 ??'),
    Sig('BATTLE_REAL_POS', DISP, 8, 4, 0x9184, 0x917c,
        '89 54 24 20 EB ?? 83 BE ?? ?? ?? ?? 0A'),
    Sig('BATTLE_PET_REAL_POS', DISP, 8, 4, 0x9188, 0x9180,
        '88 8E ?? ?? ?? ?? 89 86 ?? ?? ?? ?? 80 7F 28 0A'),
    Sig('SCENE_INDEX', DISP, 8, 4, 0x24928, 0x24928,
        '8D 88 ?? ?? ?? ?? 8B 80 ?? ?? ?? ?? 8D 74 24 0C'),
    Sig('SCENE_FIRST', DISP, 8, 4, 0xe34, 0xe34,
        '8B B9 ?? ?? ?? ?? 8B 9F ?? ?? ?? ?? 8B 8F ?? ?? ?? ?? 2B CB'),
    Sig('SESSION_MAP_ID', DISP, 2, 4, 0x688, 0x688,
        '8B 82 ?? ?? ?? ?? 89 44 24 14 89 7C 24 38'),
    Sig('SESSION_LEVEL', DISP, 8, 4, 0xf00, 0xf00,
        'C6 44 24 13 01 50 39 81 ?? ?? ?? ??'),
    Sig('BAG_COUNT', DISP, 6, 4, 0x8818, 0x8818,
        '89 7C 24 10 39 B8 ?? ?? ?? ?? 0F 8E ?? ?? ?? ??'),
    Sig('BAG_GOLD', DISP, 12, 4, 0x8800, 0x8800,
        '8B 74 24 40 8B 8E ?? ?? ?? ?? 8B 86 ?? ?? ?? ??'),
    Sig('EQUIP_TABLE', DISP, 4, 4, 0x8828, 0x8828,
        '8B C8 39 87 ?? ?? ?? ?? 75 ?? 88 9C CD ?? ?? ?? ??'),
    Sig('SKILL_TABLE', DISP, 2, 4, 0x1b8a8, 0x1b8a8,
        '8D 9E ?? ?? ?? ?? 89 44 24 2C 89 5C 24 18'),
    Sig('PET_VECTOR', DISP, 2, 4, 0x1b98c, 0x1b98c,
        '8D 86 ?? ?? ?? ?? 50 89 45 20 8B 81 ?? ?? ?? ??'),
    Sig('PET_FIGHTING', DISP, 12, 4, 0x1b9a0, 0x1b9a0,
        '8B 74 24 40 8B 8E ?? ?? ?? ?? 8B 81 ?? ?? ?? ??'),
    Sig('QUEST_ACTIVE', DISP, 2, 4, 0x1b94c, 0x1b94c,
        '3B 86 ?? ?? ?? ?? 74 ?? 8B 4F 08 89 48 14'),
    Sig('QUEST_DONE', DISP, 4, 4, 0x1b95c, 0x1b95c,
        '33 C0 3B 8E ?? ?? ?? ?? 5E 0F 95 C0'),
    Sig('PLAYER_CHAR_ID', DISP, 8, 4, 0x34c, 0x34c,
        '8B 4F 24 8B 75 E8 8B 96 ?? ?? ?? ??'),
    Sig('QUIZ_QNO', DISP, 2, 4, 0x3d4, 0x1a4,
        '8B 8F ?? ?? ?? ?? 8B 11 89 44 24 18'),
    Sig('QUIZ_CHOSEN', DISP, 5, 4, 0x3dc, 0x1ac,
        '89 45 08 8D 86 ?? ?? ?? ?? 8D 55 08'),
    Sig('QUIZ_MAP_MODE', DISP, 6, 4, 0x3e4, 0x1b4,
        '6A 00 FF D0 8B 8F ?? ?? ?? ?? 6A 01'),
    Sig('QUIZ_TEXT_BOX', DISP, 6, 4, 0x3fc, 0x1cc,
        '8B 54 24 28 8B 8A ?? ?? ?? ?? 8B 01'),
    Sig('LOGIN_ACCOUNT_EDIT', DISP, 8, 4, 0x3b0, 0x180,
        '83 E4 F8 8B 55 08 89 86 ?? ?? ?? ??'),
    Sig('ROLE_SELECT_INDEX', DISP, 2, 4, 0x3d8, 0x1a8,
        '8B B3 ?? ?? ?? ?? 8B FB 89 74 24 10'),
    Sig('CAST_SKILL', LUA, 0, 0, 0x134e0, 0x134c0, 'CastSkillToFighter'),
    Sig('CAST_PET_MAGIC', LUA, 0, 0, 0x135a0, 0x13580, 'CastPetMagicToFighter'),
)

# Values that follow from another one (same object, next field), checked live on 2.101.
DERIVED = {
    'UI_QUESTION_MAP': ('UI_QUESTION', 4),    # ui+0x12F8 QuestionOnMap, same class CUIQuestion as ui+0x12F4
    'SHOE_XY': ('SHOE_MAP', 4),
    'SCENE_LAST': ('SCENE_FIRST', 4),
}


def load_image(path):
    """Exe file -> (image bytes laid out by RVA, (text_start, text_end)). Plain PE parsing, no pefile needed."""
    raw = Path(path).read_bytes()
    pe = struct.unpack_from('<I', raw, 0x3C)[0]
    if raw[pe:pe + 4] != b'PE\0\0':
        raise ValueError(f'{path} 不是 PE 文件')
    sections, opt_size = struct.unpack_from('<H', raw, pe + 6)[0], struct.unpack_from('<H', raw, pe + 20)[0]
    opt = pe + 24
    image_size, headers = struct.unpack_from('<I', raw, opt + 56)[0], struct.unpack_from('<I', raw, opt + 60)[0]
    image = bytearray(image_size)
    image[:headers] = raw[:headers]
    text = None
    for i in range(sections):
        s = opt + opt_size + 40 * i
        name = raw[s:s + 8].rstrip(b'\0')
        vsize, rva, rsize, rptr = struct.unpack_from('<4I', raw, s + 8)
        n = min(rsize, vsize or rsize)
        image[rva:rva + n] = raw[rptr:rptr + n]
        if name == b'.text':
            text = (rva, rva + vsize)
    if not text:
        raise ValueError(f'{path} 没有 .text 段')
    return bytes(image), text


def compile_pattern(pattern):
    return re.compile(b''.join(b'.' if t == '??' else re.escape(bytes([int(t, 16)])) for t in pattern.split()), re.S)


def find_lua(image, text, name):
    """Function registered for Lua as `name`: the code `push func; push "name"` (68 imm32 68 imm32)."""
    found = set()
    for m in re.finditer(b'\0' + re.escape(name.encode('ascii')) + b'\0', image):
        va = struct.pack('<I', m.start() + 1 + IMAGE_BASE)
        for c in re.finditer(b'\x68(....)\x68' + re.escape(va), image[:text[1]], re.S):
            if c.start() >= text[0]:
                found.add(struct.unpack('<I', c.group(1))[0] - IMAGE_BASE)
    return found


def resolve(sig, image, text):
    """-> (value, None) or (None, why)."""
    if sig.kind == LUA:
        found = find_lua(image, text, sig.pattern)
        return (found.pop(), None) if len(found) == 1 else (None, f'Lua 注册找到 {len(found)} 处')
    hits = [m.start() for m in compile_pattern(sig.pattern).finditer(image, *text)]
    if len(hits) != 1:
        return None, f'特征码匹配 {len(hits)} 处'
    at = hits[0]
    if sig.kind == FUNC:
        return at + sig.off, None
    value = int.from_bytes(image[at + sig.off:at + sig.off + sig.size], 'little')
    return (value - IMAGE_BASE if sig.kind == GLOBAL else value), None


def scan(path):
    """{name: (value | None, why | None)} for every signature plus the derived values."""
    image, text = load_image(path)
    out = {s.name: resolve(s, image, text) for s in SIGS}
    for name, (base, delta) in DERIVED.items():
        v = out[base][0]
        out[name] = (v + delta, None) if v is not None else (None, f'{base} 没找到')
    return out


def code_constants():
    """Name -> value the Python code uses now (the same names as SIGS / DERIVED)."""
    from . import game, memory, world
    out = {
        'UI': world.UI_RVA, 'BATTLE': world.BATTLE_RVA, 'SESSION': world.SESSION_MGR_RVA, 'PLAYER': world.PLAYER_PTR_RVA,
        'CONNECTION': game.RVA_CONNECTION, 'SESSION_VTABLE': memory.SESSION_VTABLE_RVA,
        'MOVE_TO': game.RVA_MOVE_TO, 'NAVIGATE': game.RVA_NAVIGATE, 'CANCEL_NAV': game.RVA_CANCEL_NAV,
        'CLICK_NPC': game.RVA_CLICK_NPC, 'SELECT_DIALOG': game.RVA_SELECT_DIALOG, 'FIGHT_CMD': game.RVA_FIGHT_CMD,
        'SEND': game.RVA_SEND, 'TEAM_ACCEPT': game.RVA_TEAM_ACCEPT, 'TEAM_LEAVE': game.RVA_TEAM_LEAVE,
        'CAST_SKILL': game.RVA_CAST_SKILL, 'CAST_PET_MAGIC': game.RVA_CAST_PET_MAGIC,
        'UI_NAV_MGR': world.UI_NAV_MGR, 'UI_TEAM': world.UI_TEAM, 'UI_SHOE_PANEL': world.UI_SHOE_PANEL,
        'UI_DIALOG': world.UI_DIALOG, 'UI_QUESTION': world.UI_QUESTION, 'UI_QUESTION_MAP': world.UI_QUESTION_MAP,
        'NAV_READY': world.NAV_READY, 'NAV_ACTIVE': world.NAV_ACTIVE, 'SHOE_MAP': world.SHOE_MAP,
        'SHOE_XY': world.SHOE_XY, 'BATTLE_FIGHTERS': world.BATTLE_FIGHTERS, 'BATTLE_SIDE': world.BATTLE_SIDE,
        'BATTLE_REAL_POS': world.BATTLE_REAL_POS, 'BATTLE_PET_REAL_POS': world.BATTLE_PET_REAL_POS,
        'SCENE_INDEX': world.SCENE_INDEX, 'SCENE_FIRST': world.SCENE_FIRST, 'SCENE_LAST': world.SCENE_LAST,
        'SESSION_MAP_ID': world.SESSION_MAP_ID, 'SESSION_LEVEL': world.SESSION_LEVEL, 'BAG_COUNT': world.BAG_COUNT,
        'BAG_GOLD': world.BAG_GOLD, 'EQUIP_TABLE': world.EQUIP_TABLE, 'SKILL_TABLE': world.SKILL_TABLE,
        'PET_VECTOR': world.PET_VECTOR, 'PET_FIGHTING': world.PET_FIGHTING, 'QUEST_ACTIVE': world.QUEST_ACTIVE,
        'QUEST_DONE': world.QUEST_DONE, 'PLAYER_CHAR_ID': world.PLAYER_CHAR_ID,
    }
    out.update({f'BUSY{i}': v for i, v in enumerate(world.BUSY_MASK_RVAS)})
    assert memory.NETWORK_MANAGER_RVA == game.RVA_CONNECTION
    return out


# Copies of the numbers outside provisioner/ (C++ sources compiled into bin/ and the quizbot, research scripts).
# Each file must contain the value as a hex literal; the check is textual, so it catches a forgotten file.
OTHER_FILES = {
    'native/login_dll.cpp': ('LOGIN', 'SELECTION', 'UI', 'LOGIN_ACCOUNT_EDIT', 'ROLE_SELECT_INDEX'),
    'native/network.inc': ('SEND', 'CONNECTION', 'CODEC_ENC', 'CODEC_DEC'),
    'factory/delete.py': ('CONNECTION',),
    'research/shitu/boss_quiz.py': ('QUIZ_SUBMIT', 'CLOSE_DIALOG', 'QUIZ_QNO', 'QUIZ_CHOSEN', 'QUIZ_MAP_MODE',
                                    'QUIZ_TEXT_BOX'),
    '../大冒险2_自动答题器_原生无感关窗版/src/dll/game_addrs.h': (
        'UI', 'LOGIN', 'BATTLE', 'SESSION', 'PLAYER', 'CODEC_ENC', 'CODEC_DEC', 'QUIZ_SUBMIT', 'CLOSE_DIALOG',
        'UI_QUESTION', 'UI_QUESTION_MAP', 'QUIZ_QNO', 'QUIZ_CHOSEN', 'QUIZ_MAP_MODE', 'BATTLE_FIGHTERS'),
}


def has_hex(text, value):
    return re.search(rf'(?<![0-9a-fA-Fx])0x0*{value:x}(?![0-9a-fA-F])', text, re.I) is not None


def missing_in_files(values, root=ROOT):
    """[(file, name, value)] for every copy that does not contain the scanned value."""
    out = []
    for rel, names in OTHER_FILES.items():
        p = root / rel
        if not p.is_file():
            continue
        text = p.read_text('utf-8', errors='replace')
        out += [(rel, n, values[n]) for n in names if values.get(n) is not None and not has_hex(text, values[n])]
    return out


def compare(found, code):
    """-> (rows, problems): rows (name, code value, scanned value, status) sorted by name."""
    rows, problems = [], 0
    for name in sorted(found):
        value, why = found[name]
        have = code.get(name)
        if value is None:
            status = f'没找到（{why}）'
            problems += 1
        elif have is None:
            status = '只在代码外用'
        elif have == value:
            status = '一致'
        else:
            status = '代码里的值不对'
            problems += 1
        rows.append((name, have, value, status))
    return rows, problems


def default_exe():
    from factory.supervisor import load_supervisor
    return load_supervisor(ROOT / 'supervisor.toml').login.game_exe


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    exe = argv[0] if argv else default_exe()
    found = scan(exe)
    rows, problems = compare(found, code_constants())
    print(f'游戏程序 {exe}')
    for name, have, value, status in rows:
        h = f'{have:#x}' if have is not None else '-'
        v = f'{value:#x}' if value is not None else '-'
        print(f'  {name:20s} 代码 {h:>10s}  扫描 {v:>10s}  {status}')
    stale = missing_in_files({k: v for k, (v, _) in found.items()})
    for rel, name, value in stale:
        print(f'  [要改] {rel}: {name} 应为 {value:#x}')
    print(f'共 {len(rows)} 项，{problems} 项有问题，{len(stale)} 处代码外的副本要改')
    return 1 if problems or stale else 0


if __name__ == '__main__':
    sys.exit(main())
