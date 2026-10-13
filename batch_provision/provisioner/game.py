"""In-game actions: each wraps exactly one client function, called on the window thread.

RVAs and calling conventions come from earlier research (Codex/Gemini pp_runtime/bridge.py,
the parts that were exercised live) and were re-checked by disassembly on 2026-10-12.
Callers must check state first (map, busy, battle); these functions do not decide anything.
"""
import ctypes
import struct
from ctypes import wintypes as W

from . import native
from .world import nav_object, team_object

RVA_MOVE_TO = 0x111D0        # stdcall MoveTo(x, y): same-map walk
RVA_NAVIGATE = 0x18A3C0      # official path-finder: ECX=map, EDX=x, EAX=y, stack=nav object
RVA_CANCEL_NAV = 0x18A2C0    # EAX=nav object
RVA_CLICK_NPC = 0x10B70      # stdcall ClickNpc(npc_id)
RVA_SELECT_DIALOG = 0x11660  # stdcall SelectNpcDialogEntry(index); 0 = 离开
RVA_FIGHT_CMD = 0x16B900     # cdecl SendFightCmdPacket(is_pet, target_client_pos, action, param) -> 0x1004

# Fight actions (CFightCmdSelf factory RVA 0x23A210, 2026-10-12): 2 = 普攻, 0xB = 捕捉 (level check
# in 0x237A70), 8 = 逃跑 — confirmed live on mw01..08: 7 novice battles, each ended 0.6..2 s after the
# escape sent on SP 0->1 (the one sent at SP 0 does nothing). 7 / 9 are the other self commands.
FIGHT_ATTACK = 2
FIGHT_ESCAPE = 8

# The client's own packet sender (same one DLL command 103 uses for 0x0002 create):
# ESI = connection object [base+0x6390F8] (its +0x20 socket must not be -1), EBX = opcode,
# EDI = body length, stack = body pointer; ret 4. It encodes and queues the packet itself.
RVA_SEND = 0x310850
RVA_CONNECTION = 0x6390F8
CONNECTION_SOCKET = 0x20
MAX_BODY = 512

# 0x0049 use item (Codex/Gemini mw_items_20261009, bytes matched the real WSASend): 19 bytes,
# <IIiI>(0,0,-1,0) + (0, bag slot, 1). The server looks the item up by slot and uses exactly 1.
OP_USE_ITEM = 0x0049

# 飞鞋 (built-in, character bag): the panel's button handler RVA 0x1c7d50 sends 0x82 = record the current
# position, 0x83 = return to it, each with 4 bytes taken from an UNINITIALISED stack slot, so the server
# ignores the body. The server decides position and cooldown. Verified live 2026-10-12 with 4 zero bytes:
# record took the server's position (exact only after standing still ~1 s), return jumped 70 px back in
# 0.2 s, a second return within the hour did nothing (chat says 飞行器尚未就绪).
OP_SHOE_RECORD, OP_SHOE_RETURN = 0x82, 0x83
SHOE_BODY = b'\0' * 4

# Trade (Codex/Gemini character_trade.py, gold trades verified live 2026-10-09 with server receipts;
# opcodes re-found in the client 2026-10-12: 0x60 sent at RVA 0x143752/0x2322b4, 0x62 = 8-byte reply
# next to the invite dialog, 0x63 offer at 0x2335ff, 0x64/0x65 chosen by one flag at 0x23391f).
# Order: A invites B (0x60) -> B accepts (0x61) -> A offers (0x63) -> A confirms (0x65)
#        -> B offers nothing (0x63, 16 zero bytes) -> B confirms (0x65).
# The invite dialog stays open on the INVITED side after a network accept, so stations always invite.
OP_TRADE_INVITE, OP_TRADE_ACCEPT, OP_TRADE_OFFER, OP_TRADE_CONFIRM = 0x60, 0x61, 0x63, 0x65
TRADE_CONFIRM_BODY = struct.pack('<I', 17)

# Team (disassembly 2026-10-12; call sites from Codex pp_runtime/bridge.py opcodes 6/9/10, used live 2026-10-09):
# - invite: RVA 0x21b540 builds 0x30, 33 bytes: <I target><I high half, left uninitialised by the client>
#   <I own level><I session+0x135C byte><17s own name, NUL-terminated>. We send it through RVA_SEND ourselves.
# - accept: RVA 0x21d000 (ECX = team object [ui+0xDA0]) answers the invitation from [team+0xA8] with 0x31
#   (49 bytes, mostly uninitialised) and hides the invite dialog, so we call the client's own function.
# - leave: RVA 0x29ce60 (no arguments) sends 0x33 with 8 zero bytes.
OP_TEAM_INVITE = 0x30
RVA_TEAM_ACCEPT = 0x21D000
RVA_TEAM_LEAVE = 0x29CE60
TEAM_NAME_SIZE = 17


# Battle casts: the functions the client registers for Lua (push func; push name at RVA 0xbf46 / 0xbf55), both
# stdcall(target client pos, id, level), ret 0xC; they convert the position themselves (disassembled 2026-10-12).
# CastSkillToFighter sends 0x1005 (16 bytes), CastPetMagicToFighter sends 0x1004. Lua NormalAttack /
# PetNormalAttack (RVA 0x12DB0 / 0x12DE0) are just SendFightCmdPacket(is_pet, target, 2, 0) = fight_command().
RVA_CAST_SKILL = 0x12ED0
RVA_CAST_PET_MAGIC = 0x12F90

# Talent points (bb01 2026-10-05, TALENT_ALLOCATION_BB_20261005.md): 0x0070, 24 bytes <6i>, the 4th = 体质 delta.
# The server answers 0x4740 and ignores a request for more points than remain.
OP_TALENT = 0x0070


def talent_body(constitution):
    if not 0 < constitution < 1000:
        raise ValueError(f'体质点数 {constitution} 不合法')
    return struct.pack('<6i', 0, 0, 0, constitution, 0, 0)


def team_invite_body(target_id, level, invite_byte, name):
    raw = name.encode('gbk')
    if not raw or len(raw) >= TEAM_NAME_SIZE:
        raise ValueError(f'角色名 {name!r} 长度不合法')
    return struct.pack('<4I', target_id, 0, level, invite_byte) + raw.ljust(TEAM_NAME_SIZE, b'\0')


def trade_invite_body(target_id):
    return struct.pack('<I', target_id) + bytes(21)


def trade_accept_body(inviter_id):
    return struct.pack('<2I', inviter_id, 0)


def trade_gold_offer_body(amount):
    return struct.pack('<IqI', 0, amount, 0)


def trade_item_offer_body(slot, quantity):
    """0x63 with one bag entry, 24 bytes <IqIII>(0, gold 0, entry count 1, bag slot, quantity). Shape from the old
    runtime's UI capture (Gemini mwxqll_game reference_runtime/item_trade.py, quantity 1 only); not yet live-tested
    by us."""
    if not 0 <= slot < 256 or not 1 <= quantity <= 99:
        raise ValueError(f'背包格 {slot} / 数量 {quantity} 超出范围')
    return struct.pack('<IqIII', 0, 0, 1, slot, quantity)


class NotSent(RuntimeError):
    """Raised by the checks before the call: the request certainly did not reach the client's sender."""


def use_item_body(slot):
    if not 0 <= slot < 256:
        raise ValueError(f'背包格号 {slot} 超出范围')
    return struct.pack('<IIiI', 0, 0, -1, 0) + bytes((0, slot, 1))


_k = ctypes.WinDLL('kernel32', use_last_error=True)
_k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
_k.OpenProcess.restype = W.HANDLE
_k.VirtualAllocEx.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_size_t, W.DWORD, W.DWORD]
_k.VirtualAllocEx.restype = ctypes.c_void_p
_k.VirtualFreeEx.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_size_t, W.DWORD]
_k.WriteProcessMemory.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                  ctypes.POINTER(ctypes.c_size_t)]
_k.CloseHandle.argtypes = [W.HANDLE]


class _RemoteBuffer:
    """One page inside the game process for request bodies; allocated once, freed on close()."""
    SIZE = 4096

    def __init__(self, pid):
        self.handle = _k.OpenProcess(0x0008 | 0x0020, False, pid)  # VM_OPERATION | VM_WRITE
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.address = _k.VirtualAllocEx(self.handle, None, self.SIZE, 0x3000, 0x04)  # commit, READWRITE
        if not self.address:
            err = ctypes.get_last_error()
            _k.CloseHandle(self.handle)
            raise ctypes.WinError(err)

    def write(self, data):
        if len(data) > self.SIZE:
            raise ValueError('请求体太大')
        buf = ctypes.create_string_buffer(data, len(data))
        done = ctypes.c_size_t()
        if not _k.WriteProcessMemory(self.handle, self.address, buf, len(data), ctypes.byref(done)) \
                or done.value != len(data):
            raise ctypes.WinError(ctypes.get_last_error())
        return self.address

    def close(self):
        if self.handle:
            _k.VirtualFreeEx(self.handle, self.address, 0, 0x8000)  # MEM_RELEASE
            _k.CloseHandle(self.handle)
            self.handle = None


class Game:
    """Actions for one client. `mem` is an open ProcessMemory of the same process."""

    def __init__(self, session, mem):
        self.session, self.mem = session, mem
        self._buffer = None

    def close(self):
        if self._buffer:
            self._buffer.close()
            self._buffer = None

    def _check_connection(self):
        conn = self.mem.u32(self.mem.base + RVA_CONNECTION)
        if not conn or self.mem.u32(conn + CONNECTION_SOCKET) == 0xFFFFFFFF:
            raise NotSent('网络连接已断开（socket=-1），没有发送')
        return conn

    def send(self, opcode, body):
        """One request through the client's own sender on the window thread (no raw socket writes)."""
        if not 0 < len(body) <= MAX_BODY:
            raise ValueError(f'请求体长度 {len(body)} 不合法')
        conn = self._check_connection()
        if self._buffer is None:
            self._buffer = _RemoteBuffer(self.session.pid)
        address = self._buffer.write(body)
        return native.call(self.session, RVA_SEND, address, esi=conn, ebx=opcode, edi=len(body))

    def use_item(self, slot):
        return self.send(OP_USE_ITEM, use_item_body(slot))

    def shoe_record(self):
        return self.send(OP_SHOE_RECORD, SHOE_BODY)

    def shoe_return(self):
        return self.send(OP_SHOE_RETURN, SHOE_BODY)

    def trade_invite(self, target_id):
        return self.send(OP_TRADE_INVITE, trade_invite_body(target_id))

    def trade_accept(self, inviter_id):
        return self.send(OP_TRADE_ACCEPT, trade_accept_body(inviter_id))

    def trade_offer_gold(self, amount):
        return self.send(OP_TRADE_OFFER, trade_gold_offer_body(amount))

    def trade_offer_item(self, slot, quantity):
        return self.send(OP_TRADE_OFFER, trade_item_offer_body(slot, quantity))

    def trade_confirm(self):
        return self.send(OP_TRADE_CONFIRM, TRADE_CONFIRM_BODY)

    def team_invite(self, target_id, level, invite_byte, name):
        return self.send(OP_TEAM_INVITE, team_invite_body(target_id, level, invite_byte, name))

    def team_accept(self):
        team = team_object(self.mem)
        if not team:
            raise NotSent('队伍对象不存在，没有发送')
        self._check_connection()
        return native.call(self.session, RVA_TEAM_ACCEPT, ecx=team)

    def team_leave(self):
        self._check_connection()
        return native.call(self.session, RVA_TEAM_LEAVE)

    def move_to(self, x, y):
        return native.call(self.session, RVA_MOVE_TO, int(x), int(y))

    def navigate(self, map_id, x, y):
        nav = nav_object(self.mem)
        if not nav:
            raise RuntimeError('寻路对象不可用')
        return native.call(self.session, RVA_NAVIGATE, nav, ecx=map_id, edx=int(x), eax=int(y))

    def cancel_navigation(self):
        nav = nav_object(self.mem)
        if nav:
            native.call(self.session, RVA_CANCEL_NAV, eax=nav)

    def click_npc(self, npc_id):
        return native.call(self.session, RVA_CLICK_NPC, npc_id)

    def select_dialog(self, index):
        return native.call(self.session, RVA_SELECT_DIALOG, index)

    def fight_command(self, action, is_pet=False, target=0, param=0):
        return native.call(self.session, RVA_FIGHT_CMD, int(is_pet), target, action, param)

    def cast_skill(self, target, skill_id, level):
        return native.call(self.session, RVA_CAST_SKILL, target, skill_id, level)

    def cast_pet_magic(self, target, magic_id, level):
        return native.call(self.session, RVA_CAST_PET_MAGIC, target, magic_id, level)

    def add_constitution(self, points):
        return self.send(OP_TALENT, talent_body(points))
