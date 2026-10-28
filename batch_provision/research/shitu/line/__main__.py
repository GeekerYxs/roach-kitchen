"""师徒产线 v5 总控：每个师傅一条线程，一批接一批跑 route.ROUTE（建号 -> 前段 -> 中段 -> 后段 -> 出师）。

    cd batch_provision/research/shitu
    python -X utf8 -m line                          按 line.toml 跑全部队
    python -X utf8 -m line --teams a,c              只跑这几队
    python -X utf8 -m line --status                 每队进度（logs/line_state.json + 当前批的步骤）
    python -X utf8 -m line --dry-run [--teams a]    只打印每队下一批要执行的全部命令，不碰游戏
    python -X utf8 -m line --team a --batch 3 --from king [--until king] [--apps 亿万35]
                                                    手动补跑一队一批的几步（--apps = 只带这几个徒弟）

停下：建文件 logs/LINE_STOP（当前批跑完再停）；删掉再启动就从断点接着跑（每步完成都记在 logs/<LOGID>_line.json）。
报警：logs/line_alert.log。设置：line/line.toml。设计和接手说明：docs/SHITU_LINE.md 第 8 节。
"""
import json
import sys
import threading
import time
import tomllib
from pathlib import Path

from . import plan, route as R
from .runner import LOGS, Result, Runner

STATE = LOGS / 'line_state.json'       # same file / schema as r4_line.py: batches 1-2 of round 4 carry over
ALERT = LOGS / 'line_alert.log'
STOP = LOGS / 'LINE_STOP'
CONFIG = Path(__file__).with_name('line.toml')
QUIZBOT = ('启动答题器.exe', 'quizbot.exe')
_lock = threading.Lock()


def say(msg):
    print(f'{time.strftime("%H:%M:%S")} {msg}', flush=True)


def alert(team, msg):
    say(f'[{team}] 报警: {msg}')
    LOGS.mkdir(exist_ok=True)
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
        LOGS.mkdir(exist_ok=True)
        STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding='utf-8')


def load_config(path=CONFIG):
    cfg = {'teams': ['a', 'b', 'c', 'd'], 'batches': [3, 4], 'retries': 3, 'recover_tries': 2, 'recover_wait': 300,
           'silent': 900, 'stagger': 60, 'stuck': {}}
    if path.exists():
        cfg.update(tomllib.loads(path.read_text(encoding='utf-8')))
    return cfg


def quizbot_running():
    """启动答题器 answers the boss / battle quizzes and unlocks the 辅助工具 pages; scripts fall back to
    boss_quiz.py without it, but the battle quiz (0x46F4) has no fallback."""
    import subprocess
    out = subprocess.run(['tasklist', '/FO', 'CSV', '/NH'], capture_output=True, text=True, encoding='gbk',
                         errors='replace').stdout
    return any(q.lower() in out.lower() for q in QUIZBOT)


def next_batch(cfg, data):
    return next((b for b in cfg['batches'] if b not in data['done']), None)


class Team(threading.Thread):
    def __init__(self, team, cfg, runner=Runner):
        super().__init__(name=team, daemon=True)
        self.team, self.cfg, self.Runner = team, cfg, runner
        st = load_state().get(team, {})
        self.data = {'done': st.get('done', []), 'stuck': st.get('stuck', list(cfg['stuck'].get(team, []))),
                     'parked': False, 'batch': None, 'reason': ''}

    def save(self):
        save_team(self.team, self.data)

    def runner(self, batch):
        b = plan.Batch(self.team, batch, plan.plan_skip(self.team, batch, self.data['stuck']))
        c = self.cfg
        return self.Runner(b, retries=c['retries'], recover_tries=c['recover_tries'], recover_wait=c['recover_wait'],
                           silent=c['silent'], say=lambda m: say(f'[{self.team} 第{batch}批] {m}'))

    def run(self):
        try:
            self.line()
        except Exception as e:          # a bug here must not end the team silently
            alert(self.team, f'总控线程出错停摆: {e!r}')
            self.data.update(parked=True, reason=repr(e))
            self.save()
            raise

    def line(self):
        while (batch := next_batch(self.cfg, self.data)) is not None:
            if STOP.exists():
                say(f'[{self.team}] 有 LINE_STOP，第 {batch} 批不再开始')
                break
            if plan.MASTER_SLOTS - len(self.data['stuck']) <= 0:
                alert(self.team, f'排除的徒弟 {self.data["stuck"]} 占满了师傅名额，这一队停摆')
                self.data.update(parked=True, reason='master slots full')
                break
            if not quizbot_running():
                alert(self.team, '启动答题器 没在运行：战斗里的题没人答（boss 题脚本会自己答）。请启动它')
            self.data.update(batch=batch, parked=False, reason='')
            self.save()
            r = self.runner(batch)
            say(f'[{self.team}] 第 {batch} 批开始: {r.b.apprentices}（跳过 {r.b.skip}）')
            res = r.run()
            self.data['stuck'] = list(dict.fromkeys(self.data['stuck'] + list(res.excluded)))
            if not res.ok:
                alert(self.team, f'第 {batch} 批停摆: {res.reason}' +
                      ('（师傅窗口没了：人工登录师傅后重启总控，会从断点接着跑）' if res.reason == 'MASTER_DOWN' else ''))
                self.data.update(parked=True, reason=res.reason)
                break
            self.data['done'].append(batch)
            self.data['batch'] = None
            self.save()
            say(f'[{self.team}] 第 {batch} 批完成')
        self.save()


def dry_run(cfg):
    for team in cfg['teams']:
        data = Team(team, cfg).data
        batch = next_batch(cfg, data)
        if batch is None:
            print(f'== 队 {team}: 配置里的批次都跑完了')
            continue
        b = plan.Batch(team, batch, plan.plan_skip(team, batch, data['stuck']))
        print(f'== 队 {team} 第 {batch} 批 {b.master}: {b.apprentices}  跳过 {b.skip}  {b.pairs}')
        for s in R.ROUTE:
            print(f'-- {s.stage}/{s.name}' + (f'  (跳过条件 {s.unless})' if s.unless else '') + f'  重跑前 {s.retry}')
            for c in s.cmds:
                for a in R.expand(c, b, python=()):
                    print('    ' + (f'[{c.when}] ' if c.when else '') + ' '.join(a) + ('  || 失败不算' if c.soft else ''))


def status(cfg):
    st = load_state()
    for team in cfg['teams']:
        d = st.get(team, {})
        line = f'队 {team}: 完成批 {d.get("done", [])}  排除 {d.get("stuck", [])}'
        if d.get('parked'):
            line += f'  停摆: {d.get("reason", "")}'
        if d.get('batch'):
            p = LOGS / f'{plan.logid(team, d["batch"])}_line.json'
            try:
                pr = json.loads(p.read_text(encoding='utf-8'))
                todo = [n for n in R.NAMES if n not in pr['done']]
                line += f'  第 {d["batch"]} 批下一步 {todo[0] if todo else "-"}  最近: {pr["events"][-1:]}'
            except (OSError, ValueError, KeyError):
                line += f'  第 {d["batch"]} 批进行中'
        print(line)


def arg(argv, name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


def main(argv):
    cfg = load_config()
    if '--teams' in argv:
        cfg['teams'] = arg(argv, '--teams').split(',')
    if '--status' in argv:
        return status(cfg)
    if '--dry-run' in argv:
        return dry_run(cfg)
    if '--team' in argv:                 # manual catch-up of one batch
        team, batch = arg(argv, '--team'), int(arg(argv, '--batch', '1'))
        data = Team(team, cfg).data
        b = plan.Batch(team, batch, plan.plan_skip(team, batch, data['stuck']))
        if '--apps' in argv:
            keep = arg(argv, '--apps').split(',')
            b.skip = [n for n in b.all_names if n not in keep]
        r = Runner(b, retries=cfg['retries'], recover_tries=cfg['recover_tries'], recover_wait=cfg['recover_wait'],
                   silent=cfg['silent'])
        res = r.run(arg(argv, '--from'), arg(argv, '--until'))
        say(f'结果: {res}')
        return 0 if res.ok else 1
    LOGS.mkdir(exist_ok=True)
    say(f'产线开始: 队 {cfg["teams"]}，批次 {cfg["batches"]}；停下 = 建 {STOP}')
    threads = [Team(t, cfg) for t in cfg['teams']]
    for th in threads:
        th.start()
        time.sleep(cfg['stagger'])       # stagger the logins (make_apprentices) of the teams
    for th in threads:
        th.join()
    say('产线结束: ' + json.dumps(load_state(), ensure_ascii=False))


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
