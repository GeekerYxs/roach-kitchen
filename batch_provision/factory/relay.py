"""Stage test 4+5 in a loop: the well leader trains alts batch after batch and the dispatcher sends them to
平静海岸2区 (map 81), until every configured role (e.g. mw09..mw100 slots 1..4) has landed there.

Entry: python -m factory.relay [relay.toml]
One batch = up to 4 alt windows that THIS tool opened (one role per account at a time). Per cycle:
  0. a well leader left with a team or outside the village (earlier run stopped) -> stage 4b finishes that first
  1. fill the batch: log in the next roles (distinct accounts, not done, not quarantined) and enter their slot
  2. per alt: novice map -> 新手出村; outside village/coast -> 飞鞋 / 回城卷 home; in the village below 11 ->
     eat 小肉林 (stage 1) and record 飞鞋 (stage 2)
  3. stage 4a (team at spawn + 地瓜) and 4b (well to 11, home) with the well leader
  4. stage 5 with the dispatcher (gold top-up, PP鸡 -> 81, dispatcher scrolls home)
  5. alts on 81 at level >= 11 are done: record state/relay/<account>_slot<N>.json, close the window; alts that
     are quarantined or made no progress for `max_cycles` cycles are recorded as failed and closed
The stage code is reused unchanged; it only ever sees this batch's alts, so other windows (coast leaders and
their alts, the user's own windows) are never touched. Stop with Ctrl+C: windows stay open, and the next start
adopts them (roles of the configured accounts in windows with our DLL) and continues from the observed state.
Decisions are pure (tests/test_factory_relay.py).
"""
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from provisioner import config, log, native, procs
from provisioner.enter import enter_role, verify_in_world
from provisioner.login import LaunchThrottle, login, read_session
from provisioner.memory import ProcessMemory
from provisioner.novice import NoviceJob, NoviceSettings
from provisioner.pipeline import OwnWindows, online_elsewhere, remember_roster
from provisioner.world import read_team, read_world

from . import db
from .config import load_settings
from .home import HomeJob
from .meat import MeatJob
from .observe import observe
from .phase import (COAST_MAP, DISPATCHER, NOVICE_MAP, QUEUE_TRANSPORT, QUEUE_WELL, TARGET_LEVEL, VILLAGE_MAP, WELL,
                    derive_phase)
from .shoe import ShoeJob
from .transport import TransportRun
from .welltrain import WellTrainRun
from .wellteam import WellTeamRun

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / 'state' / 'relay'
STATION_FAIL_LIMIT = 3      # this many cycles in a row with a station error -> stop, a human must look
LOGIN_FAIL_LIMIT = 4        # this many logins in a row failed -> count as a cycle error (do not burn the list)


# ---- pure decisions -------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Job:
    account: object         # provisioner.config.Account
    slot: int

    @property
    def key(self):
        return f'{self.account.name}#{self.slot}'


def jobs_in_order(accounts, slots):
    """Slot-major (every account's slot 1, then slot 2 ...): one account comes back only after all others."""
    return [Job(a, s) for s in slots for a in accounts]


def next_jobs(jobs, finished, open_accounts, room):
    """Up to `room` jobs not finished (done / failed / skipped this run) whose account has no open window,
    at most one per account."""
    out, taken = [], set(open_accounts)
    for j in jobs:
        if len(out) >= room:
            break
        if j.key in finished or j.account.name in taken:
            continue
        out.append(j)
        taken.add(j.account.name)
    return out


def outcome(obs, quarantined, stalled_cycles, max_cycles):
    """After a cycle: 'done' (landed on 81 at 11+) | 'failed' | 'keep' (next cycle goes on with it)."""
    if obs is not None and obs.map_id == COAST_MAP and obs.level >= TARGET_LEVEL:
        return 'done'
    if quarantined:
        return 'failed'
    if stalled_cycles >= max_cycles:
        return 'failed'
    return 'keep'


def progress_key(obs):
    """What counts as progress between two cycles."""
    return None if obs is None else (obs.map_id, obs.level)


# ---- settings -------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class RelaySettings:
    login: object           # provisioner.config.PipelineSettings ([game] [batch] [novice] [accounts])
    factory: object         # factory.config.Settings
    team_size: int
    max_cycles: int


def load_relay(path):
    data = config._read(path)
    r = data.get('relay', {})
    login_settings = config.load_pipeline(path)
    factory = load_settings(ROOT / r.get('factory', 'factory.toml'))
    size = min(login_settings.max_windows, factory.well_team_size, factory.transport_team_size)
    return RelaySettings(login_settings, factory, size, max(1, int(r.get('max_cycles', 3))))


# ---- state files ----------------------------------------------------------------------------------------

def state_path(account, slot):
    return STATE_DIR / f'{account}_slot{slot}.json'


def load_state(account, slot):
    p = state_path(account, slot)
    return json.loads(p.read_text('utf-8')) if p.is_file() else {}


def save_state(account, slot, result):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    p = state_path(account, slot)
    old = load_state(account, slot)
    history = old.get('history', []) + [{k: result.get(k) for k in ('ok', 'error', 'time')}]
    tmp = p.with_suffix('.tmp')
    tmp.write_text(json.dumps({**result, 'history': history[-20:]}, ensure_ascii=False, indent=2), 'utf-8')
    tmp.replace(p)


# ---- the run --------------------------------------------------------------------------------------------

@dataclass
class Alt:
    client: object          # procs.Client
    account: str
    slot: int
    stalled: int = 0
    last_progress: object = None

    @property
    def key(self):
        return f'{self.account}#{self.slot}'


class Relay:
    def __init__(self, s, logger):
        self.s, self.log = s, logger
        self.conn = db.connect(s.factory.db_path)
        self.own = OwnWindows(s.team_size, logger)
        self.throttle = LaunchThrottle.of(s.login)
        self.jobs = jobs_in_order(s.login.accounts, s.login.slots)
        self.wanted = {f'{j.account.name}r{j.slot}': j for j in self.jobs}     # role name -> job
        self.finished = set()       # job keys done / failed / skipped in this run
        self.batch = {}             # char_id -> Alt
        self.counts = {'done': 0, 'failed': 0, 'skipped': 0}
        self.station_fails = self.login_fails = 0
        self.quiet = logging.LoggerAdapter(logging.getLogger('prov.scan'), {'account': 'scan'})
        logging.getLogger('prov.scan').setLevel(logging.ERROR)

    # ---- windows
    def scan(self):
        return {c.char_id: c for c in procs.discover(self.quiet)}

    def adopt(self):
        """Windows with our DLL already showing one of the wanted roles (left by a stopped run)."""
        for c in self.scan().values():
            job = self.wanted.get(c.name)
            if job is None:
                continue
            if len(self.batch) >= self.s.team_size or any(a.account == job.account.name for a in self.batch.values()):
                self.log.warning('%s 已在窗口 pid=%d 在线，但本批已满/同账号已在批里，不接管', c.name, c.session.pid)
                self.finished.add(job.key)
                continue
            self.own.add(c.session)
            self.add(Alt(c, job.account.name, job.slot))
            self.log.info('接管已开的窗口 %s pid=%d 地图 %d', c.name, c.session.pid, c.map_id)

    def add(self, alt):
        c = alt.client
        db.register_alt(self.conn, c.char_id, alt.account, alt.slot, c.name, time.time())
        self.batch[c.char_id] = alt

    def close(self, alt, why):
        time.sleep(1.0)       # let the client finish the arrival before disconnecting
        self.own.close(alt.client.session, log.for_account(alt.client.name))
        self.batch.pop(alt.client.char_id, None)
        self.log.info('%s 关窗: %s', alt.client.name, why)

    # ---- 1: fill the batch
    def skip_reason(self, job):
        if load_state(job.account.name, job.slot).get('ok'):
            return '之前已传到平静海岸2区'
        row = self.conn.execute('SELECT name, quarantined, last_error FROM alts WHERE account=? AND slot=?',
                                (job.account.name, job.slot)).fetchone()
        if row and row['quarantined']:
            return f'已隔离（{row["last_error"]}），解除隔离后才会再做'
        return None

    def fill(self):
        while len(self.batch) < self.s.team_size:
            room = self.s.team_size - len(self.batch)
            jobs = next_jobs(self.jobs, self.finished, {a.account for a in self.batch.values()}, room)
            if not jobs:
                return
            todo = []
            for j in jobs:
                why = self.skip_reason(j)
                if why:
                    self.finished.add(j.key)
                    self.counts['skipped'] += 1
                    self.log.info('跳过 %s: %s', j.key, why)
                else:
                    todo.append(j)
            if not todo:
                continue
            with ThreadPoolExecutor(max_workers=len(todo), thread_name_prefix='login') as pool:
                opened = list(pool.map(self.open_role, todo))
            for j, alt in zip(todo, opened):
                if alt is None:
                    self.finished.add(j.key)
                    self.counts['failed'] += 1
                    self.login_fails += 1
                    continue
                self.login_fails = 0
                if alt == 'done':
                    self.finished.add(j.key)
                    self.counts['done'] += 1
                else:
                    self.add(alt)
            if self.login_fails >= LOGIN_FAIL_LIMIT:
                self.login_fails = 0
                raise RuntimeError(f'连续 {LOGIN_FAIL_LIMIT} 个角色登录/进入失败（服务器或网络问题？）')

    def open_role(self, job):
        """Log in and enter the slot. -> Alt | 'done' (already on 81) | None (failed, recorded)."""
        lg = log.for_account(job.key)
        session, result = None, {'account': job.account.name, 'slot': job.slot, 'ok': False}
        try:
            elsewhere = online_elsewhere(job.account.name, self.own)
            if elsewhere:
                raise RuntimeError(f'该账号的角色正在其他窗口在线（{elsewhere}），为避免挤号，跳过')
            session = login(self.s.login, job.account, ROOT / 'runtime', self.throttle, lg, kill_on_failure=True)
            self.own.add(session)
            _, roster = read_session(session, job.account.name, lg)
            remember_roster(job.account.name, roster)
            if job.slot > len(roster):
                raise RuntimeError(f'槽{job.slot} 没有角色（这个号只有 {len(roster)} 个角色）')
            char_id, _, name = roster[job.slot - 1]
            enter_role(session, job.slot, self.s.login.enter_timeout, lg)
            world = verify_in_world(session, char_id, name, lg)
            client = procs.Client(session, char_id, name, world.map_id, world.x, world.y)
            if world.map_id == COAST_MAP:
                with ProcessMemory(session.pid, session.base) as mem:
                    obs = observe(mem, read_world(mem))
                if obs is not None and obs.level >= TARGET_LEVEL:
                    self.finish(Alt(client, job.account.name, job.slot), obs, True, '登录时已在平静海岸2区')
                    return 'done'
            return Alt(client, job.account.name, job.slot)
        except Exception as e:
            result.update(error=f'{type(e).__name__}: {e}', time=time.strftime('%Y-%m-%d %H:%M:%S'))
            lg.error('登录/进入失败: %s', e, exc_info=not isinstance(e, RuntimeError))
            save_state(job.account.name, job.slot, result)
            if session:
                self.own.close(session, lg)
            return None

    # ---- 2: per-alt preparation
    def prepare(self, alt):
        lg = log.for_account(alt.client.name)
        try:
            self._prepare(alt, lg)
        except Exception as e:
            lg.error('准备失败: %s', e, exc_info=not isinstance(e, RuntimeError))

    def _prepare(self, alt, lg):
        c = alt.client
        w = self.reread(c)
        if w is None:
            return
        if w.map_id == NOVICE_MAP:
            n = self.s.login
            r = NoviceJob(c, NoviceSettings(n.escape_action, n.novice_timeout, n.tick), lg).run()
            if not r['ok']:
                lg.error('新手出村失败: %s', r.get('error'))
                return
            w = self.reread(c)
        if w and w.map_id not in (VILLAGE_MAP, COAST_MAP):
            self.go_home(alt, lg)
            w = self.reread(c)
        if w is None or w.map_id != VILLAGE_MAP:
            return
        with ProcessMemory(c.session.pid, c.session.base) as mem:
            obs = observe(mem, w)
        if obs is None or obs.level >= TARGET_LEVEL:
            return
        for job in (MeatJob, ShoeJob):
            r = job(c, alt.account, alt.slot, self.s.factory, lg).run()
            if not r['ok']:
                lg.error('%s 失败: %s', '吃小肉林' if job is MeatJob else '记录飞鞋', r.get('error'))
                return

    def conn_for_thread(self):
        return db.connect(self.s.factory.db_path)

    @staticmethod
    def reread(c):
        with ProcessMemory(c.session.pid, c.session.base) as mem:
            return read_world(mem)

    def go_home(self, alt, lg):
        """Lost outside village/coast (e.g. relogged in the meadow): 飞鞋 if allowed, else 回城卷."""
        r = HomeJob(alt.client, self.s.factory, lg).run()
        if not r['ok']:
            lg.error('%s', r['error'])
            if not r['error'].startswith('回村 '):          # 'stuck' (no way home) counts as a failure
                conn = self.conn_for_thread()
                try:
                    db.record_failure(conn, alt.client.char_id, r['error'], time.time())
                finally:
                    conn.close()

    # ---- 3/4: stations
    def station(self, role):
        rows = self.conn.execute('SELECT * FROM stations WHERE role=?', (role,)).fetchall()
        if len(rows) != 1:
            raise RuntimeError(f'数据库里 {role} 工位应正好 1 个，实际 {len(rows)} 个；先运行 一键登录工位.cmd')
        return rows[0]

    def alts_arg(self):
        return {cid: (a.client, a.account, a.slot) for cid, a in self.batch.items()
                if native.alive(a.client.session.pid)}

    def run_station(self, cls, role, label):
        st = self.station(role)
        leader = self.scan().get(st['char_id'])
        if leader is None:
            raise RuntimeError(f'{label} {st["name"]} (ID={st["char_id"]}) 不在本工具的窗口里在线；先运行 一键登录工位.cmd')
        lg = log.for_account(label)
        with ProcessMemory(leader.session.pid, leader.session.base) as mem:
            run = cls(self.conn, st, leader, mem, self.alts_arg(), self.s.factory, lg)
            try:
                results = run.run()
            finally:
                run.close()
        for r in results:
            lg.info('%-8s %s %s', r['name'], '成功' if r['ok'] else '失败', r.get('error') or '')
        return results

    def leader_busy(self):
        """Well leader outside the village or still leading a team (an earlier run stopped mid-batch)."""
        st = self.station(WELL)
        leader = self.scan().get(st['char_id'])
        if leader is None:
            return False
        with ProcessMemory(leader.session.pid, leader.session.base) as mem:
            w, team = read_world(mem), read_team(mem)
        return bool(w and (w.map_id != VILLAGE_MAP or (team and len(team.members) > 1)))

    def phases(self):
        """Observe the batch and save each alt's phase. -> {char_id: (obs, phase)}"""
        roles, out = db.station_roles(self.conn), {}
        for cid, a in self.batch.items():
            if not native.alive(a.client.session.pid):
                out[cid] = (None, None)
                continue
            with ProcessMemory(a.client.session.pid, a.client.session.base) as mem:
                obs = observe(mem, read_world(mem))
            if obs is None:
                out[cid] = (None, None)
                continue
            plan = derive_phase(obs, db.ledger(self.conn, cid), roles)
            db.save_observation(self.conn, obs, plan, time.time())
            out[cid] = (obs, plan.phase)
        return out

    # ---- 5: results
    def finish(self, alt, obs, ok, why):
        save_state(alt.account, alt.slot, {'account': alt.account, 'slot': alt.slot, 'ok': ok, 'name': alt.client.name,
                                           'char_id': alt.client.char_id, 'map': obs.map_id if obs else None,
                                           'level': obs.level if obs else None, 'gold': obs.gold if obs else None,
                                           'error': None if ok else why, 'time': time.strftime('%Y-%m-%d %H:%M:%S')})
        self.close(alt, why)

    def settle(self):
        observed = self.phases()
        for cid, alt in list(self.batch.items()):
            obs, phase = observed.get(cid, (None, None))
            key = progress_key(obs)
            alt.stalled = alt.stalled + 1 if key == alt.last_progress else 0
            alt.last_progress = key
            row = db.alt(self.conn, cid)
            verdict = outcome(obs, bool(row and row['quarantined']), alt.stalled, self.s.max_cycles)
            if obs is None and not native.alive(alt.client.session.pid):
                verdict = 'failed'
            if verdict == 'done':
                self.counts['done'] += 1
                self.finished.add(alt.key)
                self.finish(alt, obs, True, f'已到平静海岸2区（{obs.level} 级，金币 {obs.gold}）')
            elif verdict == 'failed':
                self.counts['failed'] += 1
                self.finished.add(alt.key)
                why = (row['last_error'] if row and row['quarantined'] else
                       f'连续 {alt.stalled} 轮没有进展，阶段 {phase}')
                self.finish(alt, obs, False, why or '进程已退出')
            else:
                self.log.info('%s 留到下一轮: 阶段 %s', alt.client.name, phase)

    # ---- the loop
    def cycle(self, n):
        self.log.info('=' * 20 + ' 第 %d 轮 ' + '=' * 20, n)
        if self.leader_busy():
            self.log.info('古井队长还带着上次的队伍/不在村里，先把上一批练完回村')
            self.run_station(WellTrainRun, WELL, '古井队长')
        self.fill()
        if not self.batch:
            return False
        self.log.info('本批: %s', ', '.join(a.client.name for a in self.batch.values()))
        with ThreadPoolExecutor(max_workers=len(self.batch), thread_name_prefix='prep') as pool:
            list(pool.map(self.prepare, list(self.batch.values())))
        phases = self.phases()
        if any(p == QUEUE_WELL for _, p in phases.values()):
            self.run_station(WellTeamRun, WELL, '古井队长')
            self.run_station(WellTrainRun, WELL, '古井队长')
            phases = self.phases()
        disp = self.station(DISPATCHER)
        disp_client = self.scan().get(disp['char_id'])
        disp_away = disp_client is not None and disp_client.map_id == COAST_MAP
        if disp_away or any(p == QUEUE_TRANSPORT for _, p in phases.values()):
            self.run_station(TransportRun, DISPATCHER, '调度员')
        self.settle()
        return True

    def run(self):
        self.adopt()
        total = len(self.jobs)
        self.log.info('目标 %d 个角色（%s 号 %d 个账号 × 槽 %s），每批最多 %d 个', total,
                      f'{self.s.login.accounts[0].name}..{self.s.login.accounts[-1].name}', len(self.s.login.accounts),
                      list(self.s.login.slots), self.s.team_size)
        n, started = 0, time.monotonic()
        while True:
            n += 1
            batch_started = time.monotonic()
            try:
                if not self.cycle(n):
                    break
                self.station_fails = 0
            except RuntimeError as e:
                self.station_fails += 1
                self.log.error('第 %d 轮出错（连续 %d 次）: %s', n, self.station_fails, e)
                if self.station_fails >= STATION_FAIL_LIMIT:
                    self.log.error('连续 %d 轮出错，停止。窗口保留，处理后重新运行会接着做', self.station_fails)
                    return 1
                time.sleep(5)
                continue
            c = self.counts
            self.log.info('第 %d 轮用时 %.0fs。累计 完成 %d 失败 %d 跳过 %d，剩余 %d；已运行 %.1f 分钟', n,
                          time.monotonic() - batch_started, c['done'], c['failed'], c['skipped'],
                          total - len(self.finished), (time.monotonic() - started) / 60)
        c = self.counts
        self.log.info('全部结束: 完成 %d 失败 %d 跳过 %d，用时 %.1f 分钟。逐个结果在 %s', c['done'], c['failed'],
                      c['skipped'], (time.monotonic() - started) / 60, STATE_DIR)
        return 0 if not c['failed'] else 1


def main():
    cfg = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'relay.toml'
    log_path = log.setup(ROOT / 'logs', prefix='relay')
    logger = log.for_account('main')
    logger.info('日志文件: %s', log_path)
    try:
        s = load_relay(cfg)
    except Exception as e:
        logger.error('配置错误 (%s): %s', cfg, e)
        return 2
    relay = Relay(s, logger)
    try:
        return relay.run()
    except KeyboardInterrupt:
        logger.warning('已手动停止。本工具开的窗口保留，重新运行会接管它们接着做')
        return 130


if __name__ == '__main__':
    sys.exit(main())
