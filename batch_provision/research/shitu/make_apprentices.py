"""Create the 师徒 apprentices: account mvpNN, role slot 2, name 十万N -> enter the world -> 菜鸟训练营 -> 逍遥村西区.

    python -X utf8 research/shitu/make_apprentices.py                 (default: mvp01:十万1 mvp02:十万2 mvp03:十万3)
    python -X utf8 research/shitu/make_apprentices.py mvp01:十万1 ...
    python -X utf8 research/shitu/make_apprentices.py --anywhere capNN:亿万M ...   relog: in the world anywhere = ok

Restartable per account, every step decided from what the selection screen shows:
  - the role already exists -> no create
  - it does not exist and the account has a free slot (< 4 roles) -> 0x0002 create, relogin
  - the slot is whatever the fresh roster shows for the name (deleted roles leave no row; 03:2x round)
Then enter that slot (the verify step checks the char id) and, if the role is on 菜鸟训练营 (map 271), run the novice stage (provisioner.novice NoviceJob).
Password = the [accounts] password of batch_provision/local.toml (mvp uses the same one, checked 2026-10-27).
Reuses provisioner.login / worker / enter / novice; windows stay open in the world.
"""
import dataclasses
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from common import ROOT
from provisioner import config, log, native
from provisioner.enter import enter_role, verify_in_world
from provisioner.login import LaunchThrottle, login, read_session
from provisioner.memory import ProcessMemory
from provisioner.novice import NOVICE_MAP, NoviceJob, load_settings
from provisioner.protocol import MAX_SLOTS, OP_CREATE_REPLY, TapReader, build_create, parse_create_reply
from provisioner.world import read_world

DEFAULT = ('mvp01:十万1', 'mvp02:十万2', 'mvp03:十万3')


class Stop(Exception):
    pass


def create(session, account, name, lg):
    native.arm(session)
    reader = TapReader(ROOT / 'runtime', session.pid)
    reader.poll()
    with ProcessMemory(session.pid, session.base) as mem:
        context, _ = mem.locate_context()
        body = build_create(mem, context, account.name, name)
    lg.info('发送建角请求 %s (0x0002, %d 字节)', name, len(body))
    native.send_create(session, body)
    end = time.monotonic() + 15
    while time.monotonic() < end:
        for op, payload in reader.poll():
            if op == OP_CREATE_REPLY:
                char_id, result = parse_create_reply(payload)
                if result == 0 and char_id:
                    lg.info('%s 创建成功 角色ID=%d', name, char_id)
                    return char_id
                raise Stop(f'服务器拒绝建角 result={result} raw={payload.hex()}')
        time.sleep(0.15)
    raise Stop('15s 内没收到建角回包 0x4003（结果不确定，重跑会先看选角列表）')


def one(settings, throttle, account, name, anywhere=False):
    lg = log.for_account(account.name)
    out = {'account': account.name, 'name': name, 'ok': False}
    session = None
    try:
        session = login(settings, account, ROOT / 'runtime', throttle, lg)
        _, roster = read_session(session, account.name, lg)
        names = [n for _, _, n in roster]
        if name not in names:
            if len(roster) >= MAX_SLOTS:
                raise Stop(f'账号里已有 {len(roster)} 个角色 {names}，没有空槽，不建')
            create(session, account, name, lg)
            lg.info('关窗重登，刷新选角列表 (%s)', native.close(session))
            session = login(settings, account, ROOT / 'runtime', throttle, lg)
            _, roster = read_session(session, account.name, lg)
            names = [n for _, _, n in roster]
        if names.count(name) != 1:
            raise Stop(f'{name} 不在选角列表里（或重名）: {names}')
        slot = names.index(name) + 1                   # the list as read decides the slot (2026-10-27 03:2x round)
        char_id, level, _ = roster[slot - 1]
        lg.info('进入第 %d 槽 %s (ID=%d, %d级)', slot, name, char_id, level)
        enter_role(session, slot, settings.enter_timeout, lg, account.name)
        world = verify_in_world(session, char_id, name, lg)
        out.update(char_id=char_id, pid=session.pid)
        if world.map_id == NOVICE_MAP:
            client = SimpleNamespace(name=name, session=session, char_id=char_id)
            r = NoviceJob(client, load_settings(ROOT / 'novice.toml'), lg).run()
            if not r['ok']:
                raise Stop(f'新手出村失败: {r.get("error")}')
        with ProcessMemory(session.pid, session.base) as mem:
            st = read_world(mem)
        # --anywhere (a relog of an existing apprentice): back in the world where it logged out is success
        # (2026-10-29 亿万60 relogged in map 1000 was reported as a failure)
        out.update(ok=anywhere or st.map_id == 1, map_id=st.map_id, x=round(st.x), y=round(st.y))
        if not out['ok']:
            out['error'] = f'不在逍遥村西区 (map {st.map_id})，没动它'
    except Exception as e:
        out['error'] = f'{type(e).__name__}: {e}'
        lg.error('%s 停止: %s', account.name, e)
        if session:
            lg.warning('保留窗口 pid=%d 供排查', session.pid)
    return out


def main(pairs, anywhere=False):
    log.setup(ROOT / 'logs', prefix='apprentices')
    lg = log.for_account('main')
    base = config.load_enter(ROOT / 'enter.toml')
    pw = base.accounts[0].password                     # local.toml [accounts] password (mvp shares it)
    jobs = [(config.Account(a, pw), n) for a, n in (p.split(':', 1) for p in pairs)]
    settings = dataclasses.replace(base, accounts=tuple(a for a, _ in jobs))
    throttle = LaunchThrottle.of(settings)
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        results = list(pool.map(lambda j: one(settings, throttle, *j, anywhere=anywhere), jobs))
    for r in results:
        lg.info('%s', r)
    return 0 if all(r['ok'] for r in results) else 1


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if a != '--anywhere']
    sys.exit(main(args or DEFAULT, anywhere='--anywhere' in sys.argv[1:]))
