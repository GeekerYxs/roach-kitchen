"""Log a master (伏地魔1 ...) into the world by itself: the line no longer parks when a master drops (round 5, 16:16).

    python -X utf8 research/shitu/master_login.py 伏地魔1 [伏地魔2 ...]

Accounts: the file named by line/line.toml `master_accounts` (the user's own file, outside the repo; one account per
line written `<account>密码<password>`). The passwords are only read here, never written anywhere or logged.
Which account holds which master is not in the file: accounts are tried one by one (login -> role list -> the master's
row? enter it : close the window); the answer is cached in logs/master_accounts.json (names only) so the next
relog goes straight to the right one.

A master whose window is up but offline (r4_util.offline) is closed first. Exit 0 = every named master is in the
world, 1 = some could not be logged in (the reason is printed), 2 = no accounts file.
"""
import dataclasses
import json
import re
import sys
import time
import tomllib
from pathlib import Path

from common import ROOT, find_roles

HERE = Path(__file__).resolve().parent
CACHE = HERE / 'logs' / 'master_accounts.json'
CONFIG = HERE / 'line' / 'line.toml'
LINE = re.compile(r'^\s*(\S+?)\s*密码\s*(\S+)\s*$')


def parse_accounts(text):
    """'<account>密码<password>' lines -> [(account, password)] (other lines ignored)."""
    out = []
    for line in text.splitlines():
        m = LINE.match(line.lstrip('﻿'))
        if m:
            out.append((m.group(1), m.group(2)))
    return out


def accounts_file(config=CONFIG):
    try:
        p = tomllib.loads(config.read_text(encoding='utf-8')).get('master_accounts', '')
    except OSError:
        return None
    return Path(p) if p and Path(p).exists() else None


def load_cache(path=CACHE):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def save_cache(cache, path=CACHE):
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding='utf-8')


def order(accounts, master, cache):
    """Accounts to try for master: the cached one first, then those not known to hold other roles only."""
    known = cache.get(master)
    first = [a for a in accounts if a[0] == known]
    rest = [a for a in accounts if a[0] != known]
    return first + rest


def close_offline(master):
    import r4_util
    import trial_run as t
    from provisioner import native
    found = find_roles((master,))
    if master in found and r4_util.offline(master):
        pid = found[master][0]
        st = native.read_status(pid)
        t.say(f'[{master}] 掉线的窗口先关掉: {native.close(native.Session(pid, st["hwnd"], st["game_base"]))}')
        time.sleep(3)


def login_one(master, accounts, cache, lg):
    from provisioner import config, native
    from provisioner.enter import enter_role, verify_in_world
    from provisioner.login import LaunchThrottle, login, read_session
    base = config.load_enter(ROOT / 'enter.toml')
    for name, pw in order(accounts, master, cache):
        acc = config.Account(name, pw)
        settings = dataclasses.replace(base, accounts=(acc,))
        session = login(settings, acc, ROOT / 'runtime', LaunchThrottle.of(settings), lg)
        _, roster = read_session(session, name, lg)
        names = [n for _, _, n in roster]
        cache.setdefault('_roles', {})[name] = names
        for n in names:
            cache[n] = name
        save_cache(cache)
        if master not in names:
            lg.info('%s 里没有 %s（%s），关窗换下一个账号', name, master, names)
            native.close(session)
            continue
        slot = names.index(master) + 1
        char_id = roster[slot - 1][0]
        enter_role(session, slot, settings.enter_timeout, lg, name)
        world = verify_in_world(session, char_id, master, lg)
        lg.info('%s 进入游戏: 地图 %s (%.0f,%.0f)', master, world.map_id, world.x, world.y)
        return True
    return False


def main(masters):
    from provisioner import log
    path = accounts_file()
    if not path:
        print('line.toml 的 master_accounts 没设或文件不在，不能自动登录师傅')
        return 2
    accounts = parse_accounts(path.read_text(encoding='utf-8-sig', errors='replace'))
    log.setup(ROOT / 'logs', prefix='master_login')
    lg = log.for_account('master')
    cache = load_cache()
    bad = []
    for m in masters:
        close_offline(m)
        if m in find_roles((m,)):
            lg.info('%s 已经在游戏里', m)
            continue
        try:
            ok = login_one(m, accounts, cache, lg)
        except Exception as e:                      # one master failing must not stop the others
            lg.error('%s 登录出错: %s: %s', m, type(e).__name__, e)
            ok = False
        if not ok:
            bad.append(m)
    if bad:
        print(f'没能登录: {bad}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
