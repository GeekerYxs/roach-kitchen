"""Pure decoding of the DLL tap into battles: packet framing, 0x4100 / 0x4101 / 0x472A layouts, battle assembly.

No game access. Layouts read from tap files of 2026-10-27/28 (client 2.100/2.101, 师徒 line) and checked:
- 0x472A +4 own exp matched the exp monitor's memory reading in 1697 of 1706 battles on 亿万1/17/25 (the misses are
  battles the monitor split differently). Pet exp +20, training +28, potential +32 are the offsets Codex checked
  against the result panel on 2026-09-30 (EXP_03B_GRASSLAND_TRIAL.md). In 八阵图 the apprentices often got exactly
  twice the pet exp (1968 / 984; Codex's lineup there gave 984 without a buff): most likely a character-only double.
- dropped items: every item id of three roles' 1600 drops exists in factory/data/items.csv.
- 0x4101 monsters in 八阵图 = 1197/1198/1203 at levels 21/22, same as the fighter-level rows read from memory.
Everything not understood stays in the raw bodies the store keeps (raw_4100 / raw_4101 / raw_472a / packets).
"""
import json
import struct
import zlib
from dataclasses import dataclass, field

OP_MAP, OP_LINEUP, OP_RESULT, OP_LEVEL_UP = 0x4100, 0x4101, 0x472A, 0x4210
RECV, SEND = 0, 1

# 0x4101: 46-byte head (+0 own char id, +40 own pos, +41 own pet pos, +42 players, +43 units), then the OTHER
# players (the own role is not listed: its name / level come from a teammate's file, see store.fill_from_teammates),
# then the units.
LINEUP_HEAD, PLAYER_SIZE, UNIT_SIZE, NAME_SIZE = 46, 91, 56, 17
# Some files (5 of 1171, 2026-10) end every 0x4101 with 6 more bytes, always 30 58 0a 00 01 00; meaning unknown.
LINEUP_TRAILER = 6
UNIT_MONSTER, UNIT_PET = 1, 2
# 0x472A: +140 monster npc ids (i32 x 10, -1 = none), +356 monster count, +358 item count, items of 11 bytes at +371.
RESULT_MONSTERS, RESULT_ITEM_COUNT, RESULT_ITEMS, ITEM_SIZE = 140, 358, 371, 11


@dataclass(frozen=True)
class Packet:
    tick: int           # GetTickCount ms of the tap record
    direction: int      # RECV (server -> client, decoded) or SEND (the client's own request, plain)
    opcode: int
    body: bytes


def tap_packets(lines, tables):
    """Tap jsonl lines (bytes or str) -> Packets in file order. Received bytes are one TCP stream: frames are
    <u16 ~len><u16 opcode><body>, body decoded with table ((opcode << 8) ^ ~len) % 10, +1 per byte (as TapReader)."""
    stream, pos = bytearray(), 0
    ticks = []          # (stream offset where a wire_recv record starts, its tick); a frame gets its first byte's tick
    out = []
    for line in lines:
        r = json.loads(line)
        if r['kind'] == 'request':
            out.append(Packet(r['tick'], SEND, r['opcode'], bytes.fromhex(r['hex'])))
            continue
        if r['kind'] != 'wire_recv':
            continue
        ticks.append((len(stream), r['tick']))
        stream += bytes.fromhex(r['hex'])
        while pos + 4 <= len(stream):
            inverted, opcode = struct.unpack_from('<HH', stream, pos)
            length = ~inverted & 0xFFFF
            if pos + 4 + length > len(stream):
                break
            while len(ticks) > 1 and ticks[1][0] <= pos:
                ticks.pop(0)
            index = ((opcode << 8) ^ inverted) % 10
            body = bytes(tables[(index + i) % 10][v] for i, v in enumerate(stream[pos + 4:pos + 4 + length]))
            out.append(Packet(ticks[0][1], RECV, opcode, body))
            pos += 4 + length
        if pos:                                  # drop consumed bytes (a partial frame stays)
            del stream[:pos]
            head = [t for o, t in ticks if o <= pos][-1:]        # the record holding the first byte left
            ticks = [(0, t) for t in head] + [(o - pos, t) for o, t in ticks if o > pos]
            pos = 0
    return out


def parse_map(body):
    """0x4100 -> (map id, x, y) where the battle started."""
    return struct.unpack_from('<3H', body)


@dataclass(frozen=True)
class Player:
    char_id: int
    name: str
    level: int
    pos: int            # client position
    hp: int
    hp_max: int


@dataclass(frozen=True)
class Unit:
    npc_id: int
    kind: int           # UNIT_MONSTER / UNIT_PET (a team member's pet)
    level: int
    pos: int
    hp: int
    hp_max: int


@dataclass(frozen=True)
class Lineup:
    own_id: int
    own_pos: int
    own_pet_pos: int
    players: tuple          # the other players
    units: tuple

    @property
    def monsters(self):
        return tuple(u for u in self.units if u.kind == UNIT_MONSTER)


def _name(raw):
    return raw.split(b'\0')[0].decode('gbk', 'replace')


def parse_lineup(body):
    """0x4101 battle start. Players: +0 hp i64, +8 hp max, +24 char id, +64 level, +73 pos, +74 name[17].
    Units: +0 hp i64, +8 hp max, +24 npc id, +28 level, +37 pos, +38 kind."""
    players_n, units_n = body[42], body[43]
    if len(body) - (LINEUP_HEAD + PLAYER_SIZE * players_n + UNIT_SIZE * units_n) not in (0, LINEUP_TRAILER):
        raise ValueError(f'0x4101 长度 {len(body)} 和 {players_n} 人 {units_n} 单位对不上')
    players = []
    for i in range(players_n):
        p = body[LINEUP_HEAD + PLAYER_SIZE * i:LINEUP_HEAD + PLAYER_SIZE * (i + 1)]
        hp, hp_max = struct.unpack_from('<qq', p)
        players.append(Player(struct.unpack_from('<I', p, 24)[0], _name(p[74:74 + NAME_SIZE]),
                              struct.unpack_from('<I', p, 64)[0], p[73], hp, hp_max))
    units, start = [], LINEUP_HEAD + PLAYER_SIZE * players_n
    for i in range(units_n):
        u = body[start + UNIT_SIZE * i:start + UNIT_SIZE * (i + 1)]
        hp, hp_max = struct.unpack_from('<qq', u)
        npc_id, level = struct.unpack_from('<II', u, 24)
        units.append(Unit(npc_id, u[38], level, u[37], hp, hp_max))
    return Lineup(struct.unpack_from('<I', body)[0], body[40], body[41], tuple(players), tuple(units))


@dataclass(frozen=True)
class Item:
    item_id: int
    qty: int
    slot: int           # bag slot it went into


@dataclass(frozen=True)
class Result:
    char_id: int
    exp: int            # signed: a death can give a net loss
    pet_exp: int
    pet_training: int
    potential: int
    monster_ids: tuple
    items: tuple


def parse_result(body):
    """0x472A battle result for the own role."""
    char_id, exp = struct.unpack_from('<Iq', body)
    pet_exp = struct.unpack_from('<q', body, 20)[0]
    training, potential = struct.unpack_from('<II', body, 28)
    ids = tuple(x for x in struct.unpack_from('<10i', body, RESULT_MONSTERS) if x > 0)
    items = []
    for i in range(body[RESULT_ITEM_COUNT]):
        at = RESULT_ITEMS + ITEM_SIZE * i
        if at + ITEM_SIZE > len(body):
            raise ValueError(f'0x472A 物品 {i} 超出包长 {len(body)}')
        item_id, qty = struct.unpack_from('<IH', body, at)
        items.append(Item(item_id, qty, body[at + 8]))
    return Result(char_id, exp, pet_exp, training, potential, ids, tuple(items))


def level_up(body):
    """0x4210 -> (char id, new level); the level is the low u16 (the high half carries flags)."""
    return struct.unpack_from('<I', body, 8)[0], struct.unpack_from('<H', body)[0]


def pack_packets(packets, t0):
    """Packets -> zlib blob of <i32 ms since t0><u8 direction><u32 opcode><u32 len><body> (kept for later decoding)."""
    raw = b''.join(struct.pack('<iBII', p.tick - t0, p.direction, p.opcode, len(p.body)) + p.body for p in packets)
    return zlib.compress(raw, 6)


def unpack_packets(blob, t0):
    raw, out, at = zlib.decompress(blob), [], 0
    while at < len(raw):
        dt, direction, opcode, n = struct.unpack_from('<iBII', raw, at)
        at += 13
        out.append(Packet(t0 + dt, direction, opcode, raw[at:at + n]))
        at += n
    return out


@dataclass
class Battle:
    own_id: int = 0
    start_tick: int = 0             # 0x4100 (or 0x4101 when the map packet was missed)
    end_tick: int | None = None     # 0x472A; None = no result seen (window closed, disconnect, file cut)
    patrol_ms: int | None = None    # previous result -> this start; None for the first battle of a file
    map_id: int | None = None
    x: int | None = None
    y: int | None = None
    lineup: Lineup | None = None
    result: Result | None = None
    level_after: int | None = None  # from 0x4210 inside the battle
    raw_map: bytes = b''
    raw_lineup: bytes = b''
    raw_result: bytes = b''
    packets: list = field(default_factory=list)     # everything between start and result, both directions
    errors: list = field(default_factory=list)



def assemble(packets):
    """Packets of one tap file -> Battles in order. A battle opens at 0x4100 (or a 0x4101 without one), collects every
    packet until the own 0x472A. An open battle without a result is still returned (end_tick None)."""
    out, cur, last_end = [], None, None
    for p in packets:
        if p.direction == RECV and p.opcode == OP_MAP:
            if cur:
                out.append(cur)
            cur = Battle(start_tick=p.tick, raw_map=p.body)
            cur.patrol_ms = p.tick - last_end if last_end is not None else None
            try:
                cur.map_id, cur.x, cur.y = parse_map(p.body)
            except struct.error as e:
                cur.errors.append(f'0x4100: {e}')
            continue
        if p.direction == RECV and p.opcode == OP_LINEUP:
            if cur is None or cur.raw_lineup:
                if cur:
                    out.append(cur)
                cur = Battle(start_tick=p.tick)
                cur.patrol_ms = p.tick - last_end if last_end is not None else None
            cur.raw_lineup = p.body
            try:
                cur.lineup = parse_lineup(p.body)
                cur.own_id = cur.lineup.own_id
            except (ValueError, struct.error) as e:
                cur.errors.append(f'0x4101: {e}')
                cur.own_id = struct.unpack_from('<I', p.body)[0] if len(p.body) >= 4 else 0
            continue
        if cur is None:
            continue
        cur.packets.append(p)
        if p.direction != RECV:
            continue
        if p.opcode == OP_LEVEL_UP and len(p.body) >= 12:
            who, level = level_up(p.body)
            if who == cur.own_id:
                cur.level_after = level
        elif p.opcode == OP_RESULT and len(p.body) >= 4 and struct.unpack_from('<I', p.body)[0] == cur.own_id:
            cur.end_tick, cur.raw_result = p.tick, p.body
            try:
                cur.result = parse_result(p.body)
            except (ValueError, struct.error) as e:
                cur.errors.append(f'0x472A: {e}')
            out.append(cur)
            last_end, cur = p.tick, None
    if cur:
        out.append(cur)
    return out
