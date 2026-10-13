"""Stage 11e: rebuild roles in the slots that deleted roles freed (~3 h after the delete, user 2026-10-12).

Run by the supervisor's account worker (factory/supervisor.py), one account at a time, only while that account has
no window open. One login on the selection screen (the same login every tool uses):
  1. read the server's role list; free slots = 4 - roles listed
  2. names = rebuild_names(): the deleted roles' successors (mw01r1 -> mw01r5, user 2026-10-13), oldest deletion
     first, at most one per free slot, skipping successors that exist already
  3. per name: build 0x0002 from this client's session (stage "建角", provisioner/protocol.py), DLL command 103 sends
     it, wait 0x4003 <id, result>; result 1 (server not ready) is retried once, result 2 (slots full) = the slot is
     not released yet; no reply = unknown, stop (names are unique, the next try re-reads the list first)
  4. each created role -> factory.db (phase novice: a new role starts in 菜鸟训练营), so the supervisor pulls it
     like any fresh role; a successor found in the list but missing from factory.db (crash after creating) is
     registered the same way
  5. close the window
"""
import time

from provisioner import log, native
from provisioner.login import login, read_session
from provisioner.memory import ProcessMemory
from provisioner.pipeline import remember_roster
from provisioner.protocol import MAX_SLOTS, OP_CREATE_REPLY, TapReader, build_create, parse_create_reply

from . import db
from .config import ROOT
from .phase import NOVICE
from .runner import ROLE_NAME
from .schedule import rebuild_names, successor

CREATE_TIMEOUT = 15.0
NOT_READY_RETRY = 3.0
RESULT_NOT_READY, RESULT_SLOTS_FULL = 1, 2       # 0x4003 result codes (provisioner/worker.py, live 2026-10-12)
CREATED, REFUSED, NO_REPLY = 'created', 'refused', 'no_reply'


def register_new(conn, char_id, account, name, now):
    """A role we just created: known to factory.db and queued as a fresh role (phase novice until observed)."""
    db.register_alt(conn, char_id, account, int(ROLE_NAME.match(name)[2]), name, now)
    conn.execute("UPDATE alts SET phase=?, phase_since=?, reason=? WHERE char_id=? AND phase='unknown'",
                 (NOVICE, now, '重建的新角色，在菜鸟训练营', char_id))
    db.log_event(conn, now, 'rebuild', f'重建角色 {name} ID={char_id}', char_id=char_id)


class RebuildJob:
    def __init__(self, settings, account, deleted, known_names, own, throttle, db_path):
        """settings: launch settings (factory.delete.DeleteSettings); deleted: this account's deleted role names,
        oldest deletion first; known_names: every role name factory.db knows."""
        self.s, self.account, self.deleted, self.known = settings, account, deleted, set(known_names)
        self.own, self.throttle, self.db_path = own, throttle, db_path
        self.log = log.for_account(account.name)
        self.runtime = ROOT / 'runtime'

    def run(self):
        """-> {'created': [names], 'free': free slots seen or None, 'error': str or None, 'not_released': bool}"""
        result = {'created': [], 'free': None, 'error': None, 'not_released': False}
        conn = db.connect(self.db_path)
        session = None
        try:
            self.log.info('== 登录到选角界面，看有没有释放的槽位（已删除: %s）==', ', '.join(self.deleted))
            session = login(self.s, self.account, self.runtime, self.throttle, self.log)
            self.own.add(session)
            native.arm(session)
            reader = TapReader(self.runtime, session.pid)
            reader.poll()
            context, roster = read_session(session, self.account.name, self.log)
            remember_roster(self.account.name, roster)
            listed = {name: cid for cid, _, name in roster}
            self._adopt_orphans(conn, listed)
            free = MAX_SLOTS - len(roster)
            result['free'] = free
            names = rebuild_names(self.deleted, set(listed) | self.known, free)
            self.log.info('选角列表 %d 个角色，空槽 %d 个；要建: %s', len(roster), free, names or '无')
            if not names:
                result['not_released'] = free == 0
                return result
            for i, name in enumerate(names):
                if i:
                    time.sleep(1.0)
                kind, value = self._create(session, reader, context, name)
                if kind == REFUSED and value == RESULT_NOT_READY:
                    # a definite rejection, nothing was created; names are unique, so a retry cannot duplicate
                    self.log.warning('服务器未就绪，%.0fs 后重试一次 %s', NOT_READY_RETRY, name)
                    time.sleep(NOT_READY_RETRY)
                    kind, value = self._create(session, reader, context, name)
                if kind == CREATED:
                    register_new(conn, value, self.account.name, name, time.time())
                    result['created'].append(name)
                    continue
                if kind == REFUSED and value == RESULT_SLOTS_FULL:
                    result['not_released'] = True
                    self.log.warning('%s: 服务器说角色槽已满（删除的槽位还没释放），稍后再来', name)
                elif kind == NO_REPLY:
                    result['error'] = f'{name} 在 {CREATE_TIMEOUT:.0f}s 内没有收到 0x4003，结果不明（下次先看选角列表）'
                    self.log.error('%s', result['error'])
                else:
                    result['error'] = f'{name} 服务器拒绝建角 result={value}'
                    self.log.error('%s', result['error'])
                break
        except Exception as e:
            result['error'] = f'{type(e).__name__}: {e}'
            self.log.error('重建失败: %s', e, exc_info=not isinstance(e, RuntimeError))
        finally:
            if session is not None:
                self.own.close(session, self.log)
            conn.close()
        return result

    def _adopt_orphans(self, conn, listed):
        """Successors in the server's list that factory.db does not know (crash right after creating)."""
        for name in self.deleted:
            new = successor(name)
            if new in listed and new not in self.known:
                self.log.warning('%s 已在选角列表里（ID=%d）但数据库没有，补登记', new, listed[new])
                register_new(conn, listed[new], self.account.name, new, time.time())
                self.known.add(new)

    def _create(self, session, reader, context, name):
        """-> (CREATED, char_id) | (REFUSED, result code) | (NO_REPLY, None)."""
        with ProcessMemory(session.pid, session.base) as mem:
            body = build_create(mem, context, self.account.name, name)
        self.log.info('发送建角请求 %s (0x0002, %d 字节)', name, len(body))
        native.send_create(session, body)
        sent = time.monotonic()
        while time.monotonic() - sent < CREATE_TIMEOUT:
            if not native.alive(session.pid):
                raise RuntimeError('游戏进程在建角时退出')
            for opcode, payload in reader.poll():
                if opcode != OP_CREATE_REPLY:
                    continue
                char_id, code = parse_create_reply(payload)
                ms = int((time.monotonic() - sent) * 1000)
                if code == 0 and char_id:
                    self.log.info('%s 创建成功 角色ID=%d (%dms)', name, char_id, ms)
                    return CREATED, char_id
                self.log.warning('%s 服务器回 result=%d raw=%s (%dms)', name, code, payload.hex(), ms)
                return REFUSED, code
            time.sleep(0.15)
        return NO_REPLY, None
