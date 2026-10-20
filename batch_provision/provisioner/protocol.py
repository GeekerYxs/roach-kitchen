"""Create-role protocol (0x0002 -> 0x4003) and decoding of the DLL's recv tap.

Request body layout follows the client's own constructor at RVA 0xF3FF0..0xF411C;
every session-specific field is read from the SAME client that will send it.
"""
import json
import struct
from pathlib import Path

OP_CREATE_REPLY = 0x4003
CREATE_BODY_SIZE = 292


class SessionMismatch(RuntimeError):
    pass


def session_account(memory, context):
    """The account std::string inside the session context -> (128 raw bytes, debug text)."""
    account_field = context + 0x20                      # std::string (SSO when cap < 16)
    length, cap = memory.u32(context + 0x30), memory.u32(context + 0x34)
    if cap >= 16:
        account_field = memory.u32(account_field)
    raw = memory.read(account_field, 128)
    return raw, f'ctx={context:#x} len={length} cap={cap} data@{account_field:#x}={raw[:24].hex()}'


ROSTER_VECTOR = 0x90      # context+0x90: std::vector<RosterEntry> {begin, end, cap}
ROSTER_ENTRY = 0x6C       # entry: +0 u32 char_id, +4 u32 level, +0x14 char name[20]
MAX_SLOTS = 4


def read_roster(memory, context):
    """Role list the server sent for this account -> [(char_id, level, name)], slot order.
    Verified 2026-10-12 on mw01 (ids 202851.. matched the creation replies)."""
    begin, end = memory.u32(context + ROSTER_VECTOR), memory.u32(context + ROSTER_VECTOR + 4)
    if begin == end:
        return []
    size = end - begin
    if size < 0 or size % ROSTER_ENTRY or size // ROSTER_ENTRY > MAX_SLOTS:
        raise RuntimeError(f'选角列表结构异常 begin={begin:#x} end={end:#x}')
    data = memory.read(begin, size)
    roster = []
    for off in range(0, size, ROSTER_ENTRY):
        char_id, level = struct.unpack_from('<II', data, off)
        name = data[off + 0x14:off + 0x28].split(b'\0', 1)[0].decode('gbk', 'replace')
        roster.append((char_id, level, name))
    return roster


def read_roster_raw(memory, context):
    """The raw 0x6C-byte roster entries, slot order (for checks and diffs of fields not decoded yet)."""
    begin, end = memory.u32(context + ROSTER_VECTOR), memory.u32(context + ROSTER_VECTOR + 4)
    size = end - begin
    if size <= 0 or size % ROSTER_ENTRY or size // ROSTER_ENTRY > MAX_SLOTS:
        return []
    data = memory.read(begin, size)
    return [data[off:off + ROSTER_ENTRY] for off in range(0, size, ROSTER_ENTRY)]


def _session_body(memory, context, account, size):
    """Zeroed request body with the session fields both 0x0002 and 0x0003 start with:
    [0] = ctx+0x1C byte, [4:132] = account std::string (128 raw bytes), [136:] = token std::string."""
    raw_account, debug = session_account(memory, context)
    live = raw_account.split(b'\0', 1)[0]
    if live != account.encode('ascii'):
        raise SessionMismatch(f'进程内会话账号是 {live!r}，不是 {account!r}，拒绝发送 ({debug})')
    token_field = context + 0x74                        # std::string, length at +0x84
    token_length = min(memory.u32(context + 0x84), 128)
    if memory.u32(context + 0x88) >= 16:
        token_field = memory.u32(token_field)
    body = bytearray(size)
    body[0] = memory.read(context + 0x1C, 1)[0]
    body[4:132] = raw_account
    body[136:136 + token_length] = memory.read(token_field, token_length)
    return body


def encode_role_name(role):
    """Role name -> the GBK bytes of the 0x0002 request (the roster decodes names as GBK). Letters, digits and
    Chinese characters, 1..15 bytes (a Chinese character is 2): e.g. 'box07仓1' = 8 bytes."""
    try:
        role_b = role.encode('gbk')
    except UnicodeEncodeError:
        raise ValueError(f'角色名 {role!r} 含 GBK 编码不了的字') from None
    if not 1 <= len(role_b) <= 15 or not role.isalnum():
        raise ValueError(f'角色名必须是 1..15 字节的字母/数字/汉字（一个汉字算 2 字节）: {role!r}')
    return role_b


def build_create(memory, context, account, role):
    role_b = encode_role_name(role)
    body = _session_body(memory, context, account, CREATE_BODY_SIZE)
    # Default appearance values observed from the UI sample (male, blue hair).
    struct.pack_into('<II', body, 265, 3, 0)
    body[273:275] = bytes([1, 0])
    body[275:275 + len(role_b)] = role_b
    return bytes(body)


def parse_create_reply(payload):
    """0x4003 body: <uint32 character_id, uint16 result>; result 0 = success."""
    if len(payload) != 6:
        raise ValueError(f'0x4003 回包长度异常: {len(payload)} ({payload.hex()})')
    return struct.unpack('<IH', payload)


# Delete role (selection screen). The client's own builder is RVA 0xF4120 (send at 0xF434D, caller RVA 0xF4352):
# same session fields as create, char_id u32 at 265, and at 269 a NUL-terminated string (<= 16 chars) that
# the client fills from a UI field ONLY when the roster entry's +0x60 is non-zero (a protected role, it seems).
# Four 2026-10-09 UI captures (美味05..08) match this layout byte for byte, string empty.
OP_DELETE_REPLY = 0x4004
DELETE_BODY_SIZE = 286
DELETE_ID_OFFSET = 265
ROSTER_PROTECT = 0x60


def build_delete(memory, context, account, char_id):
    if not char_id:
        raise ValueError('角色 ID 不能为 0')
    body = _session_body(memory, context, account, DELETE_BODY_SIZE)
    struct.pack_into('<I', body, DELETE_ID_OFFSET, char_id)
    return bytes(body)


def parse_delete_reply(payload):
    """0x4004 body: <uint8 result, uint32 ms until the slot is released>; result 0 = accepted.
    2026-10-09 UI sample: 00 0014730f = 0, 259200000 ms (72 h)."""
    if len(payload) != 5:
        raise ValueError(f'0x4004 回包长度异常: {len(payload)} ({payload.hex()})')
    return struct.unpack('<BI', payload)


class TapReader:
    """Incrementally decodes server->client packets from runtime/tap_<pid>.jsonl."""

    def __init__(self, runtime_dir, pid):
        self.path = Path(runtime_dir) / f'tap_{pid}.jsonl'
        codec = json.loads((Path(runtime_dir) / f'tap_{pid}_codec.json').read_text())
        self.tables = [bytes.fromhex(x) for x in codec['decode']]
        self.offset = 0
        self.stream = b''

    def poll(self):
        """Return [(opcode, body)] received since the last call."""
        with open(self.path, 'rb') as f:
            f.seek(self.offset)
            chunk = f.read()
        end = chunk.rfind(b'\n') + 1          # only complete lines
        self.offset += end
        for line in chunk[:end].splitlines():
            record = json.loads(line)
            if record['kind'] == 'wire_recv':
                self.stream += bytes.fromhex(record['hex'])
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
