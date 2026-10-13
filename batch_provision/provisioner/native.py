"""Bridge to bin/launcher.exe and the injected provision_native.dll (WM_COPYDATA commands).

Only this module knows launcher arguments, exit codes, DLL command ids and window messages.
"""
import ctypes
import json
import mmap
import struct
import subprocess
import time
from ctypes import wintypes as W
from dataclasses import dataclass
from pathlib import Path

from .protocol import CREATE_BODY_SIZE, DELETE_BODY_SIZE

BIN = Path(__file__).resolve().parent.parent / 'bin'
LAUNCHER = BIN / 'launcher.exe'

LAUNCHER_EXIT = {
    0: '成功到达选角界面',
    2: '启动器参数错误',
    3: '游戏 EXE 的 SHA256 不匹配或文件不存在（版本不对）',
    4: '账号/密码长度不合法（需 1..15 字节）',
    5: 'ShellExecute 拉起游戏失败',
    6: 'OpenProcess 失败（权限？游戏以管理员运行时脚本也要管理员）',
    7: '诊断共享内存创建失败',
    8: 'DLL 注入失败（游戏还没初始化完，可调大 inject_delay_ms）',
    9: 'DLL 已注入但没找到游戏窗口/挂窗口过程失败',
    10: '登录参数被 DLL 拒绝',
    11: '登录流程中止或超时（见 stage/error）',
}
# login_dll.cpp fail(...) codes
DLL_ERROR = {
    0: '无',
    101: '30 秒内登录界面标志未出现（游戏没加载到登录页）',
    102: '找不到账号输入框对象',
    103: '读取账号输入框失败',
    104: '写入账号失败',
    105: '输入密码字符时窗口无响应',
    106: '40 秒内未进入选角（密码错误 / 账号已在线 / 服务器无响应）',
    107: '找不到选角界面对象',
    108: '写选角序号失败', 109: '写选角序号失败',
    110: '40 秒内没进入世界（该槽没有角色 / 角色在删除中 / 服务器无响应）',
    111: '内存分配失败', 112: '创建登录线程失败', 113: '30 秒内没找到游戏窗口', 114: '挂窗口过程失败',
}
STAGE = {0: '未开始', 1: '窗口已挂钩', 2: '等待登录页', 3: '账号已填', 4: '输入密码',
         5: '已提交登录，等待选角', 6: '选角', 7: '进入世界中', 8: '已进入世界', 9: '停在选角界面', -1: '失败'}
SELECTION_STAGE = 9
NOT_RETRYABLE = {2, 3, 4}

CMD_ARM, CMD_CREATE, CMD_ENTER, CMD_CALL, CMD_DELETE = 100, 103, 105, 106, 107
WORLD_STAGE = 8
OP_CREATE, OP_DELETE = 0x0002, 0x0003


class LaunchError(RuntimeError):
    def __init__(self, message, result, retryable):
        super().__init__(message)
        self.result, self.retryable = result, retryable


@dataclass(frozen=True)
class Session:
    pid: int
    hwnd: int
    base: int


class _CopyData(ctypes.Structure):
    _fields_ = [('kind', ctypes.c_size_t), ('size', W.DWORD), ('data', ctypes.c_void_p)]


_u = ctypes.WinDLL('user32', use_last_error=True)
_u.SendMessageTimeoutW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM, W.UINT, W.UINT, ctypes.POINTER(ctypes.c_size_t)]
_u.SendMessageTimeoutW.restype = W.LPARAM
_u.GetWindowThreadProcessId.argtypes = [W.HWND, ctypes.POINTER(W.DWORD)]
_u.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
_u.IsWindow.argtypes = [W.HWND]
_u.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, ctypes.c_int]
_k = ctypes.WinDLL('kernel32', use_last_error=True)
_k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
_k.OpenProcess.restype = W.HANDLE
_k.TerminateProcess.argtypes = [W.HANDLE, W.UINT]
_k.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
_k.CloseHandle.argtypes = [W.HANDLE]
_k.OpenFileMappingW.argtypes = [W.DWORD, W.BOOL, W.LPCWSTR]
_k.OpenFileMappingW.restype = W.HANDLE
_k.GlobalMemoryStatusEx.argtypes = [ctypes.c_void_p]


def describe(result):
    code = result.get('code')
    stage, error = result.get('stage'), result.get('error', 0)
    return (f"exit={code}({LAUNCHER_EXIT.get(code, '未知')}) stage={stage}({STAGE.get(stage, '?')}) "
            f"error={error}({DLL_ERROR.get(error, '未知')}) pid={result.get('pid')} elapsed={result.get('elapsed_ms')}ms")


def launch(settings, account, result_path, log):
    """Start one client and log in up to the role-selection screen. Returns a Session."""
    result_path = Path(result_path)
    result_path.unlink(missing_ok=True)
    args = [str(LAUNCHER), '--stdin', '--selection-only', '--slot', '1',
            '--server-index', str(settings.server_index), '--game', str(settings.game_exe),
            '--inject-delay', str(settings.inject_delay_ms), '--result', str(result_path)]
    log.debug('launcher args: %s', ' '.join(args[1:]))
    started = time.monotonic()
    try:
        proc = subprocess.run(args, input=f'{account.name}\n{account.password}\n', capture_output=True,
                              text=True, encoding='utf-8', errors='replace', timeout=200)
    except subprocess.TimeoutExpired as e:
        raise LaunchError('launcher.exe 超时 200 秒无返回', {'code': None}, True) from e
    for line in proc.stdout.splitlines():
        log.debug('launcher> %s', line)
    for line in proc.stderr.splitlines():
        log.warning('launcher! %s', line)
    result = json.loads(result_path.read_text('utf-8')) if result_path.is_file() else {'code': proc.returncode}
    result['code'] = proc.returncode
    log.info('登录结果: %s, 用时 %.1fs', describe(result), time.monotonic() - started)
    if proc.returncode != 0 or result.get('stage') != SELECTION_STAGE:
        raise LaunchError(describe(result), result, proc.returncode not in NOT_RETRYABLE)
    session = Session(result['pid'], result['hwnd'], result['game_base'])
    _check_owner(session)
    return session


def _check_owner(session):
    pid = W.DWORD()
    _u.GetWindowThreadProcessId(session.hwnd, ctypes.byref(pid))
    if pid.value != session.pid:
        raise RuntimeError(f'窗口 {session.hwnd:#x} 不属于 pid {session.pid}（窗口已关闭？）')


def _command(session, kind, data=b''):
    _check_owner(session)
    buf = ctypes.create_string_buffer(data, len(data) or 1)
    cd = _CopyData(kind, len(data), ctypes.cast(buf, ctypes.c_void_p))
    out = ctypes.c_size_t()
    ok = _u.SendMessageTimeoutW(session.hwnd, 0x4A, 0, ctypes.addressof(cd), 2, 5000, ctypes.byref(out))
    if not ok:
        raise RuntimeError(f'DLL 命令 {kind} 超时（窗口无响应）, winerr={ctypes.get_last_error()}')
    return out.value


def arm(session):
    """Install the network tap (send/recv observation) inside the client."""
    if not _command(session, CMD_ARM):
        raise RuntimeError('DLL 拒绝 arm（不在选角界面，或 MinHook/tap 文件创建失败）')


def send_create(session, body):
    """Ask the client's own send function (window thread) to send one 0x0002 create request."""
    if len(body) != CREATE_BODY_SIZE:
        raise ValueError(f'建角请求体长度应为 {CREATE_BODY_SIZE}，实际 {len(body)}')
    if not _command(session, CMD_CREATE, struct.pack('<II', OP_CREATE, len(body)) + body):
        raise RuntimeError('DLL 拒绝建角命令（未 arm / 网络对象无效 / 本进程已发满 4 次 / 昵称为空）')


def send_delete(session, body):
    """Ask the client's own send function to send one 0x0003 delete-role request (DLL allows one per process)."""
    if len(body) != DELETE_BODY_SIZE:
        raise ValueError(f'删除请求体长度应为 {DELETE_BODY_SIZE}，实际 {len(body)}')
    if not _command(session, CMD_DELETE, struct.pack('<II', OP_DELETE, len(body)) + body):
        raise RuntimeError('DLL 拒绝删除命令（旧版 DLL / 未 arm / 不在选角界面 / 网络对象无效 / 本进程已删过一次）')


def enter_world(session, slot):
    """Ask the DLL to select `slot` (1..4) and press Enter until the world pointer appears.
    Returns at once; follow progress with read_status()."""
    if not _command(session, CMD_ENTER, struct.pack('<I', slot - 1)):
        raise RuntimeError('DLL 拒绝进入命令（不在选角界面 / 已经在进入中 / 选角对象无效）')


_STATUS_FIELDS = ('stage', 'error', 'hwnd', 'account_object', 'selector_object', 'role_index',
                  'enter_messages', 'game_base', 'started', 'finished', 'call_count', 'call_result')
_STATUS_FORMAT = '<i11I'
STATUS_SIZE = struct.calcsize(_STATUS_FORMAT)


def read_status(pid):
    """The DLL's diagnostic block (shared.h Status), shared memory Local\\MXBLLoginReplica_<pid>."""
    with mmap.mmap(-1, STATUS_SIZE, tagname=f'Local\\MXBLLoginReplica_{pid}', access=mmap.ACCESS_READ) as m:
        values = struct.unpack(_STATUS_FORMAT, m[:STATUS_SIZE])
    return dict(zip(_STATUS_FIELDS, values))


def has_dll(pid):
    """True when the process runs our provision DLL (its shared status block exists)."""
    name = f'Local\\MXBLLoginReplica_{pid}'
    h = _k.OpenFileMappingW(0x0004, False, name)  # FILE_MAP_READ
    if not h:
        return False
    _k.CloseHandle(h)
    return True


def call(session, rva, *args, eax=0, ecx=0, edx=0, ebx=0, esi=0, edi=0):
    """Call base+rva on the game's window thread (DLL command 106). Returns the function's EAX.
    Arguments are pushed right-to-left; ESP is restored afterwards, so any cleanup style works."""
    if len(args) > 8:
        raise ValueError('最多 8 个栈参数')
    words = [v & 0xFFFFFFFF for v in args] + [0] * (8 - len(args))
    req = struct.pack('<7I I 8I', rva, eax & 0xFFFFFFFF, ecx & 0xFFFFFFFF, edx & 0xFFFFFFFF,
                      ebx & 0xFFFFFFFF, esi & 0xFFFFFFFF, edi & 0xFFFFFFFF, len(args), *words)
    before = read_status(session.pid)['call_count']
    if not _command(session, CMD_CALL, req):
        raise RuntimeError(f'DLL 拒绝调用 RVA {rva:#x}（不在游戏世界中 / 参数非法 / 旧版 DLL）')
    st = read_status(session.pid)
    if st['call_count'] != before + 1:
        raise RuntimeError(f'调用计数异常 {before}->{st["call_count"]}（可能有并发调用）')
    return st['call_result']


def window_title(hwnd):
    buf = ctypes.create_unicode_buffer(512)
    _u.GetWindowTextW(hwnd, buf, 512)
    return buf.value


class _MemStatus(ctypes.Structure):
    _fields_ = [('dwLength', W.DWORD), ('dwMemoryLoad', W.DWORD), ('ullTotalPhys', ctypes.c_uint64),
                ('ullAvailPhys', ctypes.c_uint64), ('ullTotalPageFile', ctypes.c_uint64),
                ('ullAvailPageFile', ctypes.c_uint64), ('ullTotalVirtual', ctypes.c_uint64),
                ('ullAvailVirtual', ctypes.c_uint64), ('ullAvailExtendedVirtual', ctypes.c_uint64)]


def free_memory_mb():
    status = _MemStatus(dwLength=ctypes.sizeof(_MemStatus))
    _k.GlobalMemoryStatusEx(ctypes.byref(status))
    return status.ullAvailPhys // (1024 * 1024)


def alive(pid):
    h = _k.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if not h:
        return False
    try:
        return _k.WaitForSingleObject(h, 0) == 0x102  # WAIT_TIMEOUT
    finally:
        _k.CloseHandle(h)


def kill(pid):
    h = _k.OpenProcess(0x0001 | 0x00100000, False, pid)  # TERMINATE | SYNCHRONIZE
    if not h:
        return False
    try:
        _k.TerminateProcess(h, 1)
        return _k.WaitForSingleObject(h, 10000) == 0
    finally:
        _k.CloseHandle(h)


def close(session, timeout=15):
    """Normal exit via WM_CLOSE; terminate only if the game does not exit in time."""
    if _u.IsWindow(session.hwnd):
        _u.PostMessageW(session.hwnd, 0x0010, 0, 0)
    deadline = time.monotonic() + timeout
    while alive(session.pid) and time.monotonic() < deadline:
        time.sleep(0.2)
    if alive(session.pid):
        kill(session.pid)
        return 'terminated'
    return 'closed'
