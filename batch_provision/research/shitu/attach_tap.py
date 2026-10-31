"""Attach the network tap to clients that are ALREADY in the world (not started by our launcher).

    python -X utf8 research/shitu/attach_tap.py [role ...]      (default: mm01 欧皇)

What it does, per window:
  1. copies bin/provision_native.dll to research/shitu/bin/ (so its tap files land in research/shitu/runtime/),
     named by its content (fresh_dll)
  2. creates the DLL's status block Local\\MXBLLoginReplica_<pid> (normally made by launcher.exe)
  3. loads the DLL into the game (remote LoadLibraryW, same as launcher.exe inject())
  4. marks the status block stage 8 (= in world) and sends DLL command 100 (arm) to the window
     -> MinHook on the client's send function (+0x316AB0) and ws2_32 send/recv/WSASend; every packet is
        appended to research/shitu/runtime/tap_<pid>.jsonl. Observation only: nothing is sent.
The DLL cannot be unloaded again; it goes away when the game window is closed. The login thread is never started
(it only runs on command 13, which nothing sends).
"""
import ctypes
import hashlib
import re
import struct
import sys
import time
from ctypes import wintypes as W

from common import BIN, ROOT, RUNTIME, DEFAULT_ROLES, find_roles, modules
from provisioner import native

_k = ctypes.WinDLL('kernel32', use_last_error=True)
_k.OpenProcess.restype = W.HANDLE
_k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
_k.VirtualAllocEx.restype = ctypes.c_void_p
_k.VirtualAllocEx.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_size_t, W.DWORD, W.DWORD]
_k.VirtualFreeEx.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_size_t, W.DWORD]
_k.WriteProcessMemory.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
_k.CreateRemoteThread.restype = W.HANDLE
_k.CreateRemoteThread.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p, W.DWORD, ctypes.c_void_p]
_k.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
_k.GetExitCodeThread.argtypes = [W.HANDLE, ctypes.POINTER(W.DWORD)]
_k.CloseHandle.argtypes = [W.HANDLE]
_k.CreateFileMappingW.restype = W.HANDLE
_k.CreateFileMappingW.argtypes = [W.HANDLE, ctypes.c_void_p, W.DWORD, W.DWORD, W.DWORD, W.LPCWSTR]
_k.MapViewOfFile.restype = ctypes.c_void_p
_k.MapViewOfFile.argtypes = [W.HANDLE, W.DWORD, W.DWORD, W.DWORD, ctypes.c_size_t]

STATUS_SIZE = 48
ACCESS = 0x0002 | 0x0008 | 0x0010 | 0x0020 | 0x0400   # CREATE_THREAD | VM_OPERATION | VM_READ | VM_WRITE | QUERY_INFO


def export_rva(dll_path, name):
    """RVA of an exported function, read from the PE file on disk (32-bit kernel32 from 64-bit Python)."""
    data = open(dll_path, 'rb').read()
    pe = struct.unpack_from('<I', data, 0x3C)[0]
    sections = []
    nsec, opt_size = struct.unpack_from('<H', data, pe + 6)[0], struct.unpack_from('<H', data, pe + 20)[0]
    for i in range(nsec):
        at = pe + 24 + opt_size + i * 40
        vsize, va, rsize, raw = struct.unpack_from('<4I', data, at + 8)
        sections.append((va, max(vsize, rsize), raw))

    def off(rva):
        for va, size, raw in sections:
            if va <= rva < va + size:
                return rva - va + raw
        raise ValueError(f'rva {rva:#x}')
    exp_rva = struct.unpack_from('<I', data, pe + 24 + 96)[0]          # PE32 data directory 0
    e = off(exp_rva)
    nnames, funcs, names, ords = struct.unpack_from('<4I', data, e + 24)
    for i in range(nnames):
        n = off(struct.unpack_from('<I', data, off(names) + 4 * i)[0])
        if data[n:data.index(b'\0', n)] == name.encode():
            o = struct.unpack_from('<H', data, off(ords) + 2 * i)[0]
            return struct.unpack_from('<I', data, off(funcs) + 4 * o)[0]
    raise KeyError(name)


def inject(pid, dll):
    k32 = [(b, p) for b, p in modules(pid) if p.lower().endswith('\\kernel32.dll')]
    if not k32:
        raise RuntimeError('目标进程里没找到 32 位 kernel32.dll')
    base, path = k32[0]
    # GetModuleFileNameEx reports System32 for a WOW64 process; 64-bit Python must read the 32-bit file
    path = re.sub(r'(?i)\\system32\\', r'\\SysWOW64\\', path)
    start = base + export_rva(path, 'LoadLibraryW')
    h = _k.OpenProcess(ACCESS, False, pid)
    if not h:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        text = (str(dll) + '\0').encode('utf-16-le')
        remote = _k.VirtualAllocEx(h, None, len(text), 0x3000, 0x04)
        if not remote:
            raise ctypes.WinError(ctypes.get_last_error())
        done = ctypes.c_size_t()
        if not _k.WriteProcessMemory(h, remote, text, len(text), ctypes.byref(done)):
            raise ctypes.WinError(ctypes.get_last_error())
        t = _k.CreateRemoteThread(h, None, 0, start, remote, 0, None)
        if not t:
            raise ctypes.WinError(ctypes.get_last_error())
        _k.WaitForSingleObject(t, 15000)
        code = W.DWORD()
        _k.GetExitCodeThread(t, ctypes.byref(code))
        _k.CloseHandle(t)
        _k.VirtualFreeEx(h, remote, 0, 0x8000)
        if not code.value:
            raise RuntimeError('LoadLibraryW 返回 0（DLL 没加载上）')
        return code.value
    finally:
        _k.CloseHandle(h)


def attach(role, pid, dll):
    if native.has_dll(pid):
        st = native.read_status(pid)
        print(f'[{role}] 已经有状态块 stage={st["stage"]}，只补发 arm')
    else:
        mapping = _k.CreateFileMappingW(W.HANDLE(-1), None, 0x04, 0, STATUS_SIZE, f'Local\\MXBLLoginReplica_{pid}')
        if not mapping:
            raise ctypes.WinError(ctypes.get_last_error())
        view = _k.MapViewOfFile(mapping, 0xF001F, 0, 0, STATUS_SIZE)
        ctypes.memset(view, 0, STATUS_SIZE)
        handle = inject(pid, dll)
        print(f'[{role}] DLL 已加载 module={handle:#x}')
        for _ in range(100):
            st = native.read_status(pid)
            if st['stage'] == 1 and st['hwnd']:
                break
            time.sleep(0.2)
        else:
            raise RuntimeError(f'DLL 初始化没完成: {st}')
        ctypes.c_long.from_address(view).value = native.WORLD_STAGE   # in world: allows arm (and nothing else we use)
    st = native.read_status(pid)
    session = native.Session(pid, st['hwnd'], st['game_base'])
    native.arm(session)
    tap = RUNTIME / f'tap_{pid}.jsonl'
    print(f'[{role}] arm 成功，录包文件 {tap} (存在={tap.is_file()})')
    return locals().get('mapping')


def fresh_dll(src=None, bin_dir=None):
    """bin/provision_native.dll copied to research/shitu/bin/ under a name from its content (the DLL writes its tap
    files to <own dir>/../runtime, the name does not matter). A copy is never overwritten: a game that loaded it keeps
    the file locked, and one fixed name kept the first copy for ever (2026-10-31: research/shitu/bin held the 10-26
    DLL from before the 10-29 game update -> 亿万1 got it and arm was refused)."""
    src = src or ROOT / 'bin' / 'provision_native.dll'
    bin_dir = bin_dir or BIN
    data = src.read_bytes()
    dll = bin_dir / f'provision_native_{hashlib.md5(data).hexdigest()[:8]}.dll'
    if not dll.is_file():
        bin_dir.mkdir(parents=True, exist_ok=True)
        tmp = dll.with_suffix('.tmp')
        tmp.write_bytes(data)
        tmp.replace(dll)
    return dll


def main(roles):
    RUNTIME.mkdir(exist_ok=True)
    dll = fresh_dll()
    found = find_roles(roles)
    for r in roles:
        if r not in found:
            print(f'[{r}] 没找到窗口')
            continue
        attach(r, found[r][0], dll)


if __name__ == '__main__':
    main(tuple(sys.argv[1:]) or DEFAULT_ROLES)
