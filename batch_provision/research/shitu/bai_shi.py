"""拜师 / 收徒: the master takes apprentices one after another at 糊涂博士 (npc 341, map 1).

    python -X utf8 research/shitu/bai_shi.py [--master 伏地魔1] 十万2 十万3

Protocol (recorded 2026-10-27 00:29, 伏地魔1 took 十万1 by hand, see ANALYSIS.md section 10):
  master invites the apprentice (0x30, master = leader), apprentice accepts -> master ClickNpc(341) -> 结为师徒 ->
  rules page「结为师徒关系有以下要求…确定要结为师徒关系吗？」-> 确定 -> the apprentice gets
  0x4338 <I apprentice's own char><master name GBK, 17 bytes> (the client's yes/no popup) -> apprentice answers 0x0197 <I 0><u8 1> -> both get 0x4337, the apprentice 0x4041
  title「<master>的徒弟」-> master leaves the team.
The relation is not found in client memory, so «already done» comes from STATE (state.json, written here) or from
the server refusing the 确定 (its words are logged; an unknown refusal stops the run).
No UI clicks: team / dialog = game functions (DLL command 106), 0x0197 through the client's sender.
"""
import json
import sys
import time

import trial_run as t
from common import HERE, STATE_FILE
from monitor import Tap, texts
from provisioner import world as w

OP_ASK, OP_ANSWER, OP_BOUND, OP_MSG, OP_DIALOG = 0x4338, 0x0197, 0x4337, 0x46ff, 0x4019
STATE = HERE / STATE_FILE


def load_state(path=None):
    """The state file; the per-apprentice steps run in parallel processes (2026-10-28 23:42: one read the file while
    another was rewriting it -> JSONDecodeError on an empty file), so a half-written read is retried."""
    path = path or STATE
    for attempt in range(20):
        try:
            return json.loads(path.read_text('utf-8')) if path.is_file() else {}
        except (ValueError, PermissionError):
            if attempt == 19:
                raise
            time.sleep(0.1)


class _Lock:
    """Cross-process lock next to the state file (O_EXCL create); a lock older than 30 s is a dead writer's."""
    def __init__(self, path):
        self.path = path.with_name(path.name + '.lock')

    def __enter__(self):
        import os
        end = time.monotonic() + 30
        while True:
            try:
                os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > 30:
                        self.path.unlink()
                        continue
                except OSError:
                    continue
                if time.monotonic() > end:
                    raise TimeoutError(f'{self.path} 30 秒拿不到锁')
                time.sleep(0.05)

    def __exit__(self, *exc):
        try:
            self.path.unlink()
        except OSError:
            pass


def mark(name, step, path=None, **info):
    """state.json: {apprentice: {step: {time, ...}}}; read-modify-write under a lock, written atomically (tmp +
    replace), so parallel apprentices neither lose each other's marks nor leave a half file."""
    import os
    path = path or STATE
    with _Lock(path):
        s = load_state(path)
        s.setdefault(name, {})[step] = {'time': time.strftime('%Y-%m-%d %H:%M:%S'), **info}
        tmp = path.with_name(f'{path.name}.{os.getpid()}.tmp')
        tmp.write_text(json.dumps(s, ensure_ascii=False, indent=2), 'utf-8')
        for attempt in range(50):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:          # a reader has it open right now (Windows)
                if attempt == 49:
                    raise
                time.sleep(0.05)


def done(name, step):
    return step in load_state().get(name, {})


def team_master_lead(master, app):
    """Two-person team, master = leader (拜师 rule 3)."""
    want = (master.char_id, app.char_id)
    if master.team() == want and app.team() == want:
        return
    for c in (app, master):
        if c.team():
            t.say(f'[{c.name}] 先离开现在的队伍 {c.team()}')
            c.game.team_leave()
            t.wait(lambda: not c.team(), 5, f'{c.name} 离队')
    t.say(f'[{master.name}] 邀请 {app.name} 入队 (0x30)')
    master.game.team_invite(app.char_id, w.read_level(master.mem), w.read_invite_byte(master.mem), master.name)
    t.wait(lambda: w.read_team(app.mem).inviter == master.char_id, 5, f'{app.name} 收到邀请')
    app.game.team_accept()
    t.wait(lambda: master.team() == want and app.team() == want, 5, '队伍名单 = [师傅, 徒弟]')
    t.say(f'[{master.name}] 组队成功 {master.team()}')


def server_texts(tap, ops):
    return [(op, ' '.join(texts(body)), body) for _, d, op, body, _ in tap.poll() if d == 'S->C' and op in ops]


def bind(master, app):
    m_tap, a_tap = Tap(master.pid, from_end=True), Tap(app.pid, from_end=True)
    m_tap.poll(), a_tap.poll()
    master.game.click_npc(t.NPC)
    d = t.wait(lambda: (d := master.dialog()) and '结为师徒' in [l for _, l in d.options] and d, 5, '糊涂博士主菜单')
    d = t.choose(master, d, t.pick(d, '结为师徒'), '结为师徒')
    if '确定要结为师徒关系吗' not in t.body(d):
        raise t.Stop(f'没见过的结为师徒页面: {t.body(d)} {d.options}')
    t.say(f'[{master.name}] 选「确定」')
    master.game.select_dialog(t.pick(d, '确定'))
    end, asked, said = time.monotonic() + 10, False, []
    while time.monotonic() < end:
        for op, text, body in server_texts(m_tap, (OP_MSG, OP_DIALOG)):
            said.append(text)
            t.say(f'[{master.name}]   服务器: {op:#06x} {text}')
        for op, text, body in server_texts(a_tap, (OP_ASK, OP_BOUND, OP_MSG)):
            t.say(f'[{app.name}]   服务器: {op:#06x} {text} {body.hex()}')
            if op == OP_ASK and not asked:
                time.sleep(1.0)                        # the user answered the popup ~1.6 s after it came
                t.say(f'[{app.name}] 同意拜师 (0x0197 00000000 01)')
                app.game.send(OP_ANSWER, b'\0\0\0\0\x01')
                asked = True
            elif op == OP_BOUND:
                return text
        time.sleep(0.1)
    raise t.Stop(f'10s 内没结成师徒；徒弟收到拜师请求={asked}；师傅这边服务器说: {said}')


def main(names, master_name):
    master = t.Client(master_name)
    t.say(f'[{master_name}] pid {master.pid} char {master.char_id} 等级 {w.read_level(master.mem)}')
    for name in names:
        try:
            if done(name, 'bai_shi'):
                t.say(f'[{name}] state.json 记着已经拜过师，跳过')
                continue
            app = t.Client(name)
            t.say(f'===== {name} pid {app.pid} char {app.char_id} 等级 {w.read_level(app.mem)}')
            team_master_lead(master, app)
            t.walk_to_npc(master)
            bind(master, app)
            mark(name, 'bai_shi', master=master_name, master_id=master.char_id, char_id=app.char_id)
            t.say(f'[{name}] 拜师成功，师傅 {master_name}')
            master.game.team_leave()
            t.wait(lambda: not master.team(), 5, '师傅离队')
        except t.Stop as e:
            t.say(f'[{name}] 停止: {e}')
            raise SystemExit(1)


if __name__ == '__main__':
    m, rest = t.split_master(sys.argv[1:])
    main(rest or ['十万2', '十万3'], m if m != t.MASTER else '伏地魔1')
