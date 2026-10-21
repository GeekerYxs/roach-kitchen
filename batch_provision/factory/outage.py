"""Stage B3: many logins failing at once (unplanned maintenance, server down, this PC's network down) -> stop the
line instead of hammering the server, and come back once a canary login works.

Supervisor side (only when started by the guard): provisioner.login.RESULT_HOOK feeds every login's final result
into a LoginLog; verdict() over the last `window_minutes`:
  - any launcher exit 3 (game exe SHA256 changed = client updated) -> VERSION: retrying cannot help, the supervisor
    exits 5 and the guard stops with a loud message (a human rebuilds the addresses / DLL)
  - failures of >= `min_accounts` different accounts and no success at all -> OUTAGE: the supervisor exits 4
Guard side (factory/guard.py): close everything; this PC offline (no TCP connect to any of `net_hosts`) -> check
again every `net_check_minutes` and try a canary as soon as it is back; online -> the game servers are down: wait
`wait_minutes`, then a canary login every `canary_every_minutes`; success -> start the supervisor again.
Decisions are pure (tests/test_factory_outage.py).
"""
import socket
import threading
import time
from collections import deque
from dataclasses import dataclass

OUTAGE, VERSION = 'outage', 'version'
EXIT_OUTAGE, EXIT_VERSION = 4, 5        # supervisor exit codes the guard acts on
VERSION_EXIT = 3                        # launcher.exe: game exe SHA256 mismatch (provisioner/native.py LAUNCHER_EXIT)
GUARD_ENV = 'SMSM2_GUARD'               # set by the guard for its supervisor child


@dataclass(frozen=True)
class OutageSettings:
    window: float = 600.0
    min_accounts: int = 3
    wait: float = 3600.0
    canary_every: float = 1200.0
    net_check: float = 300.0
    net_hosts: tuple = (('www.baidu.com', 443), ('www.qq.com', 443))


def _host(text):
    host, _, port = str(text).rpartition(':')
    if not host or not port.isdigit():
        raise ValueError(f'[outage] net_hosts 要写成 "域名:端口"，不是 {text!r}')
    return host, int(port)


def load_outage(data):
    """[outage] of supervisor.toml -> OutageSettings, None when enabled = false. Missing section = defaults."""
    o = data.get('outage', {})
    if not bool(o.get('enabled', True)):
        return None
    s = OutageSettings(float(o.get('window_minutes', 10)) * 60, int(o.get('min_accounts', 3)),
                       float(o.get('wait_minutes', 60)) * 60, float(o.get('canary_every_minutes', 20)) * 60,
                       float(o.get('net_check_minutes', 5)) * 60,
                       tuple(_host(h) for h in o.get('net_hosts', ['www.baidu.com:443', 'www.qq.com:443'])))
    if s.min_accounts < 2:
        raise ValueError('[outage] min_accounts 至少 2（一个号登不上多半是那个号自己的问题）')
    if s.canary_every < 60 or s.net_check < 60:
        raise ValueError('[outage] canary_every_minutes / net_check_minutes 至少 1')
    if not s.net_hosts:
        raise ValueError('[outage] net_hosts 不能为空')
    return s


def verdict(results, now, s):
    """results: [(time, account, ok, launcher exit code)] -> None | OUTAGE | VERSION."""
    recent = [r for r in results if now - r[0] < s.window]
    if any(not ok and code == VERSION_EXIT for _, _, ok, code in recent):
        return VERSION
    if any(ok for _, _, ok, _ in recent):
        return None
    return OUTAGE if len({account for _, account, ok, _ in recent if not ok}) >= s.min_accounts else None


class LoginLog:
    """Thread-safe record of login results (all login threads write, the main thread judges)."""

    def __init__(self, keep=200):
        self._rows, self._lock = deque(maxlen=keep), threading.Lock()

    def add(self, account, ok, code, now=None):
        with self._lock:
            self._rows.append((time.time() if now is None else now, account, ok, code))

    def rows(self):
        with self._lock:
            return list(self._rows)


def internet_ok(hosts, timeout=5.0, connect=socket.create_connection):
    """True when a TCP connection to any of hosts works (DNS included)."""
    for host, port in hosts:
        try:
            connect((host, port), timeout=timeout).close()
            return True
        except OSError:
            continue
    return False
