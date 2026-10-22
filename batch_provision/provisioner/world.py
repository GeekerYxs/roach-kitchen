"""Read-only in-world state of the own character. Pure reads, no actions.

Offsets: earlier Gemini/Codex research (core/player_memory.py, pp_runtime/probe.py, runtime/game_state.py)
plus static analysis of WaatClient.exe on 2026-10-12:
  GetFighter(pos)  RVA 0x12C00: fighter = [base+BATTLE_RVA] + 0x1DC0 + pos*0x510 (pos 0..19)
  GetMyPos()       RVA 0x130F0: real pos [battle+0x917C] (0xFF = none), side flag [battle+0x9178]
  TFightNpcData.SP Lua getter 0x43E010 reads int32 at fighter+0xF4
"""
import re
import struct
import time
from dataclasses import dataclass, field

PLAYER_PTR_RVA = 0x694DC0    # [base+RVA] -> own player object (2.100; 2.98/2.99 0x64A638)
PLAYER_CHAR_ID = 0x34C       # +0x34C char_id, +0x350 x, +0x354 y (int32; can lag behind motion)
SESSION_MGR_RVA = 0x6959F0   # [base+RVA] -> session manager (2.100; 2.98/2.99 0x64B1B4)
SESSION_MAP_ID = 0x688
SCENE_INDEX, SCENE_FIRST, SCENE_LAST, SCENE_ROW = 0x24928, 0xE34, 0xE38, 0x2A8   # 2.100 (+0x2B8; was 0x24670)
ROW_ENTITY, ROW_FLAGS = 0x8, 0x148
ENTITY_MOTION = 0x18C        # float x, y, ?, ?, target_x, target_y
FLAG_IN_BATTLE = 0x8
BUSY_MASK_RVAS = (0x57385C, 0x573874, 0x57387C, 0x5738A4, 0x573894, 0x573884, 0x57388C)  # 2.100; 2.98 0x529734..
# 2.100 (2026-10-22): every address moved; found by masked byte fingerprints and instruction-by-instruction
# comparison with 2.98 (globals +0x4A83C, busy masks +0x4A128), struct offsets re-read on a live 2.100 client.
UI_RVA = 0x6959E8              # 2.100; 2.98/2.99 0x64B1AC
UI_NAV_MGR, NAV_OBJECT, NAV_ACTIVE, NAV_READY = 0xDA4, 0x8, 0x1D4, 0x1A8
UI_QUESTION, QUESTION_ACTIVE = 0x10C4, 0x1C
UI_DIALOG, DIALOG_VISIBLE, DIALOG_CTRL_FIRST, DIALOG_CTRL_LAST = 0xE90, 0x1C, 0xEC, 0xF0
BATTLE_RVA = 0x6959EC          # 2.100; 2.98/2.99 0x64B1B0
BATTLE_FIGHTERS, FIGHTER_SIZE, FIGHTER_SP = 0x1DC0, 0x510, 0xF4
BATTLE_REAL_POS, BATTLE_SIDE = 0x917C, 0x9178
# Own level: TGamePlayer object at session+0xE90, Lua property 'Grade' at +0x70 (RVA 0xf41e registration;
# 0x4210 handler writes it). Found offline 2026-10-06; first live check in the meat stage.
SESSION_LEVEL = 0xF00
# Bag (Gemini/Codex item_consumption.py, used live 2026-10-09): session+0x16B0 table, entry count u32 at
# +0x8818, entries at +0x88 stride 0x88: int32 valid(1), item_id, kind, pad, quantity.
# 2.100 inserted 0x10 bytes before the entries and 0x10 more before the count (2.98/2.99: +0x87F8, +0x78).
BAG_TABLE, BAG_COUNT, BAG_FIRST, BAG_STRIDE, BAG_MAX = 0x16B0, 0x8818, 0x88, 0x88, 100
# Equipment (found 2026-10-20, client 2.99): right after the bag, session+0x16B0+0x8828 (2.99: 0x8808), 13 rows of the bag's layout
# (stride 0x88, valid 1 / -1, item_id, kind, pad, quantity), row = EEquipSlot (luas/game_define.lua: 0 帽子 1 口罩
# 2 武器 3 鞋 ... 12 圣物). Checked on mvp01r1 (row 2 = 118 专打屁屁扳手), 伏地魔1 and cap07 (rows match their gear).
EQUIP_TABLE, EQUIP_ROWS, EQUIP_WEAPON = 0x8828, 13, 2
# 飞鞋 panel = [ui+0xD84]; its button handler (2.98 RVA 0x1c7d50) shows the recorded point from +0x438 map,
# +0x43C x, +0x440 y. Verified live 2026-10-12: the fields change to the server's position after a 0x82
# record (also when sent without the UI), on mw01..08.
# 2.100 moved the panel's fields +0x20 (2.98/2.99: +0x418 / +0x41C). Missed in the first 2.100 update (fb0825d): every
# new alt failed the shoe stage and got quarantined on 2026-10-22. Re-checked live: +0x438 reads (81, 1780, 1370).
UI_SHOE_PANEL, SHOE_MAP, SHOE_XY = 0xD84, 0x438, 0x43C
# Gold: signed i64 at session+0x16B0+0x8800 (2.98/2.99: 0x87F0; CUIDataItem:GetMoney, getters at 2.98 RVA 0x13430 / 0x481a0).
# Signatures re-checked 2026-10-12 on all clients; values 100 / 0 on alts, 1814300 on 小强杀手一号.
BAG_GOLD = 0x8800
# Team object = [ui+0xDA0] (Codex rogue184.team_roster, pp_runtime/bridge.py opcodes 9/10; re-read live
# 2026-10-12: 0 rows and inviter 0 on every client without a team). +0xC -> roster vector {first,last,cap},
# rows of 72 bytes, +0 char_id, +4 level (first row = the leader, per the old 5-member verification).
# +0xA8 = char_id of the last team invitation received (the accept function 0x21f590 answers that one).
UI_TEAM, TEAM_ROSTER, TEAM_INVITER, ROSTER_ROW, ROSTER_MAX = 0xDA0, 0xC, 0xA8, 72, 5
# Byte the client puts into its own team invitation (session+0x135C; 255 on new alts, 50 on a level-44 role).
SESSION_INVITE_BYTE = 0x135C
# Remaining talent points u16 (session+0xEFC; 5 on every new level-2 alt, read live 2026-10-12).
SESSION_TALENT = 0xEFC
# Battle fighters (TFightNpcData Lua fields, registrations at RVA 0x30dd5..0x31390, disassembled 2026-10-12):
# +0 Type (0xFFFFFFFF = empty slot), +0xCC IsDead int32, +0xF4 SP int32. Enemies sit in client positions 0..9
# (official auto-fight and the old pet Lua both scan 0..9). Pet: real pos [battle+0x9180], converted with the
# OWN real pos as the side test (GetMyPetPos RVA 0x13140).
FIGHTER_DEAD = 0xCC
BATTLE_PET_REAL_POS = 0x9180
ENEMY_POSITIONS = range(10)
# Learned skills and pets (Lua backing functions HasSkill RVA 0x11B30, HasFightPetHasAbility 0x11C90, GetPetMp
# 0x10270; read live 2026-10-12 on 伏地魔1: 803 lv6, fighting pet index 1 with 1504 lv11 and 919 MP).
# P = session+0x1658. Skills: 4 vectors {first,last} at P+0x1B600+0xC/0x1C/0x2C/0x3C, rows of 0x68 bytes inline,
# +0 id, level = +4 plus +8. Pets: pointer vector at P+0x1B6E4, fighting index i32 at P+0x1B6F8; pet+0x68 MP i64,
# pet+0x114 = vector of ability pointers (null entries happen), each +0 id, level = +4 plus +8.
SESSION_PLAYER_DATA = 0x1658
# 2.100: the skill / pet / quest block moved +0x2A8 (2.98/2.99: 0x1B600, 0x1B6E4, 0x1B6F8, 0x1B6A4, 0x1B6B4).
SKILL_TABLE, SKILL_VECTORS, SKILL_ROW = 0x1B8A8, (0xC, 0x1C, 0x2C, 0x3C), 0x68
PET_VECTOR, PET_FIGHTING, PET_MP, PET_ABILITIES = 0x1B98C, 0x1B9A0, 0x68, 0x114
# Quests (Codex/Gemini runtime/game_state.task_snapshot, quest 78 accepted live 2026-10-09; the data object [ui+0xD38]
# re-read 2026-10-12 = P on all 10 clients). Two MSVC std::map trees, head pointer at P+off, root = [head+4],
# node +0 left, +8 right, +0xC key. Active: P+0x1B6A4, key = quest << 16 | phase, isnil byte +0x61,
# +0x26 last step index, +0x27.. step status bytes. Done: P+0x1B6B4, key = quest id, isnil byte +0x1D.
QUEST_ACTIVE, QUEST_ACTIVE_NODE, QUEST_ACTIVE_NIL = 0x1B94C, 0x62, 0x61
QUEST_DONE, QUEST_DONE_NODE, QUEST_DONE_NIL = 0x1B95C, 0x1E, 0x1D
QUEST_TREE_MAX = 500


STALE_TARGET_AFTER = 0.6     # walk target with the position frozen this long is a leftover, not a walk


def _still_for(mem, x, y, now=None):
    """How long the position read through this handle has not changed (0 on first sight)."""
    now = time.monotonic() if now is None else now
    last = getattr(mem, '_last_xy', None)
    if last is None or last[0] != (x, y):
        mem._last_xy = ((x, y), now)
        return 0.0
    return now - last[1]


@dataclass(frozen=True)
class Dialog:
    text: str
    options: tuple  # ((select_id, label), ...); select_id 0 = 离开


@dataclass(frozen=True)
class WorldState:
    char_id: int
    map_id: int
    x: float                 # live motion position (the int32 x/y at +0x350 can lag)
    y: float
    target_x: float
    target_y: float
    flags: int
    busy: bool
    in_battle: bool
    nav_active: bool
    verification: bool
    my_sp: int | None = None          # own fighter's SP while in battle
    dialog: Dialog | None = field(default=None)
    still_for: float = 0.0            # seconds the position has not changed (read_world tracks it per handle)

    @property
    def moving(self):
        # A fresh character has target (0,0) while standing still at the spawn point.
        if self.target_x == 0 and self.target_y == 0:
            return False
        # A teleport (飞鞋, 回城卷, NPC, death) keeps the old walk target, e.g. (2100,1500) in the village after
        # leaving the well (live 2026-10-12). A real walk moves ~160 px/s, so a frozen position = stale target.
        if self.still_for >= STALE_TARGET_AFTER:
            return False
        return abs(self.x - self.target_x) >= 1 or abs(self.y - self.target_y) >= 1


def _client_pos(battle_real, side, my_real=None):
    """GetMyPos() / GetMyPetPos(): server position -> client position (RVA 0x130F0 / 0x13140). The side test
    always looks at the OWN real position (my_real defaults to battle_real for GetMyPos)."""
    my_real = battle_real if my_real is None else my_real
    if battle_real == 0xFF or my_real > 10 or not side:
        return battle_real
    if battle_real >= 15:
        return battle_real - 15
    if 10 <= battle_real <= 14:
        return battle_real - 5
    return battle_real + 15 if battle_real < 5 else battle_real + 5


def read_my_sp(mem):
    battle = mem.u32(mem.base + BATTLE_RVA)
    if not battle:
        return None
    pos = _client_pos(mem.u32(battle + BATTLE_REAL_POS), mem.u32(battle + BATTLE_SIDE))
    if not 0 <= pos < 20:
        return None
    fighter = battle + BATTLE_FIGHTERS + pos * FIGHTER_SIZE
    if mem.u32(fighter) == 0xFFFFFFFF:
        return None
    return struct.unpack('<i', mem.read(fighter + FIGHTER_SP, 4))[0]


def read_dialog(mem):
    """Open NPC dialog -> Dialog, else None. Options are the [URL]..[/URL] links in order."""
    ui = mem.u32(mem.base + UI_RVA)
    dlg = mem.u32(ui + UI_DIALOG)
    if not dlg or not mem.u32(dlg + DIALOG_VISIBLE):
        return None
    first, last = mem.u32(dlg + DIALOG_CTRL_FIRST), mem.u32(dlg + DIALOG_CTRL_LAST)
    if not first or last < first or (last - first) % 4 or (last - first) // 4 > 50:
        raise RuntimeError('NPC 对话框控件列表异常')
    controls = struct.unpack(f'<{(last - first) // 4}I', mem.read(first, last - first))
    text_ctrl = [c for c in controls if mem.read(c + 0x3C, 64).split(b'\0')[0] == b'OnlyReadText']
    if len(text_ctrl) != 1:
        raise RuntimeError(f'NPC 对话框文本控件数量异常: {len(text_ctrl)}')
    raw = mem.read(text_ctrl[0] + 0x108, 24)
    length, capacity = struct.unpack_from('<II', raw, 16)
    if length == 0:
        return None
    if not length <= capacity <= 100000:
        raise RuntimeError(f'NPC 对话文本长度异常 len={length} cap={capacity}')
    data = raw[:length] if capacity < 16 else mem.read(struct.unpack_from('<I', raw)[0], length)
    text = data.decode('gbk', 'replace')
    return Dialog(text, parse_options(text))


# Client 2.97 wrote options as [URL]label[/URL] (select id = position, 1-based); 2.98 writes [URL opt=N]label[/URL]
# (live 2026-10-15, 新手传送师: '[URL opt=1]逍遥村[/URL]'). The client's own pattern is \[URL(?:\s(.*?))?\](.*?)\[/URL\].
_OPTION = re.compile(r'\[URL(?:\s+([^\]]*))?\](.*?)\[/URL\]', re.S)
_OPT_ID = re.compile(r'(?<![A-Za-z0-9_])opt\s*=\s*(\d+)')


def parse_options(text):
    """Dialog text -> ((select_id, label), ...); select_id = opt=N when given, else the position; 离开 = 0."""
    options = []
    for index, (attrs, label) in enumerate(_OPTION.findall(text), 1):
        label = re.sub(r'#[0-9a-fA-F]{6}#', '', label).lstrip('★⊙').strip()
        m = _OPT_ID.search(attrs or '')
        options.append((0 if label == '离开' else int(m.group(1)) if m else index, label))
    return tuple(options)


def read_world(mem):
    """Full snapshot, or None while the own player / scene row does not exist yet (loading)."""
    base = mem.base
    player = mem.u32(base + PLAYER_PTR_RVA)
    session = mem.u32(base + SESSION_MGR_RVA)
    ui = mem.u32(base + UI_RVA)
    if not player or not session or not ui:
        return None
    char_id = struct.unpack('<i', mem.read(player + PLAYER_CHAR_ID, 4))[0]
    index = struct.unpack('<i', mem.read(session + SCENE_INDEX, 4))[0]
    first, last = mem.u32(session + SCENE_FIRST), mem.u32(session + SCENE_LAST)
    if not first or index < 0 or index >= (last - first) // SCENE_ROW:
        return None
    row = first + index * SCENE_ROW
    flags = mem.u32(row + ROW_FLAGS)
    entity = mem.u32(row + ROW_ENTITY)
    if not entity:
        return None
    x, y, _, _, tx, ty = struct.unpack('<6f', mem.read(entity + ENTITY_MOTION, 24))
    busy_mask = 0
    for rva in BUSY_MASK_RVAS:
        busy_mask |= mem.u32(base + rva)
    nav = mem.u32(mem.u32(ui + UI_NAV_MGR) + NAV_OBJECT) if mem.u32(ui + UI_NAV_MGR) else 0
    question = mem.u32(ui + UI_QUESTION)
    in_battle = bool(flags & FLAG_IN_BATTLE)
    return WorldState(
        char_id=char_id, map_id=mem.u32(session + SESSION_MAP_ID), x=x, y=y, target_x=tx, target_y=ty,
        flags=flags, busy=bool(flags & busy_mask), in_battle=in_battle,
        nav_active=bool(nav and mem.read(nav + NAV_ACTIVE, 1)[0]),
        verification=bool(question and mem.u32(question + QUESTION_ACTIVE)),
        my_sp=read_my_sp(mem) if in_battle else None,
        dialog=None if in_battle else read_dialog(mem),
        still_for=_still_for(mem, x, y),
    )


@dataclass(frozen=True)
class BagSlot:
    slot: int
    item_id: int
    quantity: int


def read_level(mem):
    session = mem.u32(mem.base + SESSION_MGR_RVA)
    if not session:
        return None
    return struct.unpack('<H', mem.read(session + SESSION_LEVEL, 2))[0]


def read_bag(mem):
    """Occupied bag slots in slot order, or None while the session does not exist."""
    session = mem.u32(mem.base + SESSION_MGR_RVA)
    if not session:
        return None
    table = session + BAG_TABLE
    count = mem.u32(table + BAG_COUNT)
    if count > BAG_MAX:
        raise RuntimeError(f'背包格数异常 {count}')
    raw = mem.read(table + BAG_FIRST, count * BAG_STRIDE) if count else b''
    slots = []
    for i in range(count):
        valid, item_id, _, _, quantity = struct.unpack_from('<5i', raw, i * BAG_STRIDE)
        if valid == 1 and item_id > 0 and quantity > 0:
            slots.append(BagSlot(i, item_id, quantity))
    return tuple(slots)


def read_equipment(mem):
    """Worn items as BagSlots (slot = equipment slot), or None while the session does not exist."""
    session = mem.u32(mem.base + SESSION_MGR_RVA)
    if not session:
        return None
    raw = mem.read(session + BAG_TABLE + EQUIP_TABLE, EQUIP_ROWS * BAG_STRIDE)
    out = []
    for i in range(EQUIP_ROWS):
        valid, item_id, _, _, quantity = struct.unpack_from('<5i', raw, i * BAG_STRIDE)
        if valid == 1 and item_id > 0:
            out.append(BagSlot(i, item_id, max(quantity, 1)))
    return tuple(out)


def free_bag_slot(bag, capacity):
    """Lowest empty bag slot, or None when the bag is full."""
    used = {s.slot for s in bag}
    return next((i for i in range(capacity) if i not in used), None)


def read_bag_capacity(mem):
    """Number of bag slots (40 on box01, 2026-10-20: the same count read_bag walks; empty slots have valid -1),
    or None while the session does not exist."""
    session = mem.u32(mem.base + SESSION_MGR_RVA)
    if not session:
        return None
    count = mem.u32(session + BAG_TABLE + BAG_COUNT)
    return count if 0 < count <= BAG_MAX else None


def read_gold(mem):
    session = mem.u32(mem.base + SESSION_MGR_RVA)
    if not session:
        return None
    gold = struct.unpack('<q', mem.read(session + BAG_TABLE + BAG_GOLD, 8))[0]
    if gold < 0:
        raise RuntimeError(f'金币读数异常 {gold}')
    return gold


def read_shoe_record(mem):
    """(map_id, x, y) the client shows as the 飞鞋 recorded point, or None while the UI does not exist."""
    ui = mem.u32(mem.base + UI_RVA)
    panel = mem.u32(ui + UI_SHOE_PANEL) if ui else 0
    if not panel:
        return None
    return struct.unpack('<3i', mem.read(panel + SHOE_MAP, 12))


@dataclass(frozen=True)
class Team:
    members: tuple          # char_ids in roster order; members[0] = leader; () = not in a team
    levels: tuple           # same order
    inviter: int            # char_id of the last invitation received (0 = none yet)

    @property
    def leader(self):
        return self.members[0] if self.members else 0


def read_team(mem):
    """The own client's team as the server last told it, or None while the UI does not exist."""
    ui = mem.u32(mem.base + UI_RVA)
    team = mem.u32(ui + UI_TEAM) if ui else 0
    vector = mem.u32(team + TEAM_ROSTER) if team else 0
    if not vector:
        return None
    first, last, capacity = struct.unpack('<3I', mem.read(vector, 12))
    if first == last:
        rows = b''
    elif not first or last < first or capacity < last or (last - first) % ROSTER_ROW \
            or (last - first) // ROSTER_ROW > ROSTER_MAX:
        raise RuntimeError(f'队伍名单异常 first={first:#x} last={last:#x} cap={capacity:#x}')
    else:
        rows = mem.read(first, last - first)
    pairs = [struct.unpack_from('<2I', rows, i) for i in range(0, len(rows), ROSTER_ROW)]
    return Team(tuple(p[0] for p in pairs), tuple(p[1] for p in pairs), mem.u32(team + TEAM_INVITER))


def team_object(mem):
    ui = mem.u32(mem.base + UI_RVA)
    return mem.u32(ui + UI_TEAM) if ui else 0


def read_invite_byte(mem):
    session = mem.u32(mem.base + SESSION_MGR_RVA)
    return mem.read(session + SESSION_INVITE_BYTE, 1)[0] if session else None


def item_count(bag, item_id):
    return sum(s.quantity for s in bag if s.item_id == item_id)


def read_talent_points(mem):
    session = mem.u32(mem.base + SESSION_MGR_RVA)
    return struct.unpack('<H', mem.read(session + SESSION_TALENT, 2))[0] if session else None


@dataclass(frozen=True)
class Fighter:
    pos: int                # client position
    sp: int
    dead: bool


@dataclass(frozen=True)
class Battle:
    me: Fighter | None
    pet: Fighter | None
    enemies: tuple          # client positions of live enemies, ascending


def _fighter(mem, battle, pos):
    if not 0 <= pos < 20:
        return None
    at = battle + BATTLE_FIGHTERS + pos * FIGHTER_SIZE
    if mem.u32(at) == 0xFFFFFFFF:
        return None
    dead = struct.unpack('<i', mem.read(at + FIGHTER_DEAD, 4))[0]
    sp = struct.unpack('<i', mem.read(at + FIGHTER_SP, 4))[0]
    return Fighter(pos, sp, bool(dead))


def read_battle(mem):
    """Own fighter, own pet and the live enemies while in battle, or None without a battle object."""
    battle = mem.u32(mem.base + BATTLE_RVA)
    if not battle:
        return None
    my_real, side = mem.u32(battle + BATTLE_REAL_POS), mem.u32(battle + BATTLE_SIDE)
    pet_real = mem.u32(battle + BATTLE_PET_REAL_POS)
    me = _fighter(mem, battle, _client_pos(my_real, side))
    pet = _fighter(mem, battle, _client_pos(pet_real, side, my_real))
    enemies = tuple(p for p in ENEMY_POSITIONS if (f := _fighter(mem, battle, p)) and not f.dead)
    return Battle(me, pet, enemies)


def _player_data(mem):
    session = mem.u32(mem.base + SESSION_MGR_RVA)
    return session + SESSION_PLAYER_DATA if session else 0


def _vector(mem, at, limit):
    first, last = struct.unpack('<2I', mem.read(at, 8))
    if first == last:
        return 0, 0
    if not first or last < first or last - first > limit:
        raise RuntimeError(f'向量异常 {at:#x}: first={first:#x} last={last:#x}')
    return first, last


def read_skill_level(mem, skill_id):
    """Learned level of a player skill (0 = not learned), or None while the session does not exist."""
    p = _player_data(mem)
    if not p:
        return None
    for k in SKILL_VECTORS:
        first, last = _vector(mem, p + SKILL_TABLE + k, 500 * SKILL_ROW)
        if (last - first) % SKILL_ROW:
            raise RuntimeError(f'技能表行长异常 {last - first:#x}')
        for at in range(first, last, SKILL_ROW):
            sid, a, b = struct.unpack('<3i', mem.read(at, 12))
            if sid == skill_id:
                return a + b
    return 0


@dataclass(frozen=True)
class Pet:
    index: int
    mp: int
    abilities: dict         # {ability id: level}


def read_fighting_pet(mem):
    """The pet set to fight, or None (no session / no pet)."""
    p = _player_data(mem)
    if not p:
        return None
    first, last = _vector(mem, p + PET_VECTOR, 4 * 50)
    index = struct.unpack('<i', mem.read(p + PET_FIGHTING, 4))[0]
    if not 0 <= index < (last - first) // 4:
        return None
    pet = mem.u32(first + 4 * index)
    if not pet:
        return None
    mp = struct.unpack('<q', mem.read(pet + PET_MP, 8))[0]
    af, al = _vector(mem, pet + PET_ABILITIES, 4 * 100)
    abilities = {}
    for ptr in struct.unpack(f'<{(al - af) // 4}I', mem.read(af, al - af)) if al > af else ():
        if ptr:
            aid, a, b = struct.unpack('<3i', mem.read(ptr, 12))
            abilities[aid] = a + b
    return Pet(index, mp, abilities)


def _tree_nodes(mem, head, node_size, nil_at):
    """Raw bytes of every node of an MSVC std::map / std::set (head = its sentinel node)."""
    nodes, stack, seen = [], [mem.u32(head + 4)], set()
    while stack:
        node = stack.pop()
        if not node or node == head or node in seen:
            continue
        if len(seen) >= QUEST_TREE_MAX:
            raise RuntimeError(f'任务树节点过多 head={head:#x}')
        seen.add(node)
        raw = mem.read(node, node_size)
        if raw[nil_at]:
            continue
        nodes.append(raw)
        stack += struct.unpack_from('<I', raw, 0) + struct.unpack_from('<I', raw, 8)
    return nodes


@dataclass(frozen=True)
class Quest:
    active: bool
    done: bool
    steps: tuple = ()       # status byte per step of the active quest (2 = finished, 1 = current, per the old reads)


def read_quest(mem, quest_id):
    """Quest state from the client's own task tables, or None while the session does not exist."""
    p = _player_data(mem)
    if not p:
        return None
    head, done_head = mem.u32(p + QUEST_ACTIVE), mem.u32(p + QUEST_DONE)
    if not head or not done_head:
        return None
    active = [raw for raw in _tree_nodes(mem, head, QUEST_ACTIVE_NODE, QUEST_ACTIVE_NIL)
              if struct.unpack_from('<I', raw, 0xC)[0] >> 16 == quest_id]
    done = any(struct.unpack_from('<I', raw, 0xC)[0] == quest_id
               for raw in _tree_nodes(mem, done_head, QUEST_DONE_NODE, QUEST_DONE_NIL))
    steps = tuple(active[0][0x27:0x27 + min(active[0][0x26], 0x3A) + 1]) if active else ()
    return Quest(bool(active), done, steps)


def nav_object(mem):
    """Navigation object for the official path-finder (0 when unavailable)."""
    ui = mem.u32(mem.base + UI_RVA)
    mgr = mem.u32(ui + UI_NAV_MGR) if ui else 0
    nav = mem.u32(mgr + NAV_OBJECT) if mgr else 0
    return nav if nav and mem.u32(nav + NAV_READY) else 0
