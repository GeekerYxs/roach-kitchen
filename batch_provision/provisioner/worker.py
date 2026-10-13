"""One account's pipeline: login -> arm tap -> create roles -> (re-login and verify).

Each step logs its start, result and timing; any exception carries the step name.
"""
import hashlib
import time
from pathlib import Path

from . import native
from .log import for_account
from .login import LaunchThrottle, login, read_session  # noqa: F401  (LaunchThrottle re-exported)
from .memory import ProcessMemory
from .protocol import MAX_SLOTS, OP_CREATE_REPLY, TapReader, build_create, parse_create_reply
from .state import CREATED, EXISTS, FAILED, NO_SLOT, UNCERTAIN, AccountState


# 0x4003 result codes. 2 confirmed on mw105 (2026-10-12): account already had a role created by
# another tool, r1..r3 filled the rest, r4 got 2. On error the char_id field is garbage.
# 1 seen once (mw141r1, 2026-10-12): the create went out before the server's login data (0x4002)
# had arrived; the relogin roster proved nothing was created. Treated as "not ready": retried once.
RESULT_NOT_READY = 1
RESULT_SLOTS_FULL = 2
CREATE_RESULT = {RESULT_NOT_READY: '服务器未就绪（推测：登录数据还没处理完），稍后重试一次',
                 RESULT_SLOTS_FULL: '角色槽已满（账号里已有 4 个角色，可能有其他程序建的）'}
NOT_READY_RETRY_DELAY = 3.0
SLOTS_FULL = 'slots_full'
NOT_READY = 'not_ready'


class StepError(RuntimeError):
    pass


class AccountJob:
    _run_id = time.strftime('%Y%m%d_%H%M%S')  # same id for every account in this run

    def __init__(self, settings, account, root, throttle):
        self.s, self.account, self.throttle = settings, account, throttle
        self.runtime = Path(root) / 'runtime'
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.state = AccountState(Path(root) / 'state', account.name)
        self.log = for_account(account.name)
        self.roles = settings.role_names(account.name)
        self.session = None
        self.step = 'init'

    # ---------- public ----------
    def run(self):
        started = time.monotonic()
        summary = {'account': self.account.name, 'ok': False, 'step': None, 'error': None}
        if not self.s.keep_windows_open and all(self.state.is_done(r) for r in self.roles):
            self.log.info('%d 个角色记录均已创建，且不保留窗口，跳过本号', len(self.roles))
            summary.update(ok=True, skipped=True, roles={r: self.state.role(r).get('status') for r in self.roles},
                           pid=None, hwnd=None, seconds=0)
            return summary
        try:
            self._step('登录')
            self.session = self._login()
            self._step('挂网络观察')
            native.arm(self.session)
            reader = TapReader(self.runtime, self.session.pid)
            reader.poll()
            self._step('读取选角列表')
            context, roster = self._read_session()
            self._step('建角')
            self._create_roles(reader, context, roster)
            if self.s.relogin_after_create and any(self.state.role(r).get('status') == CREATED and
                                                   self.state.role(r).get('run') == self._run_id for r in self.roles):
                self._step('重登核验')
                self._relogin_and_verify()
            else:
                self.log.info('本次没有新建角色或未开启重登核验，保持当前选角界面')
            roles = {r: self.state.role(r).get('status') for r in self.roles}
            summary.update(ok=all(v in (CREATED, EXISTS) for v in roles.values()), roles=roles)
            if NO_SLOT in roles.values():
                summary['error'] = '角色槽被其他角色占用，部分角色没建'
            elif not summary['ok']:
                summary['error'] = '部分角色未建成，详见日志'
        except Exception as e:
            summary.update(step=self.step, error=f'{type(e).__name__}: {e}')
            self.log.exception('步骤「%s」失败: %s', self.step, e)
            self._on_failure()
            summary['roles'] = {r: self.state.role(r).get('status') for r in self.roles}
        summary['pid'] = self.session.pid if self.session else None
        summary['hwnd'] = self.session.hwnd if self.session else None
        if self.session and not self.s.keep_windows_open:
            try:
                self.log.info('关闭窗口 pid=%d 释放名额 (%s)', self.session.pid, native.close(self.session))
            except Exception as e:
                self.log.error('关闭窗口失败: %s', e)
        summary['seconds'] = round(time.monotonic() - started, 1)
        self.state.update(last_run=self._run_id, last_summary=summary)
        self.log.info('结束: ok=%s 角色=%s 用时 %.1fs%s', summary['ok'], summary.get('roles'), summary['seconds'],
                      f" 错误={summary['error']}" if summary['error'] else '')
        return summary

    # ---------- steps ----------
    def _step(self, name):
        self.step = name
        self.log.info('== %s ==', name)

    def _login(self):
        return login(self.s, self.account, self.runtime, self.throttle, self.log, self.s.kill_on_failure)

    def _read_session(self):
        return read_session(self.session, self.account.name, self.log, own_names=self.roles)

    def _create_roles(self, reader, context, roster):
        present = {name for _, _, name in roster}
        for role in self.roles:
            if role in present and not self.state.is_done(role):
                self.state.set_role(role, EXISTS, run=self._run_id)
            elif role not in present and self.state.is_done(role):
                self.log.warning('%s 本地记录为已创建，但服务器选角列表里没有，重新建', role)
        todo = [r for r in self.roles if r not in present]
        free = MAX_SLOTS - len(roster)
        if len(todo) > free:
            foreign = [name for _, _, name in roster if name not in self.roles]
            skipped = todo[free:]
            todo = todo[:free]
            self.log.error('空槽只有 %d 个，放不下 %s；占槽的其他角色: %s。这些角色不建，请手动处理后再运行',
                           free, skipped, foreign)
            for role in skipped:
                self.state.set_role(role, NO_SLOT, foreign_roles=foreign, run=self._run_id)
        if not todo:
            self.log.info('没有需要新建的角色')
            return
        sent = 0
        for role in todo:
            index = self.roles.index(role) + 1
            if sent:
                time.sleep(self.s.create_interval)
            if not native.alive(self.session.pid):
                raise StepError('游戏进程已退出')
            outcome = self._create_one(reader, context, role, index)
            if outcome == NOT_READY:
                # a definite rejection, so nothing was created; names are unique, so a retry cannot duplicate
                self.log.warning('%.0fs 后重试一次 %s', NOT_READY_RETRY_DELAY, role)
                time.sleep(NOT_READY_RETRY_DELAY)
                outcome = self._create_one(reader, context, role, index)
            sent += 1
            if outcome == SLOTS_FULL:
                self.log.error('%s 的角色槽已满（账号里有不是本工具建的角色），停止该账号后续建角', self.account.name)
                break
            if outcome == UNCERTAIN:
                self.log.error('%s 结果不确定，停止该账号后续建角，避免重复提交；下次运行会先扫描列表再决定', role)
                break

    def _create_one(self, reader, context, role, index):
        with ProcessMemory(self.session.pid, self.session.base) as mem:
            body = build_create(mem, context, self.account.name, role)
        digest = hashlib.sha256(body).hexdigest()[:16]
        self.log.info('[%d/%d] 发送建角请求 %s (0x0002, %d 字节, sha=%s)', index, len(self.roles), role, len(body), digest)
        native.send_create(self.session, body)
        sent_at = time.monotonic()
        deadline = sent_at + self.s.create_timeout
        while time.monotonic() < deadline:
            for opcode, payload in reader.poll():
                self.log.debug('收包 op=%#06x len=%d %s', opcode, len(payload), payload[:32].hex())
                if opcode != OP_CREATE_REPLY:
                    continue
                char_id, result = parse_create_reply(payload)
                ms = int((time.monotonic() - sent_at) * 1000)
                if result == 0 and char_id:
                    self.log.info('[%d/%d] %s 创建成功 角色ID=%d (%dms)', index, len(self.roles), role, char_id, ms)
                    self.state.set_role(role, CREATED, char_id=char_id, run=self._run_id, slot_index=index)
                    return CREATED
                reason = CREATE_RESULT.get(result, '未知错误码（请把这行发给开发）')
                self.log.error('[%d/%d] %s 服务器拒绝: result=%d %s raw=%s (%dms)',
                               index, len(self.roles), role, result, reason, payload.hex(), ms)
                self.state.set_role(role, FAILED, server_result=result, reason=reason, raw=payload.hex(),
                                    run=self._run_id)
                return {RESULT_SLOTS_FULL: SLOTS_FULL, RESULT_NOT_READY: NOT_READY}.get(result, FAILED)
            time.sleep(0.15)
        self.log.error('[%d/%d] %s 在 %.0fs 内没有收到 0x4003 回包', index, len(self.roles), role, self.s.create_timeout)
        self.state.set_role(role, UNCERTAIN, run=self._run_id)
        return UNCERTAIN

    def _relogin_and_verify(self):
        how = native.close(self.session)
        self.log.info('旧窗口已退出 (%s)，重新登录刷新选角列表', how)
        self.session = None
        self.session = self._login()
        _, roster = self._read_session()
        present = {name for _, _, name in roster}
        missing = [r for r in self.roles if r not in present]
        expected_missing = [r for r in missing if self.state.role(r).get('status') == CREATED]
        if expected_missing:
            self.log.error('重登核验失败: 服务器回包说已创建，但选角列表里没有 %s', expected_missing)
        else:
            self.log.info('重登核验通过: 本次创建的角色都在选角列表里')
        self.state.update(verified_roles=[r for r in self.roles if r in present],
                          roster=[{'id': i, 'level': lv, 'name': n} for i, lv, n in roster])

    def _on_failure(self):
        if self.session and self.s.kill_on_failure:
            self.log.warning('kill_on_failure=true，关闭 pid=%d', self.session.pid)
            native.kill(self.session.pid)
        elif self.session:
            self.log.warning('保留窗口 pid=%d hwnd=%#x 供排查', self.session.pid, self.session.hwnd)
