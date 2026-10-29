"""Entry: python -m provisioner.doctor — checks this machine before the first run (no game window is touched).

Python version, local.toml, game exe, bin files, every tool config, station passwords, memory, which accounts
of this machine's range still need 一键建角.cmd, and whether state/factory.db holds alts of another range."""
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

from . import config, native

ROOT = Path(__file__).resolve().parent.parent
OK, WARN, BAD = 'OK  ', '提示', '错误'


class Report:
    def __init__(self):
        self.bad = 0

    def line(self, level, text):
        self.bad += level == BAD
        print(f'[{level}] {text}')


def role_status(state_dir, accounts, per_account=4, suffix='r'):
    """-> (ready, todo, foreign): accounts whose roles 1..N all exist; accounts still needing 一键建角;
    {account: [names]} roles in the roster that are not ours (left by other tools; they keep a slot)."""
    ready, todo, foreign = [], [], {}
    for name in accounts:
        p = Path(state_dir) / f'{name}.json'
        data = json.loads(p.read_text('utf-8')) if p.is_file() else {}
        roles = data.get('roles', {})
        want = [f'{name}{suffix}{i}' for i in range(1, per_account + 1)]
        if all(roles.get(r, {}).get('status') in ('created', 'exists') for r in want):
            ready.append(name)
        else:
            todo.append(name)
        others = [x.get('name', '') for x in data.get('roster', [])
                  if not str(x.get('name', '')).startswith(f'{name}{suffix}')]
        if others:
            foreign[name] = others
    return ready, todo, foreign


def window_budget(ip_max_clients, stations, alt_cap, reserve):
    """-> (level, text): do stations + alts + the delete/rebuild window + the spare fit the per-IP window limit?"""
    from factory.schedule import ACCOUNT_WORKER_WINDOWS
    if ip_max_clients <= 0:
        return WARN, f'没设单 IP 窗口上限（[game] ip_max_clients = 0）：窗口多了进不了世界（error=110），建议填 50'
    total = stations + alt_cap + ACCOUNT_WORKER_WINDOWS
    text = (f'窗口预算：工位 {stations} + 小号 {alt_cap} + 删号/重建 {ACCOUNT_WORKER_WINDOWS} = {total}，'
            f'预留 {reserve}，单 IP 上限 {ip_max_clients}')
    if stations + ACCOUNT_WORKER_WINDOWS + 1 > ip_max_clients - 1:
        return BAD, text + '：工位太多，一个小号都开不了，请减少 [[station]]'
    if total + reserve > ip_max_clients:
        return BAD, text + '：超了，会有窗口进不了世界'
    return OK, text


def expected_client_hashes(launcher_source=ROOT / 'native' / 'launcher.cpp'):
    """Game exe SHA256 -> version label, the builds launcher.exe accepts (CLIENT_HASHES in its source,
    one `"<sha256>", // <version>` line each); empty if the source is missing."""
    p = Path(launcher_source)
    text = p.read_text('utf-8') if p.is_file() else ''
    return {h: v for h, v in re.findall(r'"([0-9a-f]{64})",\s*//\s*(\S+)', text)}


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    r = Report()
    v = sys.version_info
    r.line(OK if v >= (3, 12) else BAD, f'Python {v.major}.{v.minor}.{v.micro}（需要 3.12 以上，开发电脑用 3.14）')
    local = ROOT / config.LOCAL_NAME
    if not local.is_file():
        r.line(BAD, f'没有 {local.name}：把 local.example.toml 复制成 local.toml，填好游戏路径、号段、密码')
        return 1
    r.line(OK, f'{local.name} 存在')
    for f in (native.LAUNCHER, ROOT / 'bin' / 'provision_native.dll'):
        r.line(OK if f.is_file() else BAD, f'{f.relative_to(ROOT)}' + ('' if f.is_file() else ' 缺失（仓库里应该带着，重新拉取代码）'))

    from factory.supervisor import load_supervisor
    try:
        sup = load_supervisor(ROOT / 'supervisor.toml')
        login = sup.login
        r.line(OK, f'游戏程序 {login.game_exe}')
    except Exception as e:
        r.line(BAD, f'supervisor.toml + local.toml 读不出来：{e}')
        return 1
    known = expected_client_hashes()
    if not Path(login.game_exe).is_file():
        r.line(BAD, f'游戏程序不存在：{login.game_exe}')
    elif known:
        version = known.get(file_sha256(login.game_exe))
        if version:
            r.line(OK, f'游戏版本 {version}，代码支持（SHA256 匹配；支持 {"、".join(sorted(set(known.values())))}）')
        else:
            r.line(BAD, f'游戏版本和代码不匹配（SHA256 不在 {"、".join(sorted(set(known.values())))} 里）：游戏更新过的话，'
                        '先跑 python -m provisioner.addrscan 按特征码找新地址，改好后在 launcher.cpp 的 CLIENT_HASHES '
                        '加上新哈希并重新编译')
    if Path(login.game_exe).is_file():
        from . import addrscan
        try:
            rows, problems = addrscan.compare(addrscan.scan(login.game_exe), addrscan.code_constants())
            stale = addrscan.missing_in_files({name: value for name, _, value, _ in rows})
            r.line(BAD if problems or stale else OK,
                   f'特征码找到的 {len(rows)} 个游戏地址' + ('和代码一致' if not problems and not stale else
                   f'：{problems} 个对不上、{len(stale)} 处副本要改（python -m provisioner.addrscan 看明细）'))
        except Exception as e:
            r.line(BAD, f'特征码扫描失败：{e}')
    names = [a.name for a in login.accounts]
    if any(not a.password for a in login.accounts):
        r.line(BAD, 'local.toml [accounts] 的小号密码还没填')
    r.line(OK, f'本机号段 {names[0]} .. {names[-1]}，共 {len(names)} 个账号（其它电脑不能用这些号）')

    for name, loader in (('stations.toml', config.load_stations), ('config.toml', config.load)):
        try:
            loaded = loader(ROOT / name)
            if name == 'stations.toml':
                r.line(OK, '工位 ' + '、'.join(f'{s.label}={s.account.name}' for s in loaded[1]))
                game = config._read(ROOT / name).get('game', {})
                r.line(*window_budget(config.ip_max_clients(game), len(loaded[1]), sup.policy.max_windows,
                                      config.ip_reserve(game)))
                if sup.window_budget:
                    r.line(OK, sup.window_budget)
        except Exception as e:
            r.line(BAD, f'{name}: {e}')

    free = native.free_memory_mb()
    r.line(OK if free > login.min_free_memory_mb * 2 else WARN,
           f'空闲内存 {free} MB（低于 {login.min_free_memory_mb} MB 时总大脑暂停开窗口）')

    ready, todo, foreign = role_status(ROOT / 'state', names)
    if todo:
        r.line(WARN, f'{len(todo)} 个账号还没建好 4 个角色（{todo[0]} ..），第一次请先双击 一键建角.cmd（只补没建的，可重复运行）')
    else:
        r.line(OK, f'{len(ready)} 个账号的 4 个角色都已建好')
    for acct, others in foreign.items():
        r.line(WARN, f'{acct} 有不是本工具建的角色 {others}：它占着槽，那个号只能用剩下的槽')

    db = sup.factory.db_path
    if db.is_file():
        conn = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
        accts = {a for (a,) in conn.execute("SELECT DISTINCT account FROM alts WHERE phase != 'deleted'")}
        conn.close()
        alien = sorted(accts - set(names))
        r.line(WARN if alien else OK, f'数据库 {db.relative_to(ROOT)}：' +
               (f'有 {len(alien)} 个号段外账号的进行中角色（{alien[:5]}..），像是从别的电脑拷来的；'
                f'新电脑请不要拷 state 目录' if alien else '没有号段外的角色'))
    else:
        r.line(OK, '数据库还不存在（第一次运行会自动新建）')

    print()
    print('有错误，请先处理上面标 [错误] 的项。' if r.bad else '环境检查通过。下一步见 docs/DEPLOY.md。')
    return 1 if r.bad else 0


if __name__ == '__main__':
    sys.exit(main())
