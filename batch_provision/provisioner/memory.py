"""Read-only access to a game process: raw reads and a private-memory pattern scan."""
import ctypes
import struct
from ctypes import wintypes as W

SESSION_VTABLE_RVA = 0x4A1A54   # vtable of the login/session context object
NETWORK_MANAGER_RVA = 0x64B1B8  # global pointer to the connection object
CONTEXT_NETWORK_OFFSET = 0x150  # context+0x150 == *NETWORK_MANAGER


class _MBI(ctypes.Structure):
    _fields_ = [('BaseAddress', ctypes.c_void_p), ('AllocationBase', ctypes.c_void_p), ('AllocationProtect', W.DWORD),
                ('PartitionId', W.WORD), ('RegionSize', ctypes.c_size_t), ('State', W.DWORD), ('Protect', W.DWORD),
                ('Type', W.DWORD)]


_k = ctypes.WinDLL('kernel32', use_last_error=True)
_k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
_k.OpenProcess.restype = W.HANDLE
_k.ReadProcessMemory.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
_k.VirtualQueryEx.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.POINTER(_MBI), ctypes.c_size_t]
_k.VirtualQueryEx.restype = ctypes.c_size_t
_k.CloseHandle.argtypes = [W.HANDLE]

MEM_COMMIT, MEM_PRIVATE = 0x1000, 0x20000
CHUNK = 1024 * 1024


class ProcessMemory:
    def __init__(self, pid, base):
        self.pid, self.base = pid, base
        self.handle = _k.OpenProcess(0x0410, False, pid)  # QUERY_INFORMATION | VM_READ
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if self.handle:
            _k.CloseHandle(self.handle)
            self.handle = None

    def read(self, address, size):
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t()
        if not _k.ReadProcessMemory(self.handle, address, buf, size, ctypes.byref(got)) or got.value != size:
            raise RuntimeError(f'读内存失败 {address:#x}+{size}')
        return buf.raw

    def u32(self, address):
        return struct.unpack('<I', self.read(address, 4))[0]

    def _regions(self):
        address = 0
        while address < 0x80000000:
            info = _MBI()
            if not _k.VirtualQueryEx(self.handle, address, ctypes.byref(info), ctypes.sizeof(info)):
                break
            start = info.BaseAddress or 0
            address = start + info.RegionSize
            if info.State != MEM_COMMIT or info.Type != MEM_PRIVATE:
                continue
            if info.Protect & 0x101 or not info.Protect & 0xCC:  # skip GUARD/NOACCESS, need readable+writable
                continue
            yield start, info.RegionSize

    def scan(self, needles):
        """Find every occurrence of each byte pattern in writable private memory. -> {needle: [addr,...]}"""
        hits = {n: [] for n in needles}
        overlap = max(len(n) for n in needles) - 1
        for start, size in self._regions():
            for off in range(0, size, CHUNK):
                length = min(CHUNK + overlap, size - off)
                try:
                    data = self.read(start + off, length)
                except RuntimeError:
                    continue
                for n in needles:
                    at = 0
                    while (i := data.find(n, at)) >= 0:
                        if i < CHUNK:  # the overlap belongs to the next chunk
                            hits[n].append(start + off + i)
                        at = i + 1
        return hits

    def locate_context(self, extra_needles=()):
        """Unique session context (object with the session vtable whose +0x150 is the live connection).

        Also scans extra_needles in the same pass; returns (context, {needle: [addr]}).
        """
        vtable = struct.pack('<I', self.base + SESSION_VTABLE_RVA)
        hits = self.scan([vtable, *extra_needles])
        network = self.u32(self.base + NETWORK_MANAGER_RVA)
        found = []
        for candidate in hits.pop(vtable):
            try:
                if self.u32(candidate + CONTEXT_NETWORK_OFFSET) == network:
                    found.append(candidate)
            except RuntimeError:
                pass
        if len(found) != 1:
            raise RuntimeError(f'会话上下文应唯一，实际找到 {len(found)} 个 (network={network:#x})')
        return found[0], hits
