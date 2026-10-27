"""Delete the 师徒 apprentice roles (user's order 2026-10-27, after their gold went to 伏地魔1).

    python -X utf8 research/shitu/delete_apprentices.py mvp01:222150:十万1 mvp02:222151:十万2 mvp03:222152:十万3

Per role (the core of factory/delete.py without its factory.db gate; deleting cannot be undone):
  1. its in-world window (title '-<name>') is closed (the client ignores WM_CLOSE in the world -> terminated)
  2. fresh login to the selection screen, arm the tap
  3. the roster entry is found BY ID and its name must match; +0x60 (protect) must be 0, the client's own delete
     flag (context +0x148) clear, and the session connection == the DLL's send connection
  4. 0x0003 built from this session (protocol.build_delete), DLL command 107 sends it, wait for 0x4004;
     no reply = result unknown: NOT sent again, check the selection screen by hand
  5. close the window
Only the given char ids are touched (slot 1 of mvp01..03 = mm01..mm03 stays).
"""
import dataclasses
import struct
import sys
import time

from common import ROOT, find_roles
from factory.delete import BUSY, CONNECTION, MANAGER, find_entry
from provisioner import config, log, native
from provisioner.login import LaunchThrottle, login, read_session
from provisioner.memory import ProcessMemory
from provisioner.protocol import (OP_DELETE_REPLY, ROSTER_PROTECT, TapReader, build_delete, parse_delete_reply,
                                  read_roster_raw)

REPLY_TIMEOUT = 15


def close_world_window(name, lg):
    found = find_roles((name,))
    if name not in found:
        return
    pid = found[name][0]
    st = native.read_status(pid) if native.has_dll(pid) else None
    if st:
        how = native.close(native.Session(pid, st['hwnd'], st['game_base']), timeout=3)
    else:
        native.kill(pid)
        how = 'killed'
    lg.info('关闭 %s 的游戏窗口 pid=%d (%s)，3 秒后重新登录', name, pid, how)
    time.sleep(3)


def delete_one(settings, throttle, account, cid, name):
    lg = log.for_account(account.name)
    close_world_window(name, lg)
    session = login(settings, account, ROOT / 'runtime', throttle, lg)
    try:
        native.arm(session)
        reader = TapReader(ROOT / 'runtime', session.pid)
        reader.poll()
        context, roster = read_session(session, account.name, lg)
        index, problem = find_entry(roster, cid, name)
        if problem:
            raise RuntimeError(problem)
        if index is None:
            lg.warning('%s (ID %d) 已不在选角列表里', name, cid)
            return 'gone'
        with ProcessMemory(session.pid, session.base) as mem:
            entry = read_roster_raw(mem, context)[index]
            if struct.unpack_from('<I', entry, ROSTER_PROTECT)[0]:
                raise RuntimeError('列表项 +0x60 非 0（客户端会要求额外输入），不删')
            if mem.u32(context + BUSY):
                raise RuntimeError('客户端自己的删除标志已置位，不删')
            if mem.u32(context + CONNECTION) != mem.u32(session.base + MANAGER):
                raise RuntimeError('会话连接和 DLL 发送用的连接不一致，不删')
            body = build_delete(mem, context, account.name, cid)
        lg.info('删除 槽%d %s ID=%d：发送 0x0003 (%d 字节)', index + 1, name, cid, len(body))
        native.send_delete(session, body)
        sent = time.monotonic()
        while time.monotonic() - sent < REPLY_TIMEOUT:
            for op, payload in reader.poll():
                if op == OP_DELETE_REPLY:
                    code, release_ms = parse_delete_reply(payload)
                    if code != 0:
                        raise RuntimeError(f'服务器拒绝删除 result={code}')
                    lg.info('服务器接受删除 %s，%.1f 小时后释放槽位', name, release_ms / 3.6e6)
                    return 'deleted'
            time.sleep(0.15)
        raise RuntimeError(f'{REPLY_TIMEOUT}s 内没收到 0x4004：结果不明，不重发，请人工看选角界面')
    finally:
        lg.info('关闭选角窗口 (%s)', native.close(session))


def main(specs):
    log.setup(ROOT / 'logs', prefix='delete_apprentices')
    lg = log.for_account('main')
    base = config.load_enter(ROOT / 'enter.toml')
    pw = base.accounts[0].password
    jobs = [(config.Account(a, pw), int(cid), name) for a, cid, name in (s.split(':') for s in specs)]
    settings = dataclasses.replace(base, accounts=tuple(a for a, _, _ in jobs))
    throttle = LaunchThrottle.of(settings)
    ok = True
    for account, cid, name in jobs:
        try:
            lg.info('%s: %s', name, delete_one(settings, throttle, account, cid, name))
        except Exception as e:
            ok = False
            lg.error('%s 没删: %s', name, e)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
