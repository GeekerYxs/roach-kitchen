"""Loads the TOML config files into immutable settings. No other module reads them.

config.toml -> Settings (batch role creation); enter.toml -> EnterSettings (log in and enter a role).
"""
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .protocol import encode_role_name


@dataclass(frozen=True)
class Account:
    name: str
    password: str
    slot: int = 0  # enter tool only: per-account role slot override, 0 = use the default

    def __repr__(self):  # never leak the password into logs/tracebacks
        return f'Account({self.name!r})'


@dataclass(frozen=True)
class Settings:
    game_exe: Path
    server_index: int
    parallel: int
    launch_interval: float
    inject_delay_ms: int
    login_retries: int
    roles_per_account: int
    role_suffix: str
    create_interval: float
    create_timeout: float
    relogin_after_create: bool
    kill_on_failure: bool
    keep_windows_open: bool
    min_free_memory_mb: int
    accounts: tuple

    def role_names(self, account):
        return [f'{account}{self.role_suffix}{i}' for i in range(1, self.roles_per_account + 1)]


@dataclass(frozen=True)
class EnterSettings:
    game_exe: Path
    server_index: int
    max_windows: int
    launch_interval: float
    inject_delay_ms: int
    login_retries: int
    min_free_memory_mb: int
    slot: int
    enter_timeout: float
    kill_on_failure: bool
    accounts: tuple

    def slot_of(self, account):
        return account.slot or self.slot


@dataclass(frozen=True)
class PipelineSettings:
    game_exe: Path
    server_index: int
    max_windows: int
    launch_interval: float
    inject_delay_ms: int
    login_retries: int
    min_free_memory_mb: int
    slots: tuple
    enter_timeout: float
    skip_done: bool
    escape_action: int
    novice_timeout: float
    tick: float
    accounts: tuple


def _slot(value, where):
    slot = int(value)
    if not 1 <= slot <= 4:
        raise ValueError(f'{where}: 角色槽位必须是 1..4，实际 {value}')
    return slot


def _slots(value):
    """slots = 1 or slots = [2, 3, 4] -> tuple of distinct slots in the given order."""
    items = value if isinstance(value, list) else [value]
    slots = tuple(dict.fromkeys(_slot(v, 'slots') for v in items))
    if not slots:
        raise ValueError('slots 不能为空')
    return slots


def _accounts(section):
    if 'list' in section:
        items = [Account(str(x['account']), str(x['password']),
                         _slot(x['slot'], x['account']) if 'slot' in x else 0) for x in section['list']]
    else:
        prefix, digits = section.get('prefix', ''), int(section.get('digits', 0))
        start, count = int(section['start']), int(section['count'])
        items = [Account(f'{prefix}{n:0{digits}d}', str(section.get('password', '')))
                 for n in range(start, start + count)]
    names = [a.name for a in items]
    if len(set(names)) != len(names):
        raise ValueError(f'账号重复: {names}')
    for a in items:
        if not (1 <= len(a.name) <= 15 and a.name.isascii() and a.name.isalnum()):
            raise ValueError(f'账号必须是 1..15 位 ASCII 字母数字: {a.name!r}')
        if not 1 <= len(a.password.encode()) <= 15:
            raise ValueError(f'{a.name}: 密码长度必须 1..15 字节')
    return tuple(items)


def _launch_common(data):
    """[game] plus the launch-related [batch] keys shared by both tools."""
    g, b = data.get('game', {}), data['batch']
    if 'exe' not in g:
        raise ValueError(f'没有设置游戏程序路径：请在 {LOCAL_NAME} 的 [game] 里填 exe（模板见 local.example.toml）')
    if not data.get('accounts'):
        raise ValueError(f'没有设置账号：请在 {LOCAL_NAME} 的 [accounts] 里填本机号段和密码')
    common = dict(
        game_exe=Path(g['exe']),
        server_index=int(g.get('server_index', 0)),
        launch_interval=float(b.get('launch_interval', 2.0)),
        inject_delay_ms=int(b.get('inject_delay_ms', 3000)),
        login_retries=max(0, int(b.get('login_retries', 2))),
        min_free_memory_mb=int(b.get('min_free_memory_mb', 3000)),
        kill_on_failure=bool(b.get('kill_on_failure', False)),
        accounts=_accounts(data['accounts']),
    )
    if not common['game_exe'].is_file():
        raise FileNotFoundError(f'游戏程序不存在: {common["game_exe"]}')
    return common


LOCAL_NAME = 'local.toml'


def merge_local(data, local):
    """Overlay this machine's local.toml (not in git) on a tool's config.
    - every section of local except [accounts]/[passwords] updates the same-named section key by key
      ([game] is always applied: the exe path is per machine);
    - [accounts] (this machine's alt range + password) fills every key the tool's own [accounts] does not set,
      so an empty or missing tool [accounts] means "this machine's range"; a tool [accounts] with
      from = "store_accounts" takes that local section instead (the 料理 store accounts box07.., store.toml);
    - [passwords] (account = password) fills [[station]] entries and [accounts] list items without a password;
    - [[station]] in local (only applied to files that have stations) replaces the shared list: this machine's own
      stations, so changing e.g. the receiver never edits a file that git pull updates."""
    out = {k: dict(v) if isinstance(v, dict) else v for k, v in data.items()}
    if 'station' in local and 'station' in out:
        out['station'] = list(local['station'])
    for section, values in local.items():
        if section in ('accounts', 'passwords') or not isinstance(values, dict):
            continue
        if section == 'game' or isinstance(out.get(section), dict):
            out[section] = {**out.get(section, {}), **values}
    acc = out.get('accounts', {})
    source = acc.pop('from', 'accounts')
    if source != 'accounts' and not isinstance(local.get(source), dict):
        raise ValueError(f'{LOCAL_NAME} 里没有 [{source}]（模板见 local.example.toml）')
    la, pw = local.get(source, {}), local.get('passwords', {})
    if 'list' in acc:
        acc['list'] = [x if x.get('password') else {**x, 'password': pw.get(x['account'], la.get('password', ''))}
                       for x in acc['list']]
    elif la or 'accounts' in out:
        out['accounts'] = {**la, **acc}
    if 'station' in out:
        out['station'] = [x if x.get('password') else {**x, 'password': pw.get(str(x.get('account', '')), '')}
                          for x in out['station']]
    return out


def _read(path):
    """A tool's TOML, with local.toml from the same folder laid over it (see merge_local)."""
    path = Path(path)
    data = tomllib.loads(path.read_text('utf-8'))
    local = path.with_name(LOCAL_NAME)
    if path.name != LOCAL_NAME and local.is_file():
        data = merge_local(data, tomllib.loads(local.read_text('utf-8')))
    return data


def load(path):
    data = _read(path)
    b = data['batch']
    common = _launch_common(data)
    accounts = common['accounts']
    parallel = max(1, int(b.get('parallel', 8)))
    keep = b.get('keep_windows_open', 'auto')
    # Windows that stay open never free their slot, so keeping them is only possible
    # when every account fits in `parallel` windows at once.
    keep = len(accounts) <= parallel if keep == 'auto' else bool(keep)
    if keep and len(accounts) > parallel:
        raise ValueError(f'keep_windows_open=true 时账号数({len(accounts)})不能超过 parallel({parallel})，'
                         f'否则窗口会无限累积；请改成 "auto" 或 false')
    s = Settings(
        **common,
        parallel=parallel,
        roles_per_account=int(b.get('roles_per_account', 4)),
        role_suffix=str(b.get('role_suffix', 'r')),
        create_interval=float(b.get('create_interval', 1.5)),
        create_timeout=float(b.get('create_timeout', 15)),
        relogin_after_create=bool(b.get('relogin_after_create', True)),
        keep_windows_open=keep,
    )
    if not 1 <= s.roles_per_account <= 4:
        raise ValueError('roles_per_account 必须是 1..4')
    for a in s.accounts:
        for role in s.role_names(a.name):
            encode_role_name(role)
    return s


def load_pipeline(path):
    data = _read(path)
    b, n = data['batch'], data.get('novice', {})
    common = _launch_common(data)
    common.pop('kill_on_failure')  # the pipeline always closes its own windows (window budget)
    return PipelineSettings(
        **common,
        max_windows=max(1, int(b.get('max_windows', 8))),
        slots=_slots(b.get('slots', b.get('slot', 1))),
        enter_timeout=float(b.get('enter_timeout', 60)),
        skip_done=bool(b.get('skip_done', True)),
        escape_action=int(n.get('escape_action', 8)),
        novice_timeout=float(n.get('timeout', 300)),
        tick=float(n.get('tick', 0.15)),
    )


STATION_ROLES = {'dispatcher': '调度员（给金币+传送）', 'well': '古井队长', 'coast': '海岸队长', 'receiver': '收货人'}


@dataclass(frozen=True)
class Station:
    station_id: str
    role: str
    account: Account          # account.slot = the role slot this station plays
    name: str = ''            # expected character name (optional): checked after login, and used to spot
                              # the same character already online in a window we did not start

    @property
    def label(self):
        return f'{self.station_id}({STATION_ROLES[self.role]})'


def load_stations(path):
    """stations.toml -> (EnterSettings for logging them in, tuple of enabled Station)."""
    data = _read(path)
    b = data.get('batch', {})
    stations = []
    for i, x in enumerate(data.get('station', []), 1):
        if not x.get('enabled', True):
            continue
        sid, role = str(x.get('id', '')), str(x.get('role', ''))
        if not sid:
            raise ValueError(f'第 {i} 个 [[station]] 缺少 id')
        if role not in STATION_ROLES:
            raise ValueError(f'{sid}: role 必须是 {"/".join(STATION_ROLES)}，实际 {role!r}')
        if not str(x.get('password', '')):
            raise ValueError(f'{sid}: 还没有填密码（在 {LOCAL_NAME} 的 [passwords] 里写 {x.get("account", "账号")} = "密码"）')
        stations.append(Station(sid, role, Account(str(x['account']), str(x['password']),
                                                    _slot(x.get('slot', 1), sid)), str(x.get('name', ''))))
    ids = [s.station_id for s in stations]
    if len(set(ids)) != len(ids):
        raise ValueError(f'工位 id 重复: {ids}')
    data['accounts'] = {'list': [{'account': s.account.name, 'password': s.account.password,
                                  'slot': s.account.slot} for s in stations]}
    data['batch'] = b
    settings = EnterSettings(
        **_launch_common(data),
        max_windows=max(1, len(stations)),
        slot=1,
        enter_timeout=float(b.get('enter_timeout', 60)),
    )
    return settings, tuple(stations)


def load_enter(path):
    data = _read(path)
    b = data['batch']
    s = EnterSettings(
        **_launch_common(data),
        max_windows=max(1, int(b.get('max_windows', 8))),
        slot=_slot(b.get('slot', 1), 'slot'),
        enter_timeout=float(b.get('enter_timeout', 60)),
    )
    # Every entered window stays open, so the account count IS the window count.
    if len(s.accounts) > s.max_windows:
        raise ValueError(f'账号数 {len(s.accounts)} 超过 max_windows={s.max_windows}；'
                         f'进游戏的窗口会一直开着，请减少账号或调大 max_windows（注意内存）')
    return s
