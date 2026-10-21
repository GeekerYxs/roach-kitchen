"""Wipe: delete EVERY role of a range of alt accounts (e.g. mw301..mw380), with a report.

Entry: python -m factory.wipe [wipe.toml] [起始号 结束号] [--check] [--yes]   (一键清空小号.cmd asks interactively)
User, 2026-10-14: when the line's state is a mess, wipe the whole range; ~3 h later the slots are free again and the
supervisor rebuilds them (stage 11e: deleted rN -> r(N+4)), so factory.db is kept consistent instead of thrown away.

Before anything is deleted (main):
  - the range comes from the command line or a prompt (default: this machine's local.toml range); accounts that
    are stations (stations table / station list / local.toml [passwords]) are always removed from it
  - refuses while the supervisor looks alive (a station heartbeat in the last `supervisor_quiet` seconds): it would
    keep pulling the roles being deleted
  - warns about accounts outside this machine's range (another PC may be playing them; a login kicks it)
  - lists the open game windows that show a role of the range; they are terminated (they would be kicked anyway)
  - shows the plan and asks to type DELETE (not asked with --check or --yes)
Per account (accounts in parallel, max_windows at once; one delete per process, so one login per role):
  1. login stopped on the selection screen (the login every tool uses), read the server's role list and its raw
     entries (logged: they are also used to learn the "being deleted" field, see deleting_candidates)
  2. first login only: roles named <account>r<N> are registered in factory.db; factory.db roles of this account
     that are no longer listed are marked gone (deleted)
  3. plan_account (pure): already deleted per factory.db -> skip (a deleted role stays listed with a restore
     button for ~3 h; never delete twice), unknown result of an earlier delete -> skip (human checks), station ->
     skip, otherwise delete
  4. delete the first role left with stage 10's checked sender (factory.delete.AccountDeleteJob.delete_listed:
     +0x60 / busy flag / connection checks, pending mark, wait 0x4004), close the window, next login
  5. stops when nothing is left to delete, after 2 failed deletes, or after MAX_LOGINS logins
Report: logs/wipe_*.log, logs/wipe_report_*.md (read this), logs/wipe_roles_*.csv (Excel), logs/wipe_*.json.
Re-running is safe: roles already deleted are skipped, failures are tried again.
Decisions are pure (tests/test_factory_wipe.py).
"""
import csv
import json
import re
import sys
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path

from provisioner import config, log, native
from provisioner.config import Account
from provisioner.login import LaunchThrottle, LoginFailed, login, read_session
from provisioner.memory import ProcessMemory
from provisioner.pipeline import OwnWindows, remember_roster
from provisioner.procs import TITLE_NAME, game_window_titles
from provisioner.protocol import MAX_SLOTS, TapReader, read_roster_raw

from . import db
from .delete import ACTION, AccountDeleteJob, DeleteSettings
from .config import load_settings
from .phase import DELETED
from .runner import ROLE_NAME

ROOT = Path(__file__).resolve().parent.parent
MAX_LOGINS = MAX_SLOTS + 2          # 4 deletes + room for a retry
MAX_FAILS = 2                       # failed deletes per account before giving up on it
NAME_END = 0x28                     # entry +0 id, +4 level, +0x14 name: bytes before this are known fields
CONFIRM_WORD = 'DELETE'

DELETE, DONE, SKIP = 'delete', 'done', 'skip'


# ---- pure decisions -------------------------------------------------------------------------------------

def account_names(prefix, digits, start, end):
    """mw301..mw380 -> ['mw301', ..., 'mw380']. Numbers, inclusive."""
    if start < 0 or end < start:
        raise ValueError(f'号段不对: {start}..{end}（结束号要 >= 起始号）')
    if end - start + 1 > 1000:
        raise ValueError(f'号段太大: {end - start + 1} 个账号')
    return [f'{prefix}{n:0{digits}d}' for n in range(start, end + 1)]


def own_role(name, account):
    """True for names this tool chain gives (<account>r<N>): only those go into factory.db (rebuild needs it)."""
    m = ROLE_NAME.match(name)
    return bool(m) and m[1] == account


def plan_account(roster, rows, station_ids):
    """roster: [(char_id, level, name)] in slot order; rows: {char_id: factory.db alts row}; station_ids: char ids
    of stations. -> [dict(slot, char_id, level, name, action, why)]"""
    out = []
    for slot, (cid, level, name) in enumerate(roster, 1):
        row = rows.get(cid)
        if cid in station_ids:
            action, why = SKIP, '是工位角色，不删'
        elif row is not None and row['name'] != name:
            action, why = SKIP, f'数据库里 ID {cid} 叫 {row["name"]}，和选角列表的 {name} 不一致'
        elif row is not None and (row['phase'] == DELETED or row['deleted_at']):
            action, why = DONE, '之前已删除（数据库有记录），正在等槽位释放'
        elif row is not None and row['pending_action'] == ACTION:
            action, why = SKIP, '之前的删除没收到服务器回包，结果不明：不重发，请人工看选角界面'
        else:
            action, why = DELETE, ''
        out.append({'slot': slot, 'char_id': cid, 'level': level, 'name': name, 'action': action, 'why': why})
    return out


def next_target(plan, attempted):
    """The first role still to delete that this run has not tried yet, or None."""
    return next((p for p in plan if p['action'] == DELETE and p['char_id'] not in attempted), None)


def stale_rows(rows, listed_ids):
    """factory.db roles of the account that the server no longer lists and that are not recorded as deleted."""
    return [r for r in rows if r['char_id'] not in listed_ids and r['phase'] != DELETED and not r['deleted_at']]


def deleting_candidates(deleted, alive):
    """Raw roster entries of roles known to be deleted vs alive -> [(offset, value)] where every deleted entry has
    the same byte and no alive entry has it (past the id/level/name fields). Empty when either side is empty."""
    if not deleted or not alive:
        return []
    out = []
    for off in range(NAME_END, min(len(e) for e in deleted + alive)):
        values = {e[off] for e in deleted}
        if len(values) == 1:
            v = values.pop()
            if all(e[off] != v for e in alive):
                out.append((off, v))
    return out


def supervisor_alive(heartbeats, now, quiet):
    """heartbeats: [(station_id, status, heartbeat_at)] -> stations that reported in the last `quiet` seconds."""
    return [sid for sid, status, at in heartbeats if status != 'offline' and now - at < quiet]


def window_roles(titles, accounts):
    """{pid: [titles]} -> [(pid, role, account)] for game windows showing a role of one of `accounts`."""
    out = []
    for pid, ts in titles.items():
        for t in ts:
            m = TITLE_NAME.search(t)
            r = ROLE_NAME.match(m.group(1)) if m else None
            if r and r[1] in accounts:
                out.append((pid, m.group(1), r[1]))
                break
    return out


def eta(at, hours):
    return time.strftime('%m-%d %H:%M', time.localtime(at + hours * 3600)) if at else ''


# ---- settings -------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class WipeSettings:
    delete: DeleteSettings      # launch + delete parameters (stage 10's sender reads reply_timeout from it)
    prefix: str
    digits: int
    local_start: int            # this machine's range in local.toml
    local_end: int
    password: str
    release_hours: float
    supervisor_quiet: float
    close_open_windows: bool


def load_wipe(path):
    data = config._read(path)
    acc = data.get('accounts', {})
    if 'list' in acc or 'start' not in acc:
        raise ValueError('local.toml 的 [accounts] 要写号段（prefix/start/count/digits/password）')
    w, b = data.get('wipe', {}), data['batch']
    common = config._launch_common(data)
    start = int(acc['start'])
    s = DeleteSettings(**common, max_windows=max(1, int(b.get('max_windows', 8))), max_roles=0,
                       reply_timeout=float(w.get('reply_timeout', 15)),
                       close_settle=float(w.get('close_settle', 3)),
                       close_timeout=float(w.get('close_timeout', 3)),
                       factory=load_settings(ROOT / w.get('factory', 'factory.toml')))
    return WipeSettings(delete=s, prefix=str(acc.get('prefix', '')), digits=int(acc.get('digits', 0)),
                        local_start=start, local_end=start + int(acc['count']) - 1,
                        password=str(acc.get('password', '')),
                        release_hours=float(w.get('release_hours', 3.2)),
                        supervisor_quiet=float(w.get('supervisor_quiet', 120)),
                        close_open_windows=bool(w.get('close_open_windows', True)))


def station_accounts(conn):
    """Accounts that play stations: never wiped."""
    names = {r['account'] for r in conn.execute('SELECT account FROM stations') if r['account']}
    for f in ('stations.toml', 'local.toml'):
        p = ROOT / f
        if p.is_file():
            data = tomllib.loads(p.read_text('utf-8'))
            names |= {str(x.get('account', '')) for x in data.get('station', [])}
            names |= set(data.get('passwords', {}))
    return names - {''}


# ---- one account ----------------------------------------------------------------------------------------

@dataclass
class AccountResult:
    account: str
    roles: list = field(default_factory=list)     # plan rows of the first login + 'result'/'detail'/'deleted_at'
    error: str = ''
    logins: int = 0
    seconds: float = 0.0
    samples: dict = field(default_factory=dict)   # char_id -> {'hex': raw entry, 'deleted': known deleted then}


class AccountWipeJob:
    def __init__(self, ws, account, check_only, own, throttle, station_ids):
        self.ws, self.s, self.account, self.check_only = ws, ws.delete, account, check_only
        self.own, self.throttle, self.station_ids = own, throttle, station_ids
        self.log = log.for_account(account.name)
        self.runtime = ROOT / 'runtime'
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.sender = AccountDeleteJob(self.s, account, [], {}, own, throttle, self.s.factory.db_path)

    def run(self):
        res = AccountResult(self.account.name)
        started = time.monotonic()
        conn = db.connect(self.s.factory.db_path)
        try:
            self._loop(conn, res)
        except Exception as e:
            res.error = f'{type(e).__name__}: {e}'
            self.log.error('出错: %s', e, exc_info=not isinstance(e, RuntimeError))
        finally:
            conn.close()
        res.seconds = round(time.monotonic() - started, 1)
        for r in res.roles:
            r.setdefault('result', {DONE: '之前已删', SKIP: '跳过', DELETE: '只检测' if self.check_only else '没删到'}
                         [r['action']])
        return res

    def _loop(self, conn, res):
        attempted, fails = set(), 0
        by_id = {}
        while res.logins < MAX_LOGINS:
            res.logins += 1
            self.log.info('== 第 %d 次登录到选角界面 ==', res.logins)
            try:
                session = login(self.s, self.account, self.runtime, self.throttle, self.log)
            except LoginFailed as e:
                res.error = str(e)
                return
            self.own.add(session)
            try:
                native.arm(session)
                reader = TapReader(self.runtime, session.pid)
                reader.poll()
                context, roster = read_session(session, self.account.name, self.log)
                remember_roster(self.account.name, roster)
                with ProcessMemory(session.pid, session.base) as mem:
                    raw = read_roster_raw(mem, context)
                for (_, _, name), entry in zip(roster, raw):
                    self.log.info('列表项 %s 原始数据: %s', name, entry.hex())
                if res.logins == 1:
                    self._sync_db(conn, roster)
                rows = {r['char_id']: r for r in conn.execute('SELECT * FROM alts WHERE account=?',
                                                              (self.account.name,))}
                plan = plan_account(roster, rows, self.station_ids)
                for p, entry in zip(plan, raw):     # the entry as it looked while factory.db said (not) deleted
                    res.samples[p['char_id']] = {'hex': entry.hex(), 'deleted': p['action'] == DONE}
                if res.logins == 1:
                    res.roles = plan
                    by_id = {p['char_id']: p for p in plan}
                    for p in plan:
                        self.log.info('槽%d %s ID=%d %d级: %s %s', p['slot'], p['name'], p['char_id'], p['level'],
                                      {DELETE: '要删', DONE: '已删过', SKIP: '跳过'}[p['action']], p['why'])
                target = next_target(plan, attempted)
                if self.check_only or target is None:
                    return
                attempted.add(target['char_id'])
                entry = by_id.setdefault(target['char_id'], dict(target))
                try:
                    out = self.sender.delete_listed(conn, session, reader, context, roster,
                                                    target['char_id'], target['name'])
                    entry.update(result='已删除' if not out.get('skipped') else '已不在列表',
                                 detail=f"{out.get('reply_ms', '')}ms" if out.get('reply_ms') else '',
                                 deleted_at=time.time())
                except Exception as e:      # noqa: BLE001 - one role failing must not stop the account
                    fails += 1
                    entry.update(result='失败', detail=f'{type(e).__name__}: {e}')
                    self.log.error('%s 删除失败: %s', target['name'], e)
                    if fails >= MAX_FAILS:
                        res.error = f'{fails} 次删除失败，这个账号先停'
                        return
            finally:
                self.own.close(session, self.log)
                time.sleep(self.s.close_settle)
        res.error = f'登录了 {MAX_LOGINS} 次还没删完'

    def _sync_db(self, conn, roster):
        now = time.time()
        listed = {cid for cid, _, _ in roster}
        for cid, _, name in roster:
            if own_role(name, self.account.name) and cid not in self.station_ids:
                db.register_alt(conn, cid, self.account.name, int(ROLE_NAME.match(name)[2]), name, now)
        rows = conn.execute('SELECT * FROM alts WHERE account=?', (self.account.name,)).fetchall()
        for r in stale_rows(rows, listed):
            db.mark_gone(conn, r['char_id'], now)
            self.log.info('数据库里的 %s 已不在选角列表里，记为已删除', r['name'])


# ---- report ---------------------------------------------------------------------------------------------

def write_report(stem, results, ws, label, check_only, seconds, candidates):
    roles = [(res.account, r) for res in results for r in res.roles]
    count = lambda word: sum(r.get('result') == word for _, r in roles)   # noqa: E731
    deleted = [r['deleted_at'] for _, r in roles if r.get('deleted_at')]
    empty = [res.account for res in results if not res.roles and not res.error]
    foreign = [f"{a} {r['name']}" for a, r in roles if not own_role(r['name'], a)]
    bad = [(a, r) for a, r in roles if r.get('result') in ('失败', '跳过', '没删到')]
    errors = [res for res in results if res.error]
    lines = [f'# 清空小号报告 {time.strftime("%Y-%m-%d %H:%M")}', '',
             f'- 号段 {label}，{len(results)} 个账号，模式：{"只检测（什么都没删）" if check_only else "检测并删除"}',
             f'- 用时 {seconds / 60:.1f} 分钟，共登录 {sum(r.logins for r in results)} 次', '',
             '| 结果 | 角色数 |', '|---|---|']
    for word in ('已删除', '已不在列表', '之前已删', '只检测', '跳过', '失败', '没删到'):
        if count(word):
            lines.append(f'| {word} | {count(word)} |')
    lines += [f'| 空账号（0 个角色） | {len(empty)} 个账号 |', '']
    if deleted:
        lines += [f'预计槽位释放：{eta(min(deleted), ws.release_hours)} ~ {eta(max(deleted), ws.release_hours)}'
                  f'（删除后约 {ws.release_hours:g} 小时）。', '',
                  '下一步：打开 一键总大脑.cmd 就行，它会在槽位释放后自动按 rN -> r(N+4) 重建（mw301r1 删了建 mw301r5），'
                  '再自动走新手村、古井……不需要再跑 一键建角。', '']
    if errors:
        lines += ['## 没做完的账号（再运行一次本工具会接着做）', '', '| 账号 | 原因 |', '|---|---|']
        lines += [f'| {r.account} | {r.error} |' for r in errors] + ['']
    if bad:
        lines += ['## 跳过 / 失败的角色', '', '| 账号 | 槽 | 角色 | 结果 | 原因 |', '|---|---|---|---|---|']
        lines += [f"| {a} | {r['slot']} | {r['name']} | {r['result']} | {r.get('detail') or r['why']} |"
                  for a, r in bad] + ['']
    if empty:
        lines += ['## 空账号', '', '这些账号本来就没有角色。总大脑只重建删掉的角色，空账号要先跑一次 一键建角.cmd：', '',
                  ', '.join(empty), '']
    if foreign:
        lines += ['## 不是 <账号>r<编号> 命名的角色', '',
                  '照删，但不进数据库，总大脑不会给它们重建（槽位释放后用 一键建角 补）：', '', ', '.join(foreign), '']
    lines += ['## 每个账号', '', '| 账号 | 删前角色 | 结果 | 登录次数 | 用时 |', '|---|---|---|---|---|']
    for res in results:
        names = ' '.join(r['name'] for r in res.roles) or '（空）'
        outcome = ' '.join(f"{r['name']}:{r['result']}" for r in res.roles) or (res.error or '-')
        lines.append(f'| {res.account} | {names} | {outcome} | {res.logins} | {res.seconds:.0f}s |')
    lines += ['', '## “正在删除”字段线索', '',
              '对比数据库里已删的角色和没删的角色，选角列表项里所有已删的都相同、没删的都不同的字节（以后可用来直接认出正在删除的角色）：',
              '', ', '.join(f'+{o:#x}={v:02x}' for o, v in candidates) or '还没有（需要同一次登录里既有已删又有未删的角色）', '']
    md = stem.with_name(stem.name.replace('wipe_', 'wipe_report_') + '.md')
    md.write_text('\n'.join(lines), 'utf-8')
    with open(stem.with_name(stem.name.replace('wipe_', 'wipe_roles_') + '.csv'), 'w', newline='',
              encoding='utf-8-sig') as f:
        out = csv.writer(f)
        out.writerow(['账号', '槽', '角色', '角色ID', '等级', '结果', '说明', '删除时间', '预计释放'])
        for a, r in roles:
            at = r.get('deleted_at')
            out.writerow([a, r['slot'], r['name'], r['char_id'], r['level'], r['result'], r.get('detail') or r['why'],
                          time.strftime('%H:%M:%S', time.localtime(at)) if at else '', eta(at, ws.release_hours)])
    stem.with_suffix('.json').write_text(json.dumps(
        [{'account': r.account, 'error': r.error, 'logins': r.logins, 'seconds': r.seconds, 'roles': r.roles,
          'raw_entries': r.samples} for r in results], ensure_ascii=False, indent=1), 'utf-8')
    return md


def learn_candidates(results):
    deleted, alive = [], []
    for res in results:
        for sample in res.samples.values():
            (deleted if sample['deleted'] else alive).append(bytes.fromhex(sample['hex']))
    return deleting_candidates(deleted, alive)


# ---- the run --------------------------------------------------------------------------------------------

def ask(prompt, default):
    answer = input(f'{prompt} [{default}]: ').strip()
    return answer or str(default)


def parse_args(argv):
    flags = {a for a in argv if a.startswith('--')}
    rest = [a for a in argv if not a.startswith('--')]
    cfg = Path(rest[0]) if rest and rest[0].endswith('.toml') else ROOT / 'wipe.toml'
    nums = [a for a in rest if not a.endswith('.toml')]
    return cfg, nums, '--check' in flags, '--yes' in flags


def main():
    cfg, nums, check_only, yes = parse_args(sys.argv[1:])
    try:
        ws = load_wipe(cfg)
    except Exception as e:
        print(f'配置错误 ({cfg}): {e}')
        return 2
    interactive = not nums
    if interactive:
        print(f'本机号段（local.toml）: {ws.prefix}{ws.local_start:0{ws.digits}d} .. {ws.prefix}{ws.local_end:0{ws.digits}d}')
        nums = [ask('起始号（只写数字）', ws.local_start), ask('结束号（只写数字）', ws.local_end)]
        if not check_only:
            check_only = ask('模式：1 = 只检测不删，2 = 检测并删除', 1) != '2'
    try:
        start, end = int(nums[0]), int(nums[1] if len(nums) > 1 else nums[0])
        names = account_names(ws.prefix, ws.digits, start, end)
    except (ValueError, IndexError) as e:
        print(f'号段输入不对: {e}')
        return 2
    label = f'{names[0]}..{names[-1]}'

    log_path = log.setup(ROOT / 'logs', prefix='wipe')
    logger = log.for_account('main')
    logger.info('日志文件: %s', log_path)
    conn = db.connect(ws.delete.factory.db_path)
    try:
        stations = station_accounts(conn)
        station_ids = set(db.station_roles(conn))
        beats = [(r['station_id'], r['status'], r['heartbeat_at'])
                 for r in conn.execute('SELECT station_id, status, heartbeat_at FROM stations')]
    finally:
        conn.close()
    excluded = sorted(set(names) & stations)
    if excluded:
        logger.warning('这些账号是工位大号，排除: %s', ', '.join(excluded))
        names = [n for n in names if n not in stations]
    alive = supervisor_alive(beats, time.time(), ws.supervisor_quiet)
    if alive and not check_only:
        logger.error('总大脑好像还在运行（%.0f 秒内有工位心跳: %s）。请先关掉 一键总大脑 的窗口再来。',
                     ws.supervisor_quiet, ', '.join(alive))
        return 2
    outside = [n for n in names if not ws.local_start <= int(n[len(ws.prefix):]) <= ws.local_end]
    if outside:
        logger.warning('注意：%d 个账号不在本机号段里（%s..）：如果另一台电脑在用它们，登录会把那边挤下线；'
                       '它们的数据库记录也不在这台电脑上。', len(outside), outside[0])
    windows = window_roles(game_window_titles(), set(names))
    if windows:
        logger.warning('%d 个游戏窗口开着这个号段的角色%s: %s', len(windows),
                       '，删除前会强制关掉' if ws.close_open_windows and not check_only else '（会被登录挤掉）',
                       ', '.join(f'{role}(pid={pid})' for pid, role, _ in windows))
    s = ws.delete
    logger.info('计划：%s，%d 个账号，%s；同时最多 %d 个窗口；每删一个角色登录一次（约 10 秒）', label, len(names),
                '只检测' if check_only else '删除全部角色', s.max_windows)
    if not names:
        return 0
    if not check_only and not yes:
        time.sleep(0.5)                 # let the console thread print the plan before the prompt
        if input(f'\n删除不能撤销（槽位约 {ws.release_hours:g} 小时后才释放）。确认删除请输入 {CONFIRM_WORD} 后回车: ').strip() \
                != CONFIRM_WORD:
            logger.info('没有确认，什么都没删')
            return 1
    if windows and ws.close_open_windows and not check_only:
        for pid, role, _ in windows:
            logger.info('强制关闭 %s 的窗口 pid=%d: %s', role, pid, '成功' if native.kill(pid) else '失败/已关')
        time.sleep(s.close_settle)

    accounts = [Account(n, ws.password) for n in names]
    s = replace(s, accounts=tuple(accounts))
    ws = replace(ws, delete=s)
    own = OwnWindows(s.max_windows, logger)
    throttle = LaunchThrottle.of(s)
    jobs = [AccountWipeJob(ws, a, check_only, own, throttle, station_ids) for a in accounts]
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=min(s.max_windows, len(jobs)), thread_name_prefix='wipe') as pool:
        results = list(pool.map(lambda j: j.run(), jobs))
    seconds = time.monotonic() - started
    report = write_report(log_path.with_suffix(''), results, ws, label, check_only, seconds, learn_candidates(results))
    logger.info('=' * 60)
    for res in results:
        logger.info('%-6s %s %s', res.account, ' '.join(f"{r['name']}:{r['result']}" for r in res.roles) or '（空）',
                    res.error)
    logger.info('完成，用时 %.1f 分钟。报告: %s', seconds / 60, report)
    return 0 if not any(r.error or any(x['result'] in ('失败', '没删到') for x in r.roles) for r in results) else 1


if __name__ == '__main__':
    sys.exit(main())
