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
import os
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


class Refused(Stop):
    def __init__(self, result, msg):
        super().__init__(msg)
        self.result = result


REFUSED_NAME = 3        # 0x4003 result 3: the name is not allowed (亿万J8, 2026-11-01: a 谐音 敏感词; user: just rename)
ALT_MARKS = 'XYZ'


def alt_names(name):
    """Names to try instead of a refused one: a letter before the trailing number (亿万J8 -> 亿万JX8, 亿万JY8 ...)."""
    import re
    m = re.fullmatch(r'(.*?)(\d+)', name)
    head, num = (m.group(1), m.group(2)) if m else (name, '')
    return [f'{head}{c}{num}' for c in ALT_MARKS if len(f'{head}{c}{num}'.encode('gbk')) <= 15]


def save_alias(name, alt):
    import json
    from line.plan import ALIAS_FILE, aliases
    al = aliases()
    al[name] = alt
    ALIAS_FILE.write_text(json.dumps(al, ensure_ascii=False, indent=1), encoding='utf-8')


def create_named(session, account, name, lg):
    """create(), and when the server refuses the name itself, the first alt_names one it takes (saved as an alias,
    so the rest of the batch uses it). -> the name created."""
    try:
        create(session, account, name, lg)
        return name
    except Refused as e:
        if e.result != REFUSED_NAME:
            raise
        lg.info('%s 被服务器拒绝（result=3，多半敏感词），换名字', name)
    for alt in alt_names(name):
        try:
            create(session, account, alt, lg)
        except Refused as e:
            if e.result != REFUSED_NAME:
                raise
            lg.info('%s 也被拒绝', alt)
            continue
        save_alias(name, alt)
        lg.info('改名 %s -> %s（logs/name_alias.json）', name, alt)
        return alt
    raise Stop(f'{name} 和替换名 {alt_names(name)} 都被服务器拒绝')


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
                raise Refused(result, f'服务器拒绝建角 result={result} raw={payload.hex()}')
        time.sleep(0.15)
    raise Stop('15s 内没收到建角回包 0x4003（结果不确定，重跑会先看选角列表）')


def one(settings, throttle, account, name, anywhere=False):
    lg = log.for_account(account.name)
    out = {'account': account.name, 'name': name, 'ok': False}
    target_slot = int(os.environ.get('BATCH', '0') or 0)
    session = None
    try:
        session = login(settings, account, ROOT / 'runtime', throttle, lg)
        _, roster = read_session(session, account.name, lg)
        names = [n for _, _, n in roster]
        if name in names and target_slot and names.index(name) + 1 != target_slot:
            raise Stop(f'{name} 已在第 {names.index(name) + 1} 槽，不是本批指定的第 {target_slot} 槽')
        if name not in names:
            if target_slot and len(roster) != target_slot - 1:
                raise Stop(f'本批要求第 {target_slot} 槽，但账号当前有 {len(roster)} 个角色 {names}；不建角')
            if len(roster) >= MAX_SLOTS:
                raise Stop(f'账号里已有 {len(roster)} 个角色 {names}，没有空槽，不建')
            name = out['name'] = create_named(session, account, name, lg)
            lg.info('关窗重登，刷新选角列表 (%s)', native.close(session))
            session = login(settings, account, ROOT / 'runtime', throttle, lg)
            _, roster = read_session(session, account.name, lg)
            names = [n for _, _, n in roster]
        if names.count(name) != 1:
            raise Stop(f'{name} 不在选角列表里（或重名）: {names}')
        slot = names.index(name) + 1                   # the list as read decides the slot (2026-10-27 03:2x round)
        if target_slot and slot != target_slot:
            raise Stop(f'{name} 在第 {slot} 槽，不是本批指定的第 {target_slot} 槽')
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
