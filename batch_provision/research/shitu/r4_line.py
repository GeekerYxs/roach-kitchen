"""师徒产线总控（无人值守）：每个师傅一条线程，一批接一批跑 r4_batch.sh（建号 -> 前段 -> 中段 -> 后段 -> 出师），
监管器（r4_supervise.sh）放弃之后由这里再恢复。

    python -X utf8 research/shitu/r4_line.py                    按 r4_line.toml 跑
    python -X utf8 research/shitu/r4_line.py --teams a,c        只跑这几队
    python -X utf8 research/shitu/r4_line.py --status           打印每队进度（logs/line_state.json）后退出

停下：建文件 logs/LINE_STOP（当前批跑完再停，不打断）；删掉它再启动就接着跑。
进度：logs/line_state.json（每队：已完成的批、排除的徒弟、恢复次数、是否停摆）；报警：logs/line_alert.log。

恢复规则（每一批）：
  1. 监管器在某一步重试 3 次后放弃（SUP_GIVEUP 脚本 步骤）：全队回城，等 recover_wait 秒，从那一步再交给监管器，
     最多 recover_tries 次（窗口没了的徒弟监管器会自己重新登录）。
  2. 还不行、而且是后段某一步的任务进度检查没过（r4_util need 把没到的徒弟写进 logs/<LOGID>_short.txt）：
     把这几个徒弟排除（记进 stuck，他们留在师傅名下、不出师），其余的人从那一步接着跑。
  3. MASTER_DOWN（师傅窗口没了，师傅账号不在配置里，没法自动登录）或以上都不行：这一队停摆，写报警，别的队照跑。
被排除的徒弟一直占着师傅的名额（一个师傅最多 4 个徒弟），所以这一队以后每批少建几个号。
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOGS = HERE / 'logs'
STATE = LOGS / 'line_state.json'
ALERT = LOGS / 'line_alert.log'
STOP = LOGS / 'LINE_STOP'
CONFIG = HERE / 'r4_line.toml'
MASTER_SLOTS = 4
GIVEUP = re.compile(r'SUP_GIVEUP (\S+) (\S+)')
_lock = threading.Lock()


def say(msg):
    print(f'{time.strftime("%H:%M:%S")} {msg}', flush=True)


def alert(team, msg):
    say(f'[{team}] 报警: {msg}')
    with _lock, open(ALERT, 'a', encoding='utf-8') as f:
        f.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")} [{team}] {msg}\n')


def load_state():
    try:
        return json.loads(STATE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def save_team(team, data):
    with _lock:
        st = load_state()
        st[team] = data
        STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding='utf-8')


def batch_names(team, batch):
    """The four apprentice names of a team's batch (same rule as r4_env.sh)."""
    k = 'abcd'.index(team) * 4
    o = 16 * (batch - 1) + k
    return [f'亿万{o + i}' for i in range(1, 5)]


def plan_skip(team, batch, stuck):
    """Names to leave out of this batch: the stuck ones (bound to the master) and, because each of them takes a
    master slot, as many of this batch's last names. -> list for SKIP."""
    names = batch_names(team, batch)
    room = max(0, MASTER_SLOTS - len(stuck))
    return list(stuck) + names[room:]


def outcome(sup_log):
    """Latest state of a supervisor log: ('done', None, None) | ('giveup', script, step) | ('running', None, None)
    when a run started after the last verdict | (None, None, None) for no log / nothing yet."""
    try:
        lines = Path(sup_log).read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        return None, None, None
    for line in reversed(lines):
        if 'done r4_late.sh' in line:
            return 'done', None, None
        m = GIVEUP.search(line)
        if m:
            return 'giveup', m.group(1), m.group(2)
        if re.search(r' start r4_\w+\.sh FROM=', line):
            return 'running', None, None
    return None, None, None


def last_step(logs, lid):
    """(script, step) a supervisor that vanished was in: the newest stage log with a "== STEP" line."""
    best = None
    for script in ('r4_early.sh', 'r4_mid.sh', 'r4_late.sh'):
        f = logs / f'{lid}_{script[:-3]}.log'
        if f.exists():
            steps = [l.split()[2] for l in f.read_text(encoding='utf-8', errors='replace').splitlines()
                     if l.startswith('== STEP ')]
            if best is None or f.stat().st_mtime > best[0]:
                best = (f.stat().st_mtime, script, steps[-1] if steps else 'start')
    return (best[1], best[2]) if best else ('r4_early.sh', 'start')


def resume_args(script, step):
    """r4_sup.sh arguments that continue a team from the step it gave up in."""
    if script == 'r4_early.sh':
        return ['early']               # every early step skips what is already done
    if script == 'r4_mid.sh':
        return [step]
    return ['late', step]


def logid(team, batch):
    return f'r4{team}' if batch == 1 else f'r4{team}_b{batch}'


class Team(threading.Thread):
    def __init__(self, team, cfg):
        super().__init__(name=team, daemon=True)
        self.team, self.cfg = team, cfg
        st = load_state().get(team, {})
        self.data = {'done': st.get('done', []), 'stuck': st.get('stuck', list(cfg['stuck'].get(team, []))),
                     'parked': False, 'batch': None, 'recover': 0}

    def sup_alive(self):
        """Is an r4_supervise.sh for this team running (MSYS ps lists the bash command lines)?"""
        out = subprocess.run(['bash', '-c', 'ps -ef'], capture_output=True, text=True, encoding='utf-8',
                             errors='replace').stdout or ''
        return any(f'r4_supervise.sh {self.team} ' in l or l.rstrip().endswith(f'r4_supervise.sh {self.team}')
                   for l in out.splitlines())

    def save(self):
        save_team(self.team, self.data)

    def env(self, batch):
        e = dict(os.environ, BATCH=str(batch), SKIP=' '.join(plan_skip(self.team, batch, self.data['stuck'])))
        return e

    def sh(self, args, batch):
        log = LOGS / f'{logid(self.team, batch)}_line.log'
        with open(log, 'a', encoding='utf-8') as f:
            f.write(f'== {time.strftime("%H:%M:%S")} {" ".join(args)} SKIP={self.env(batch)["SKIP"]}\n')
            f.flush()
            return subprocess.run(['bash', *args], cwd=HERE, env=self.env(batch), stdout=f, stderr=subprocess.STDOUT).returncode

    def run(self):
        try:
            self.line()
        except Exception as e:          # a bug here must not end the team silently
            alert(self.team, f'总控线程出错停摆: {e!r}')
            self.data['parked'] = True
            self.save()
            raise

    def line(self):
        first = min(self.cfg['batches'])
        prev = LOGS / f'{logid(self.team, first - 1)}_sup.log'
        if first > 1 and first - 1 not in self.data['done'] and prev.exists():
            # the batch before ours was started by hand / by r4_next.sh: wait for it, recover it like our own
            say(f'[{self.team}] 先接管第 {first - 1} 批，等它结束')
            if not self.finish(first - 1):
                self.data['parked'] = True
                self.save()
                return
            self.data['done'].append(first - 1)
            self.save()
        for batch in self.cfg['batches']:
            if batch in self.data['done']:
                continue
            if STOP.exists():
                say(f'[{self.team}] 有 LINE_STOP，第 {batch} 批不再开始')
                break
            if MASTER_SLOTS - len(self.data['stuck']) <= 0:
                alert(self.team, f'排除的徒弟 {self.data["stuck"]} 占满了师傅名额，这一队停摆')
                self.data['parked'] = True
                break
            self.data.update(batch=batch, recover=0)
            self.save()
            say(f'[{self.team}] 第 {batch} 批开始，跳过 {plan_skip(self.team, batch, self.data["stuck"])}')
            self.sh(['r4_batch.sh', self.team, str(batch)], batch)
            if not self.finish(batch):
                self.data['parked'] = True
                self.save()
                break
            self.data['done'].append(batch)
            self.save()
            say(f'[{self.team}] 第 {batch} 批完成')
        self.data['batch'] = None
        self.save()

    def finish(self, batch):
        """Recover the batch until its supervisor says done. -> False when the team has to be parked."""
        sup = LOGS / f'{logid(self.team, batch)}_sup.log'
        while True:
            verdict, script, step = outcome(sup)
            if verdict == 'done':
                return True
            if verdict == 'running' and self.sup_alive():
                time.sleep(60)
                continue
            if verdict == 'running':
                alert(self.team, f'第 {batch} 批监管器不在了但没有结论，从最后一步接着跑')
                verdict, script, step = 'giveup', *last_step(LOGS, logid(self.team, batch))
            if script == 'make':          # r4_batch.sh: make_apprentices failed (login / create)
                if self.data['recover'] < self.cfg['recover_tries']:
                    self.data['recover'] += 1
                    self.save()
                    say(f'[{self.team}] 第 {batch} 批建号失败，等 {self.cfg["recover_wait"]} 秒重来')
                    time.sleep(self.cfg['recover_wait'])
                    self.sh(['r4_batch.sh', self.team, str(batch)], batch)
                    continue
                alert(self.team, f'第 {batch} 批建号 {self.cfg["recover_tries"]} 次都失败，这一队停摆')
                return False
            if verdict is None:
                alert(self.team, f'第 {batch} 批监管器没有结论就退出了（{sup.name}）')
                return False
            if step == 'MASTER_DOWN':
                alert(self.team, f'第 {batch} 批：师傅窗口没了，需要人工登录师傅后重启 r4_line.py')
                return False
            if self.data['recover'] < self.cfg['recover_tries']:
                self.data['recover'] += 1
                self.save()
                say(f'[{self.team}] 第 {batch} 批 {script} 在 {step} 放弃，第 {self.data["recover"]} 次恢复：'
                    f'回城，等 {self.cfg["recover_wait"]} 秒再从 {step} 跑')
                self.sh(['-c', '. ./r4_env.sh "$0"; python -X utf8 r4_util.py home', self.team], batch)
                time.sleep(self.cfg['recover_wait'])
                self.sh(['r4_sup.sh', self.team, *resume_args(script, step)], batch)
                continue
            short = LOGS / f'{logid(self.team, batch)}_short.txt'
            names = short.read_text(encoding='utf-8').split() if script == 'r4_late.sh' and short.exists() else []
            names = [n for n in names if n not in self.data['stuck']]
            if names:
                self.data['stuck'] += names
                self.data['recover'] = 0
                self.save()
                short.unlink()
                alert(self.team, f'第 {batch} 批 {step} 过不去，排除 {names}（留在师傅名下不出师），其余人继续')
                self.sh(['r4_sup.sh', self.team, *resume_args(script, step)], batch)
                continue
            alert(self.team, f'第 {batch} 批 {script} {step} 恢复 {self.cfg["recover_tries"]} 次都不行，这一队停摆')
            return False


def load_config(path=CONFIG):
    cfg = {'teams': ['a', 'b', 'c', 'd'], 'batches': [3, 4], 'recover_tries': 2, 'recover_wait': 300, 'stuck': {}}
    if path.exists():
        cfg.update(tomllib.loads(path.read_text(encoding='utf-8')))
    return cfg


def main(argv):
    cfg = load_config()
    if '--status' in argv:
        print(json.dumps(load_state(), ensure_ascii=False, indent=1))
        return
    if '--teams' in argv:
        cfg['teams'] = argv[argv.index('--teams') + 1].split(',')
    LOGS.mkdir(exist_ok=True)
    say(f'产线开始: 队 {cfg["teams"]}，批次 {cfg["batches"]}；停下 = 建 {STOP}')
    threads = [Team(t, cfg) for t in cfg['teams']]
    for th in threads:
        th.start()
        time.sleep(60)          # stagger the logins (make_apprentices) of the teams
    for th in threads:
        th.join()
    say('产线结束: ' + json.dumps(load_state(), ensure_ascii=False))


if __name__ == '__main__':
    main(sys.argv[1:])
