"""战斗阵容只读采样；偏移和签名针对 2.101，客户端升级后需重新确认。"""
import struct

from provisioner.world import (
    BATTLE_RVA, BATTLE_FIGHTERS, FIGHTER_SIZE, BATTLE_GRADES,
    GRADE_ROWS, GRADE_ROW, GRADE_POS, GRADE_LEVEL,
)


def get_fighters(mem, base):
    battle = mem.u32(base + BATTLE_RVA)
    if not battle:
        return []
    code = mem.read(base + 0x13290, 28)
    if (code[:13] != bytes.fromhex('55 8b ec 8b 45 08 83 f8 13 77 11 8b 0d')
        or code[17:28] != bytes.fromhex('8b 84 81 8c 85 00 00 5d c2 04 00')
        or struct.unpack_from('<I', code, 13)[0] != base + BATTLE_RVA):
        raise RuntimeError('GetFighterName 签名不符：停止使用未验证的战斗布局')
    raw = mem.read(battle + BATTLE_FIGHTERS, 20 * FIGHTER_SIZE)
    names = struct.unpack('<20I', mem.read(battle + 0x858c, 80))
    grades = mem.read(battle + BATTLE_GRADES, GRADE_ROWS * GRADE_ROW)
    levels = {}
    for i in range(GRADE_ROWS):
        pos = struct.unpack_from('<i', grades, i * GRADE_ROW + GRADE_POS)[0]
        level = struct.unpack_from('<H', grades, i * GRADE_ROW + GRADE_LEVEL)[0]
        if 0 <= pos < 20 and level:
            levels[pos] = level
    fighters = []
    for slot, ptr in enumerate(names):
        at = slot * FIGHTER_SIZE
        kind = struct.unpack_from('<I', raw, at)[0]
        if kind == 0xffffffff:
            continue
        fighters.append({
            'slot': slot, 'type': kind,
            'name': mem.read(ptr, 96).split(b'\0')[0].decode('gbk', 'replace') if ptr else None,
            'level': levels.get(slot),
            'hp': struct.unpack_from('<i', raw, at + 0xb8)[0],
            'hp_max': struct.unpack_from('<i', raw, at + 0xc0)[0],
            'dead': bool(struct.unpack_from('<i', raw, at + 0xcc)[0]),
        })
    return fighters
