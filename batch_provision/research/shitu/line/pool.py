"""Accounts for a team that takes its apprentices from an account range (line.toml [team.x] pool = "mw01-mw100").

User 2026-11-05: "I give an account range; use whatever role slots are free, skip a full account, one role per account
at a time" -> before each batch, pick 4 accounts in range order that have a free slot (< 4 roles) and are not in any
team's latest batch (their roles may still be online: logging the account in would kick them). The 4 picked are read
fresh at the selection screen (check_rosters.one) before they are kept; the others come from the cache.
Files: logs/pool_alloc.json {"team/batch": [accounts]} (a restart keeps the same accounts), logs/pool_rosters.json
{account: [role names]} (read once, then counted on: each allocation adds its planned name).
"""
import json
import re
import threading
from pathlib import Path

LOGS = Path(__file__).resolve().parent.parent / 'logs'
ALLOC_FILE, ROSTER_FILE = LOGS / 'pool_alloc.json', LOGS / 'pool_rosters.json'
MAX_ROLES = 4                    # provisioner.protocol.MAX_SLOTS
WANT = 4                         # plan.MASTER_SLOTS
LOCK = threading.Lock()          # two team threads allocate one at a time


def expand(spec):
    """'mw01-mw100' -> ['mw01', ..., 'mw100'] (the first one's digits = the width)."""
    m = re.fullmatch(r'([A-Za-z]+)(\d+)-(?:[A-Za-z]+)?(\d+)', spec.replace(' ', ''))
    if not m:
        raise ValueError(f'pool = {spec!r}：写成 mw01-mw100')
    prefix, a, b = m.group(1), m.group(2), int(m.group(3))
    return [f'{prefix}{i:0{len(a)}d}' for i in range(int(a), b + 1)]


def _load(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _save(path, data):
    path.parent.mkdir(exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    tmp.replace(path)


def latest(alloc):
    """{team: accounts of its highest allocated batch}."""
    best = {}
    for key, accs in alloc.items():
        team, batch = key.rsplit('/', 1)
        if team not in best or int(batch) > best[team][0]:
            best[team] = (int(batch), accs)
    return {t: a for t, (_, a) in best.items()}


def busy(alloc):
    return {a for accs in latest(alloc).values() for a in accs}


def candidates(order, rosters, taken, names=()):
    """Accounts in range order with a free slot by the cache (unknown = maybe), not taken, not holding these names."""
    out = []
    for a in order:
        roles = rosters.get(a)
        if a in taken or (roles is not None and (len(roles) >= MAX_ROLES or set(roles) & set(names))):
            continue
        out.append(a)
    return out


def allocate(team, batch, spec, names, scan, alloc_file=ALLOC_FILE, roster_file=ROSTER_FILE, say=print):
    """The batch's WANT accounts (stored once picked). scan(accounts) -> {account: [role names] or error text}."""
    with LOCK:
        alloc, rosters = _load(alloc_file), _load(roster_file)
        key = f'{team}/{batch}'
        if key in alloc:
            return alloc[key]
        order, taken, picked = expand(spec), busy(alloc), []
        while len(picked) < WANT:
            todo = candidates(order, rosters, taken | set(picked), names)[:WANT - len(picked)]
            if not todo:
                raise RuntimeError(f'账号范围 {spec} 里只找到 {len(picked)} 个有空槽的账号 {picked}，不够 {WANT} 个')
            for acc, roles in scan(todo).items():
                if isinstance(roles, str):                       # login failed: leave it, try the next ones
                    say(f'[{team}] {acc} 读角色失败，跳过: {roles}')
                    taken.add(acc)
                    continue
                rosters[acc] = list(roles)
                if len(roles) < MAX_ROLES and not set(roles) & set(names):
                    picked.append(acc)
                else:
                    say(f'[{team}] {acc} 已有 {len(roles)} 个角色 {roles}，跳过')
        picked = picked[:WANT]
        for acc, name in zip(picked, names):
            rosters[acc] = rosters.get(acc, []) + [name]           # the role make_apprentices is about to create
        alloc[key] = picked
        _save(roster_file, rosters)
        _save(alloc_file, alloc)
        say(f'[{team}] 第 {batch} 批账号: ' + ', '.join(f'{a}（已有 {len(rosters[a]) - 1} 个角色）' for a in picked))
        return picked


def accounts(team, batch, alloc_file=ALLOC_FILE):
    """The stored allocation, or None."""
    return _load(alloc_file).get(f'{team}/{batch}')


def scan_rosters(names):
    """{account: [role names]} or an error text per account; logs in at the selection screen only (check_rosters)."""
    import dataclasses
    from concurrent.futures import ThreadPoolExecutor

    import check_rosters
    from common import ROOT
    from provisioner import config
    from provisioner.login import LaunchThrottle
    base = config.load_enter(ROOT / 'enter.toml')
    pw = base.accounts[0].password
    accs = tuple(config.Account(a, pw) for a in names)
    settings = dataclasses.replace(base, accounts=accs)
    throttle = LaunchThrottle.of(settings)
    with ThreadPoolExecutor(max_workers=len(accs)) as pool:
        out = dict(pool.map(lambda a: check_rosters.one(settings, throttle, a), accs))
    return {a: r if isinstance(r, str) else [n for _, _, _, n in r] for a, r in out.items()}
