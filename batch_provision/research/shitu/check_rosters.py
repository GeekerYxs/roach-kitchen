"""Read-only: log in each account, print its role list (slot, char id, level, name), close the window.

    python -X utf8 research/shitu/check_rosters.py mvp01 mvp02 ...

Password = the [accounts] password of batch_provision/local.toml (as make_apprentices.py). Nothing is created or
deleted; the windows are closed at the selection screen.
"""
import dataclasses
import sys
from concurrent.futures import ThreadPoolExecutor

from common import ROOT
from provisioner import config, log, native
from provisioner.login import LaunchThrottle, login, read_session


def one(settings, throttle, account):
    lg = log.for_account(account.name)
    session = None
    try:
        session = login(settings, account, ROOT / 'runtime', throttle, lg)
        _, roster = read_session(session, account.name, lg)
        return account.name, [(i + 1, cid, lv, n) for i, (cid, lv, n) in enumerate(roster)]
    except Exception as e:
        return account.name, f'{type(e).__name__}: {e}'
    finally:
        if session:
            native.close(session)


def main(names):
    log.setup(ROOT / 'logs', prefix='rosters')
    base = config.load_enter(ROOT / 'enter.toml')
    pw = base.accounts[0].password
    accounts = tuple(config.Account(a, pw) for a in names)
    settings = dataclasses.replace(base, accounts=accounts)
    throttle = LaunchThrottle.of(settings)
    with ThreadPoolExecutor(max_workers=len(accounts)) as pool:
        for name, roster in pool.map(lambda a: one(settings, throttle, a), accounts):
            print(name, roster)


if __name__ == '__main__':
    main(sys.argv[1:])
