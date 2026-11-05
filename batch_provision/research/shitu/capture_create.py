"""Log one account into the role-selection screen (capture armed) and record a role the USER creates by hand.

    python -X utf8 research/shitu/capture_create.py ACCOUNT [WAIT_S]

2026-11-05: the 0x0002 create body (provisioner/protocol.py build_create) holds four appearance fields copied from
the client's create screen: body[265] u32 (ctx+0xE0, sample 3), body[269] u32 (ctx+0xD4, 0), body[273] u8 (ctx+0xAC,
1), body[274] u8 (ctx+0xB0, 0) = the male / blue-hair sample. Which one is the sex is unknown, so the user creates a
女 role in the UI once and this prints those fields of the real request plus the 0x4003 reply; nothing is sent here.
The window is left open (the role then enters the world through make_apprentices as usual).
"""
import struct
import sys
import time

from common import ROOT
from monitor import Tap
from provisioner import config, log
from provisioner.login import LaunchThrottle, login, read_session

FIELDS = (('265 u32 (ctx+0xE0)', 265, '<I'), ('269 u32 (ctx+0xD4)', 269, '<I'),
          ('273 u8 (ctx+0xAC)', 273, '<B'), ('274 u8 (ctx+0xB0)', 274, '<B'))


def main(account, wait=900):
    import dataclasses
    log.setup(ROOT / 'logs', prefix='capture_create')
    lg = log.for_account(account)
    base = config.load_enter(ROOT / 'enter.toml')
    acc = config.Account(account, base.accounts[0].password)
    settings = dataclasses.replace(base, accounts=(acc,))
    session = login(settings, acc, ROOT / 'runtime', LaunchThrottle.of(settings), lg)
    _, roster = read_session(session, account, lg)
    print(f'{account} 在选角界面 pid={session.pid}，现有角色 {[n for _, _, n in roster]}；请在游戏里手动建角', flush=True)
    tap = Tap(session.pid, from_end=True)
    tap.ready()
    tap.poll()
    end = time.time() + wait
    while time.time() < end:
        for _, d, op, body, _ in tap.poll():
            if d == 'C->S' and op == 0x0002:
                print('建角请求 0x0002，长度', len(body), flush=True)
                for label, off, fmt in FIELDS:
                    print(f'  {label} = {struct.unpack_from(fmt, body, off)[0]}', flush=True)
                name = body[275:291].split(b'\0', 1)[0].decode('gbk', 'replace')
                print(f'  名字 = {name}；264..291 = {body[264:292].hex(" ")}', flush=True)
            elif d == 'S->C' and op == 0x4003:
                cid, result = struct.unpack('<IH', body[:6])
                print(f'回包 0x4003 角色 ID {cid} 结果 {result}', flush=True)
                return 0
        time.sleep(0.5)
    print('等待超时，没看到建角请求', flush=True)
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 900))
