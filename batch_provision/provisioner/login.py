"""Shared by every tool: launch gating (interval + free memory), login with retries,
and reading the role-selection screen (session context + roster)."""
import contextlib
import threading
import time

from . import native, procs
from .memory import ProcessMemory
from .protocol import MAX_SLOTS, SessionMismatch, read_roster, session_account


class LaunchThrottle:
    """Gate for every game launch across all workers: at least `interval` seconds apart, only while free physical
    memory is above `min_free_mb`, and (max_clients > 0) only while this machine has fewer than max_clients - 1
    game processes, launches on their way included: the server takes at most max_clients windows per IP and
    leaves "enter world" hanging beyond that (error=110). Station logins pass the window gate (uncapped()):
    the supervisor keeps their windows free in its alt budget, and a station must never wait for an alt."""

    def __init__(self, interval, min_free_mb=0, max_clients=0, count=None):
        self.interval, self.min_free_mb, self.max_clients = interval, min_free_mb, max_clients
        self._count = count or (lambda: len(procs.game_pids()))
        self._next, self._lock = 0.0, threading.Lock()
        self._launching, self._n_lock = 0, threading.Lock()   # launches past the gate whose process may not show yet

    @classmethod
    def of(cls, s):
        return cls(s.launch_interval, s.min_free_memory_mb, getattr(s, 'max_clients', 0))

    def uncapped(self):
        """The same gate (interval, memory) without the window limit, for station logins."""
        return _Uncapped(self)

    @contextlib.contextmanager
    def launch(self, log, capped=True):
        """with throttle.launch(log): start one game process."""
        self._reserve(log, capped)
        try:
            self.wait(log)
            yield
        finally:
            with self._n_lock:
                self._launching -= 1

    def _reserve(self, log, capped):
        warned = False
        while True:
            with self._n_lock:
                total = self._count() + self._launching
                if not capped or not self.max_clients or total < self.max_clients - 1:
                    self._launching += 1
                    break
            if not warned:
                log.warning('本机游戏窗口 %d 个（含正在启动的），单 IP 上限 %d：暂停开新窗口，等旧窗口关掉…',
                            total, self.max_clients)
                warned = True
            time.sleep(3)
        if warned:
            log.info('游戏窗口降到 %d 个，继续', total)

    def wait(self, log):
        with self._lock:  # one launcher at a time passes the gate
            warned = False
            while (free := native.free_memory_mb()) < self.min_free_mb:
                if not warned:
                    log.warning('空闲内存 %dMB < %dMB，暂停开新窗口，等待内存释放…', free, self.min_free_mb)
                    warned = True
                time.sleep(3)
            if warned:
                log.info('空闲内存恢复到 %dMB，继续', free)
            delay = self._next - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self._next = time.monotonic() + self.interval


class _Uncapped:
    def __init__(self, throttle):
        self._t = throttle

    def launch(self, log):
        return self._t.launch(log, capped=False)


class LoginFailed(RuntimeError):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code        # launcher.exe exit code of the last attempt (3 = game version changed)


# Called with (account name, ok, launcher exit code) once per login() call, after its retries. The supervisor sets it
# to spot many accounts failing at once (factory/outage.py); a hook error never breaks a login.
RESULT_HOOK = None


def _report(account, ok, code):
    if RESULT_HOOK is not None:
        try:
            RESULT_HOOK(account.name, ok, code)
        except Exception:       # noqa: BLE001
            pass


def login(settings, account, runtime, throttle, log, kill_on_failure=False):
    """Start a client and stop on the role-selection screen; retry failures (no role is touched yet)."""
    attempts = settings.login_retries + 1
    for attempt in range(1, attempts + 1):
        result_file = runtime / f'launch_{account.name}_{attempt}.json'
        try:
            with throttle.launch(log):
                log.info('启动游戏并登录 (第 %d/%d 次)', attempt, attempts)
                session = native.launch(settings, account, result_file, log)
            log.info('已到选角界面 pid=%d hwnd=%#x base=%#x', session.pid, session.hwnd, session.base)
            _report(account, True, 0)
            return session
        except native.LaunchError as e:
            pid = e.result.get('pid')
            log.error('登录失败: %s', e)
            if not e.retryable or attempt == attempts:
                if pid and kill_on_failure:
                    native.kill(pid)
                _report(account, False, e.result.get('code'))
                raise LoginFailed(f'登录失败: {e}', e.result.get('code')) from e
            if pid and native.alive(pid):
                log.warning('关闭失败的进程 pid=%d 后重试', pid)
                native.kill(pid)
            time.sleep(2)


# The selection checkpoint (DLL stage 9) can come before the server's role list. Seen 2026-10-12
# with 16 windows: mw146/mw147 read 0 roles, and mw141 read 0, sent a create at once and got
# result=1 while the late 0x4002 login packet arrived in the same instant.
ROSTER_EMPTY_WAIT = 8.0    # an empty list must stay empty this long before it is believed
ROSTER_STABLE_GAP = 0.5    # a non-empty list must read the same twice, this far apart


def settle_roster(read, log, sleep=time.sleep, clock=time.monotonic,
                  empty_wait=ROSTER_EMPTY_WAIT, gap=ROSTER_STABLE_GAP):
    """Re-read the role list until it is believable. read() -> list."""
    started = clock()
    previous = read()
    waited_note = False
    while True:
        sleep(gap)
        current = read()
        if current and current == previous:
            return current
        if not current and clock() - started >= empty_wait:
            return current
        if not current and not waited_note:
            log.info('选角列表暂时为空，等待服务器数据（最多 %.0fs）', empty_wait)
            waited_note = True
        previous = current


def read_session(session, account_name, log, attempts=5, own_names=()):
    """Locate the session context, make sure it holds THIS account (under memory pressure it once
    read back as b'6'), and read the server's role list once it has settled. -> (context, roster)"""
    for attempt in range(1, attempts + 1):
        t0 = time.monotonic()
        with ProcessMemory(session.pid, session.base) as mem:
            context, _ = mem.locate_context()
            raw, debug = session_account(mem, context)
            if raw.split(b'\0', 1)[0] == account_name.encode('ascii'):
                roster = settle_roster(lambda: read_roster(mem, context), log)
                break
        log.warning('会话账号不匹配 (第 %d/%d 次): %s；1 秒后重新定位', attempt, attempts, debug)
        if attempt == attempts:
            raise SessionMismatch(f'重试 {attempts} 次会话账号仍不匹配: {debug}')
        time.sleep(1)
    log.info('会话上下文=%#x (定位+读列表 %.1fs)', context, time.monotonic() - t0)
    if not roster:
        log.info('选角列表: 空 (0/%d)', MAX_SLOTS)
    for slot, (char_id, level, name) in enumerate(roster, 1):
        mark = '  ← 非本工具命名的角色' if own_names and name not in own_names else ''
        log.info('选角列表 槽%d: %s  ID=%d  %d级%s', slot, name, char_id, level, mark)
    return context, roster
