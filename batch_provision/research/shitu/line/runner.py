"""Run one batch of one team through the route, with every recovery rule in one place.

Replaces the round-4 stack r4_batch.sh -> r4_sup.sh -> r4_supervise.sh -> r4_run.sh -> r4_*.sh (+ r4_line.py's
recovery): no shell scripts are executed, so editing code while a team runs cannot shift a running script.

Per step (route.ROUTE order, finished steps are checkpointed in logs/<LOGID>_line.json, a restart resumes there):
  0. health: the master's window must exist (else park: MASTER_DOWN, nobody can log the master in); outside the
     make stage `r4_util windows` logs lost apprentices in again.
  1. Step.unless holds (leveling already done) -> the step counts as done.
  2. run the Cmds; a silent log for `silent` s = hung -> the process tree is killed (= a failure).
  3. failure ladder (attempt = one full run of the step):
       attempts 1..retries        cleanup (Step.retry: home / leave), 5 s, rerun
       next recover_tries ones    everybody home, wait recover_wait s, rerun
       then                       a late gate left names in logs/<LOGID>_short.txt -> those apprentices are excluded
                                  (stay bound to the master, never 出师), the rest rerun the step from attempt 1
       else                       park the team with the reason (alert); other teams go on.
The executor is injectable (tests run the whole ladder without a game).
"""
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from . import route as R

HERE = Path(__file__).resolve().parent.parent          # research/shitu (cwd of every script)
LOGS = HERE / 'logs'


@dataclass
class Result:
    ok: bool
    reason: str = ''
    excluded: tuple = ()


def kill_tree(pid):
    if os.name == 'nt':
        subprocess.run(['taskkill', '/T', '/F', '/PID', str(pid)], capture_output=True)
    else:
        try:
            os.kill(pid, 9)
        except OSError:
            pass


def run_procs(argvs, env, log, silent, poll=10):
    """Start every argv at once (output appended to log), wait for all; a log unchanged for `silent` s kills them
    all. -> 0 when every process exited 0, else the first non-zero code (-9 = killed as hung)."""
    with open(log, 'ab') as f:
        procs = [subprocess.Popen(a, cwd=HERE, env=env, stdout=f, stderr=subprocess.STDOUT) for a in argvs]
    last, size = time.time(), log.stat().st_size
    hung = False
    while any(p.poll() is None for p in procs):
        time.sleep(poll)
        s = log.stat().st_size
        if s != size:
            last, size = time.time(), s
        elif time.time() - last >= silent:
            with open(log, 'a', encoding='utf-8') as f:
                f.write(f'{time.strftime("%H:%M:%S")} 停止: 日志 {int(time.time() - last)} 秒没有变化，判定卡死\n')
            for p in procs:
                if p.poll() is None:
                    kill_tree(p.pid)
            hung = True
    if hung:
        return -9
    return next((p.returncode for p in procs if p.returncode), 0)


class Runner:
    def __init__(self, batch, retries=3, recover_tries=2, recover_wait=300, silent=900, logs=LOGS,
                 execute=None, sleep=time.sleep, say=None):
        self.b, self.logs = batch, Path(logs)
        self.retries, self.recover_tries, self.recover_wait, self.silent = retries, recover_tries, recover_wait, silent
        self.execute = execute or self._execute
        self.sleep = sleep
        self.say = say or (lambda m: print(f'{time.strftime("%H:%M:%S")} [{batch.logid}] {m}', flush=True))
        self.progress_file = self.logs / f'{batch.logid}_line.json'
        self.short_file = self.logs / f'{batch.logid}_short.txt'
        self.p = self._load()
        self.b.skip = list(dict.fromkeys(self.b.skip + self.p['excluded']))
        self.stage_log = None

    # ---- progress ------------------------------------------------------------------------------------------
    def _load(self):
        try:
            p = json.loads(self.progress_file.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            p = {}
        return {'done': p.get('done', []), 'excluded': p.get('excluded', []), 'events': p.get('events', [])}

    def _save(self):
        self.logs.mkdir(exist_ok=True)
        self.progress_file.write_text(json.dumps(self.p, ensure_ascii=False, indent=1), encoding='utf-8')

    def event(self, msg):
        self.say(msg)
        self.p['events'].append(f'{time.strftime("%m-%d %H:%M:%S")} {msg}')
        self._save()

    # ---- execution -----------------------------------------------------------------------------------------
    def env(self, step):
        e = dict(os.environ, **self.b.env(), **step.env)
        e['PYTHONIOENCODING'] = 'utf-8'
        return e

    def _execute(self, argvs, env):
        self.logs.mkdir(exist_ok=True)
        log = self.logs / f'{self.b.logid}_{self.stage_log}.log'
        with open(log, 'a', encoding='utf-8') as f:
            for a in argvs:
                f.write(f'$ {" ".join(a[3:] if a[:3] == [sys.executable, "-X", "utf8"] else a)}\n')
        return run_procs(argvs, env, log, self.silent)

    def argv(self, cmd):
        return R.expand(cmd, self.b, python=(sys.executable, '-X', 'utf8'))

    def check(self, cond, step):
        """ops condition -> True / False."""
        return self.execute([[sys.executable, '-X', 'utf8', '-m', 'line.ops', 'when', *cond.split()]], self.env(step)) == 0

    def run_step(self, step):
        """One attempt. -> 0 ok, else the exit code of the failing Cmd."""
        for cmd in step.cmds:
            if not self.b.apprentices and ('{APPS}' in cmd.args or cmd.par):
                continue
            if cmd.when and not self.check(cmd.when, step):
                continue
            rc = self.execute(self.argv(cmd), self.env(step))
            if rc and not cmd.soft:
                return rc
        return 0

    def health(self, step):
        """-> 0 ok, 2 master window missing, other = could not check / relog."""
        ops = [sys.executable, '-X', 'utf8', '-m', 'line.ops', 'master_up']
        if step.stage == 'make':
            return self.execute([ops], self.env(step))
        return self.execute([[sys.executable, '-X', 'utf8', 'r4_util.py', 'windows', *self.b.pairs]], self.env(step))

    def cleanup(self, how, step):
        if how != 'none':
            self.execute([[sys.executable, '-X', 'utf8', 'r4_util.py', how]], self.env(step))

    # ---- the ladder ----------------------------------------------------------------------------------------
    def run(self, frm=None, until=None):
        names = R.NAMES[R.NAMES.index(frm):] if frm else R.NAMES
        if until:
            names = names[:names.index(until) + 1]
        if not self.p['done'] and not frm:
            self.event('批次开始')              # r5_compare.py: the batch's first step starts here
        for name in names:
            if name in self.p['done'] and not frm:
                continue
            res = self.do_step(R.step(name))
            if not res.ok:
                return res
            frm = None                       # only the first step of a FROM run is forced
        self.event('批次完成')
        return Result(True, 'done', tuple(self.p['excluded']))

    def do_step(self, step):
        self.stage_log = f'line_{step.stage}'
        attempt, bad_health = 0, 0
        while True:
            if not self.b.apprentices and step.stage != 'make':
                return Result(False, '没有徒弟了（全被排除）', tuple(self.p['excluded']))
            h = self.health(step)
            if h == 2:
                self.event(f'{step.name}: 师傅窗口没了 MASTER_DOWN')
                return Result(False, 'MASTER_DOWN')
            if h:
                bad_health += 1
                if bad_health > 10:
                    self.event(f'{step.name}: 窗口检查 / 重新登录连续 10 次失败')
                    return Result(False, 'WINDOWS')
                self.say(f'{step.name}: 窗口检查失败，60 秒后再试')
                self.sleep(60)
                continue
            bad_health = 0
            self._marker(step)
            if step.unless and self.check(step.unless, step):
                self.say(f'{step.name}: 已满足 {step.unless}，跳过')
                rc = 0
            else:
                if self.short_file.exists():
                    self.short_file.unlink()
                rc = self.run_step(step)
            if rc == 0:
                self.p['done'].append(step.name)
                self.event(f'{step.name} 完成' + (f'（第 {attempt + 1} 次）' if attempt else ''))
                return Result(True)
            attempt += 1
            if attempt <= self.retries:
                self.event(f'{step.name} 失败（rc={rc}），第 {attempt} 次重跑，先 {step.retry}')
                self.cleanup(step.retry, step)
                self.sleep(5)
                continue
            if attempt <= self.retries + self.recover_tries:
                self.event(f'{step.name} 失败（rc={rc}），恢复 {attempt - self.retries}/{self.recover_tries}：'
                           f'回城，等 {self.recover_wait} 秒')
                self.cleanup('home', step)
                self.sleep(self.recover_wait)
                continue
            short = [n for n in self._short() if n in self.b.apprentices]
            if step.stage == 'late' and short:
                self.p['excluded'] += short
                self.b.skip += short
                self.event(f'{step.name} 过不去，排除 {short}（留在师傅名下不出师），其余人从这一步重来')
                attempt = 0
                continue
            self.event(f'{step.name} 恢复 {self.recover_tries} 次都不行，这一队停摆')
            return Result(False, f'STEP {step.name}', tuple(self.p['excluded']))

    def _short(self):
        try:
            return self.short_file.read_text(encoding='utf-8').split()
        except OSError:
            return []

    def _marker(self, step):
        if self.execute == self._execute:      # `is` never holds: every attribute access makes a new bound method
            with open(self.logs / f'{self.b.logid}_{self.stage_log}.log', 'a', encoding='utf-8') as f:
                f.write(f'== STEP {step.name} {time.strftime("%H:%M:%S")} apps={",".join(self.b.apprentices)}\n')

