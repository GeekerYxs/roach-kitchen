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


def expected_client_hash(launcher_source=ROOT / 'native' / 'launcher.cpp'):
    """The game exe SHA256 launcher.exe accepts (CLIENT_HASH in its source); None if the source is missing."""
    p = Path(launcher_source)
    m = re.search(r'CLIENT_HASH="([0-9a-f]{64})"', p.read_text('utf-8')) if p.is_file() else None
    return m.group(1) if m else None


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
    want = expected_client_hash()
    if not Path(login.game_exe).is_file():
        r.line(BAD, f'游戏程序不存在：{login.game_exe}')
    elif want and file_sha256(login.game_exe) != want:
        r.line(BAD, '游戏版本和代码不匹配（SHA256 不同）：游戏更新过的话，要先重新定位基址、改 launcher.cpp 的 '
                    'CLIENT_HASH 并重新编译；或者这台电脑的游戏还没更新')
    elif want:
        r.line(OK, '游戏版本与代码匹配（SHA256）')
    names = [a.name for a in login.accounts]
    if any(not a.password for a in login.accounts):
        r.line(BAD, 'local.toml [accounts] 的小号密码还没填')
    r.line(OK, f'本机号段 {names[0]} .. {names[-1]}，共 {len(names)} 个账号（其它电脑不能用这些号）')

    for name, loader in (('stations.toml', config.load_stations), ('config.toml', config.load)):
        try:
            loaded = loader(ROOT / name)
            if name == 'stations.toml':
                r.line(OK, '工位 ' + '、'.join(f'{s.label}={s.account.name}' for s in loaded[1]))
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
