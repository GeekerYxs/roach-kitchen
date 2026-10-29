"""Own buffs (read-only): session+0x1D264 = head of an MSVC std::map (Gemini session e45999df, 2026-10-28):
node 0x30 bytes, isnil at +0x2D, value +0x10 = buff id, +0x20 = seconds left (u32).
暗影之力的庇佑 = 1900 (禁锢之地) .. 1905 (次元时空Ⅴ); 1902 = 次元时空Ⅱ = map 1202."""
import struct

from provisioner.world import SESSION_MGR_RVA, _tree_nodes

BUFF_TREE = 0x1D264
SHADOW = range(1900, 1906)


def read_buffs(mem):
    """{buff id: seconds left}."""
    session = mem.u32(mem.base + SESSION_MGR_RVA)
    head = mem.u32(session + BUFF_TREE) if session else 0
    if not head:
        return {}
    return {struct.unpack_from('<I', n, 0x10)[0]: struct.unpack_from('<I', n, 0x20)[0]
            for n in _tree_nodes(mem, head, 0x30, 0x2D)}


def shadow_left(mem):
    """(buff id, seconds left) of 暗影之力的庇佑, or None."""
    b = {k: v for k, v in read_buffs(mem).items() if k in SHADOW}
    return max(b.items(), key=lambda kv: kv[1]) if b else None
