"""Stage 10: delete every alt that finished its job (phase delete), then close its window.

Entry: python -m factory.delete [delete.toml]
User decision (2026-10-12): this stage does NOT pick what a window does next. Delete, record the time, close;
the supervisor (stage 11) pulls the next role (any account, any slot) when a queue runs short.

Per alt (accounts in parallel, the roles of one account one after another):
  1. gate (pure, refuses on any doubt; deleting cannot be undone): phase delete, not quarantined, last observation
     says quest 78 done and no 料理 in the bag, stage 9 logged the 料理 reaching the receiver, and no earlier delete
     of it is unresolved
  2. its game window still open -> observe once more (must still be phase delete), close it
  3. any other window shows a role of the same account -> skip the account (a login would kick that role)
  4. fresh login that stops on the selection screen (the same login every tool uses), arm the DLL tap
  5. find the role in the server's list BY ID and check its name; the entry's +0x60 must be 0 (otherwise the client
     would ask for an extra string we do not have)
  6. build 0x0003 from this client's own session (layout of the client's builder RVA 0xF4120, see protocol.py),
     mark pending, DLL command 107 sends it with the client's own send function, wait for 0x4004
  7. result 0 -> phase deleted + time; the raw list entry before/after is logged (to learn the "deleting" field);
     another result -> not deleted, count a failure; no reply -> leave the pending mark: the next run does NOT
     send again, a human checks the selection screen (old runbook rule: never repeat an unknown delete)
  8. close the window
Decisions are pure (tests/test_factory_delete.py).
"""
import json
import struct
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from provisioner import config, log, native, procs
from provisioner.login import LaunchThrottle, login, read_session
from provisioner.memory import ProcessMemory
from provisioner.pipeline import OwnWindows, online_elsewhere
from provisioner.protocol import (OP_DELETE_REPLY, ROSTER_PROTECT, TapReader, build_delete, parse_delete_reply,
                                  read_roster_raw)
from provisioner.world import read_world

from . import db
from .config import load_settings
from .observe import observe
from .phase import DELETE, QUEST_DONE, derive_phase

ROOT = Path(__file__).resolve().parent.parent
ACTION = 'delete_role'
CONNECTION = 0x150          # session context +0x150: the connection the client's builder sends on
BUSY = 0x148                # session context +0x148: the client's own "delete in progress" flag
MANAGER = 0x64B1B8          # [base+0x64B1B8]: the connection DLL commands 103/107 send on


class Refused(Exception):
    """A check said "do not delete": nothing was sent and it is not counted as a failure."""


# ---- pure decisions -------------------------------------------------------------------------------------

def gate(row, obs, got_dish):
    """None = may delete; otherwise why not. row: alts row (mapping); obs: last AltObs or None;
    got_dish: stage 9 verified this alt's 料理 at the receiver."""
    if row['quarantined']:
        return f'已隔离: {row["last_error"]}'
    if row['pending_action'] == ACTION:
        return '上次删除没收到服务器回包，结果不明：不重发，请人工看选角界面后处理'
    if row['phase'] != DELETE:
        return f'阶段是 {row["phase"]}，不是 {DELETE}'
    if obs is None:
        return '没有观察记录'
    if obs.quest != QUEST_DONE:
        return f'任务 78 状态是 {obs.quest}，不是已完成'
    if obs.dishes:
        return f'背包里还有料理 {obs.dishes} 个'
    if not got_dish:
        return '没有收货人收到料理的记录'
    return None


def find_entry(roster, char_id, name):
    """roster: [(char_id, level, name)]. -> (index or None, problem or None). Missing = already gone."""
    for i, (cid, _, n) in enumerate(roster):
        if cid == char_id:
            return (i, None) if n == name else (i, f'ID {char_id} 的名字是 {n}，不是 {name}')
    return None, None


def entry_diff(before, after):
    """Offsets whose byte changed between two raw roster entries -> [(offset, old, new)]."""
    return [(i, a, b) for i, (a, b) in enumerate(zip(before, after)) if a != b]


def reply_outcome(result):
    return 'deleted' if result == 0 else 'rejected'


# ---- settings -------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class DeleteSettings:
    game_exe: Path
    server_index: int
    launch_interval: float
    inject_delay_ms: int
    login_retries: int
    min_free_memory_mb: int
    kill_on_failure: bool
    accounts: tuple
    max_windows: int
    max_roles: int              # 0 = every alt in phase delete
    reply_timeout: float
    close_settle: float
    close_timeout: float
    factory: object             # factory.config.Settings


def load_delete(path):
    data = config._read(path)
    d = data.get('delete', {})
    common = config._launch_common(data)
    return DeleteSettings(**common, max_windows=max(1, int(data['batch'].get('max_windows', 4))),
                          max_roles=max(0, int(d.get('max_roles', 0))),
                          reply_timeout=float(d.get('reply_timeout', 15)),
                          close_settle=float(d.get('close_settle', 3)),
                          close_timeout=float(d.get('close_timeout', 3)),
                          factory=load_settings(ROOT / d.get('factory', 'factory.toml')))


# ---- one account ----------------------------------------------------------------------------------------

class AccountDeleteJob:
    """Deletes the given alts of ONE account, one login each (the DLL allows one delete per process)."""

    def __init__(self, s, account, rows, open_clients, own, throttle, conn_path):
        self.s, self.account, self.rows, self.open, self.own = s, account, rows, open_clients, own
        self.throttle, self.conn_path = throttle, conn_path
        self.log = log.for_account(account.name)
        self.runtime = ROOT / 'runtime'
        self.runtime.mkdir(parents=True, exist_ok=True)

    def run(self):
        conn = db.connect(self.conn_path)
        try:
            return [self._one(conn, row) for row in self.rows]
        finally:
            conn.close()

    def _one(self, conn, row):
        cid, name = row['char_id'], row['name']
        result = {'name': name, 'char_id': cid, 'ok': False}
        started = time.monotonic()
        session = None
        try:
            client = self.open.get(cid)
            if client is not None:
                self._observe_and_close(conn, client)
            row = db.alt(conn, cid)
            why = gate(row, db.last_observation(conn, cid), db.received(conn, cid))
            if why:
                result['error'] = f'不删: {why}'
                self.log.warning('%s 不删: %s', name, why)
                return result
            busy = online_elsewhere(self.account.name, self.own)
            if busy:
                result['error'] = f'不删: 同账号的角色在别的窗口在线 ({busy})，登录会把它顶掉'
                self.log.warning('%s %s', name, result['error'])
                return result
            self.log.info('== 登录到选角界面，删除 %s (ID=%d) ==', name, cid)
            session = login(self.s, self.account, self.runtime, self.throttle, self.log)
            self.own.add(session)
            native.arm(session)
            reader = TapReader(self.runtime, session.pid)
            reader.poll()
            context, roster = read_session(session, self.account.name, self.log)
            result.update(self.delete_listed(conn, session, reader, context, roster, cid, name))
        except Refused as e:
            result['error'] = f'不删: {e}'
            self.log.warning('%s 不删: %s', name, e)
        except Exception as e:
            result['error'] = f'{type(e).__name__}: {e}'
            self.log.error('%s 失败: %s', name, e, exc_info=not isinstance(e, RuntimeError))
            if db.alt(conn, cid)['pending_action'] != ACTION:
                db.record_failure(conn, cid, result['error'], time.time())
        finally:
            if session is not None:
                self.own.close(session, self.log)
        result['seconds'] = round(time.monotonic() - started, 1)
        return result

    def _observe_and_close(self, conn, client):
        """The alt's own window is still open: one last read, then close it so the account can log in."""
        with ProcessMemory(client.session.pid, client.session.base) as mem:
            obs = observe(mem, read_world(mem))
        if obs is not None and obs.char_id == client.char_id:
            plan = derive_phase(obs, db.ledger(conn, client.char_id), db.station_roles(conn))
            db.save_observation(conn, obs, plan, time.time())
            self.log.info('%s 窗口还开着：阶段=%s（%s）', client.name, plan.phase, plan.reason)
            if plan.phase != DELETE:
                raise Refused(f'最新观察阶段是 {plan.phase}，窗口保留')
        else:
            raise Refused('窗口里读不到这个角色，窗口保留')
        # In the world the client ignores WM_CLOSE (8/8 terminated after 15 s, 2026-10-12): wait only briefly.
        self.log.info('关闭 %s 的游戏窗口 pid=%d (%s)，%.0f 秒后重新登录', client.name, client.session.pid,
                      native.close(client.session, timeout=self.s.close_timeout), self.s.close_settle)
        time.sleep(self.s.close_settle)

    def delete_listed(self, conn, session, reader, context, roster, cid, name):
        """Delete one role from the selection screen this session shows (also used by factory/wipe.py)."""
        index, problem = find_entry(roster, cid, name)
        if problem:
            raise RuntimeError(problem)
        if index is None:
            # Not in the server's list at all: an earlier delete went through and the slot was released already.
            db.mark_deleted(conn, cid, time.time(), None)
            self.log.warning('%s 已不在选角列表里（之前删过且槽位已释放），记为已删除', name)
            return {'ok': True, 'skipped': True}
        with ProcessMemory(session.pid, session.base) as mem:
            before = read_roster_raw(mem, context)[index]
            self.log.info('选角列表第 %d 项原始数据（删除前）: %s', index + 1, before.hex())
            protect = struct.unpack_from('<I', before, ROSTER_PROTECT)[0]
            if protect:
                raise RuntimeError(f'列表项 +0x60 = {protect:#x}（客户端删除时会要求额外输入），不删')
            if mem.u32(context + BUSY):
                raise RuntimeError('客户端自己的删除标志已置位（界面正在删除？），不删')
            connection, manager = mem.u32(context + CONNECTION), mem.u32(session.base + MANAGER)
            if connection != manager:
                raise RuntimeError(f'会话连接 {connection:#x} 和 DLL 发送用的连接 {manager:#x} 不一致，不删')
            body = build_delete(mem, context, self.account.name, cid)
        db.mark_pending(conn, cid, ACTION, time.time())
        try:
            native.send_delete(session, body)
        except Exception as e:
            db.clear_pending(conn, cid, time.time(), f'DLL 没有发出删除请求: {e}')
            raise RuntimeError(f'删除请求没发出: {e}') from e
        sent = time.monotonic()
        self.log.info('已发送删除请求 0x0003 (%d 字节)，等服务器 0x4004', len(body))
        reply = self._wait_reply(reader, sent)
        if reply is None:
            db.log_event(conn, time.time(), 'delete_unknown', f'{self.s.reply_timeout:.0f}s 内没有 0x4004', char_id=cid)
            raise RuntimeError(f'{self.s.reply_timeout:.0f}s 内没收到 0x4004：结果不明，不重发，请人工看选角界面')
        code, release_ms = reply
        ms = int((time.monotonic() - sent) * 1000)
        if reply_outcome(code) != 'deleted':
            db.clear_pending(conn, cid, time.time(), f'服务器拒绝删除 result={code}')
            raise RuntimeError(f'服务器拒绝删除: result={code} ({ms}ms)')
        db.mark_deleted(conn, cid, time.time(), release_ms)
        self.log.info('服务器接受删除 (%dms)，报告 %.1f 小时后释放（实际约 3 小时）', ms, release_ms / 3.6e6)
        time.sleep(1.0)
        with ProcessMemory(session.pid, session.base) as mem:
            rows = read_roster_raw(mem, context)
        after = rows[index] if index < len(rows) else b''
        changes = entry_diff(before, after)
        self.log.info('选角列表第 %d 项原始数据（删除后）: %s', index + 1, after.hex())
        self.log.info('删除前后变化的字节: %s', ', '.join(f'+{o:#x}: {a:02x}->{b:02x}' for o, a, b in changes) or '无')
        return {'ok': True, 'release_ms': release_ms, 'reply_ms': ms,
                'entry_changes': [[o, a, b] for o, a, b in changes]}

    def _wait_reply(self, reader, sent):
        while time.monotonic() - sent < self.s.reply_timeout:
            for opcode, payload in reader.poll():
                if opcode == OP_DELETE_REPLY:
                    self.log.info('收到 0x4004: %s', payload.hex())
                    return parse_delete_reply(payload)
            time.sleep(0.15)
        return None


# ---- the run --------------------------------------------------------------------------------------------

def main():
    cfg = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'delete.toml'
    log_path = log.setup(ROOT / 'logs', prefix='delete')
    logger = log.for_account('main')
    logger.info('日志文件: %s', log_path)
    try:
        s = load_delete(cfg)
    except Exception as e:
        logger.error('配置错误 (%s): %s', cfg, e)
        return 2
    conn = db.connect(s.factory.db_path)
    accounts = {a.name: a for a in s.accounts}
    rows = [r for r in conn.execute('SELECT * FROM alts WHERE phase=? AND quarantined=0 ORDER BY account, slot',
                                    (DELETE,)).fetchall()]
    conn.close()
    unknown = sorted({r['account'] for r in rows} - set(accounts))
    if unknown:
        logger.warning('这些账号不在 delete.toml 的 [accounts] 里（没有密码），跳过: %s', ', '.join(unknown))
    rows = [r for r in rows if r['account'] in accounts]
    if s.max_roles:
        rows = rows[:s.max_roles]
    if not rows:
        logger.info('没有阶段为 %s 的小号', DELETE)
        return 0
    logger.info('本次删除 %d 个: %s', len(rows), ', '.join(r['name'] for r in rows))
    by_account = {}
    for r in rows:
        by_account.setdefault(r['account'], []).append(r)
    open_clients = {c.char_id: c for c in procs.discover(logger)}
    own = OwnWindows(s.max_windows, logger)
    throttle = LaunchThrottle(s.launch_interval, s.min_free_memory_mb)
    jobs = [AccountDeleteJob(s, accounts[a], rs, open_clients, own, throttle, s.factory.db_path)
            for a, rs in by_account.items()]
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=min(s.max_windows, len(jobs)), thread_name_prefix='delete') as pool:
        results = [r for rs in pool.map(lambda j: j.run(), jobs) for r in rs]
    out = ROOT / 'logs' / (log_path.stem.replace('delete_', 'delete_summary_') + '.json')
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), 'utf-8')
    logger.info('=' * 60)
    for r in results:
        logger.info('%-8s %s %s', r['name'], '已删除' if r['ok'] else '失败', r.get('error', ''))
    ok = sum(r['ok'] for r in results)
    logger.info('完成 %d/%d，总用时 %.1fs。汇总: %s', ok, len(results), time.monotonic() - started, out)
    return 0 if ok == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
