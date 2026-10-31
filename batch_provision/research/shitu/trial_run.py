"""Run the first two 师徒考验 (quiz trials) for apprentices, one after another, with 欧皇 as the master.

    python -X utf8 research/shitu/trial_run.py [--master 伏地魔1] mm02 mm03 mm04     (master default: 欧皇)

Per apprentice: (load + arm our DLL if needed) -> master leaves any team -> apprentice invites the master
(apprentice = leader) -> master accepts -> apprentice walks to 糊涂博士 (npc 341, map 1) -> dialog
师徒任务 -> 考验任务 -> 准备好了 -> answer every question by matching the ANSWER TEXT (options are shuffled per
showing, see ANALYSIS.md) -> take the reward -> again, until the NPC offers the third trial (勇气和关心) -> master
leaves the team.
Unknown question: try an option not known to be wrong; a wrong answer ends the trial ("很可惜") and it is started
again (no penalty seen on 2026-10-26). Learned answers go to bank.json.
No UI clicks: dialog = ClickNpc / SelectNpcDialogEntry game functions (DLL command 106), team = 0x30 invite through
the client's sender + the client's own accept/leave functions, reading = ReadProcessMemory.
"""
import json
import math
import random
import re
import sys
import time
from datetime import datetime

from common import HERE, LOGS, find_roles, module_base
import attach_tap
from provisioner import native, world as w
from provisioner.game import Game
from provisioner.memory import ProcessMemory

MASTER = '欧皇'
NPC, NPC_MAP, NPC_XY = 341, 1, (1398, 1329)
STAND = (1370, 1336)                 # where mm01 stood when it talked to him
NEAR = 90
BANK = HERE / 'bank.json'
MAX_STARTS = 15                      # trial (re)starts per apprentice
ANSWER_DELAY = (1.0, 2.0)            # seconds before each answer, human-like (speed was NOT the cause of the 1st miss)
ARMOR_CHOICE = 1                     # trial 2 reward: 1 魔幻布甲 / 2 流水软甲 / 3 壮志精甲 (mm01 took 1)
ASK = False                          # --ask: unknown question / armor choice -> stop and report instead of guessing
                                     # (--armor N sets the armor and still asks about unknown questions)
_COLOR = re.compile(r'#[0-9a-fA-F]{6}#')
_QUESTION = re.compile(r'^\s*(\d+)、(.*)$', re.S)

LOGS.mkdir(exist_ok=True)
_log = open(LOGS / f'trial_{datetime.now():%Y%m%d_%H%M%S}.log', 'w', encoding='utf-8')


def say(msg):
    line = f'{datetime.now():%H:%M:%S.%f}'[:-3] + ' ' + msg
    print(line, flush=True)
    _log.write(line + '\n')
    _log.flush()


class Stop(Exception):
    pass


class Client:
    def __init__(self, name):
        found = find_roles((name,))
        if name not in found:
            raise Stop(f'{name} 的窗口没找到')
        self.name, self.pid = name, found[name][0]
        if not native.has_dll(self.pid) or native.read_status(self.pid)['stage'] != native.WORLD_STAGE:
            attach_tap.RUNTIME.mkdir(exist_ok=True)
            attach_tap.attach(name, self.pid, attach_tap.fresh_dll())
        st = native.read_status(self.pid)
        self.mem = ProcessMemory(self.pid, module_base(self.pid))
        self.game = Game(native.Session(self.pid, st['hwnd'], st['game_base']), self.mem)
        self.char_id = w.read_world(self.mem).char_id

    def world(self):
        return w.read_world(self.mem)

    def team(self):
        t = w.read_team(self.mem)
        return t.members if t else ()

    def dialog(self):
        st = self.world()
        return st.dialog if st else None


def wait(cond, timeout, what):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = cond()
        if v:
            return v
        time.sleep(0.1)
    raise Stop(f'{timeout}s 内没等到: {what}')


# ---------------------------------------------------------------- team / walking

def form_team(app, master):
    want = (app.char_id, master.char_id)
    if app.team() == want and master.team() == want:
        say(f'[{app.name}] 已经和 {master.name} 组队，{app.name} 是队长')
        return
    for c in (master, app):
        if c.team():
            say(f'[{c.name}] 先离开现在的队伍 {c.team()}')
            c.game.team_leave()
            wait(lambda: not c.team(), 5, f'{c.name} 离队')
    level, byte = w.read_level(app.mem), w.read_invite_byte(app.mem)
    say(f'[{app.name}] 邀请 {master.name} 入队 (0x30, 等级 {level})')
    app.game.team_invite(master.char_id, level, byte, app.name)
    wait(lambda: w.read_team(master.mem).inviter == app.char_id, 5, f'{master.name} 收到邀请')
    for attempt in range(3):     # the inviter field can hold an OLD invite: accept again (well10.form_team, round 3 11:06)
        say(f'[{master.name}] 接受邀请')
        master.game.team_accept()
        try:
            wait(lambda: app.team() == want and master.team() == want, 3, '双方队伍名单 = [徒弟, 师傅]')
            break
        except Stop:
            if attempt == 2:
                raise
            time.sleep(0.5)
    say(f'[{app.name}] 组队成功，队伍 {app.team()}')


def leave_team(app, master):
    if master.team():
        master.game.team_leave()
        wait(lambda: not master.team() and not app.team(), 5, '师傅离队')
        say(f'[{master.name}] 已离队')


def walk_to_npc(app):
    st = app.world()
    if st.map_id != NPC_MAP:
        raise Stop(f'{app.name} 不在逍遥村 (map {st.map_id})')
    if math.dist((st.x, st.y), NPC_XY) <= NEAR:
        return
    say(f'[{app.name}] 走到糊涂博士旁边 {STAND}（现在 {int(st.x)},{int(st.y)}）')
    app.game.navigate(NPC_MAP, *STAND)
    wait(lambda: (s := app.world()) and math.dist((s.x, s.y), NPC_XY) <= NEAR and not s.moving, 30, '走到 NPC 旁')


# ---------------------------------------------------------------- dialog

def plain(text):
    return _COLOR.sub('', text)


def body(dialog):
    """Dialog text without the option lines and colour codes."""
    return plain(re.sub(r'\[URL[^\]]*\].*?\[/URL\]', '', dialog.text, flags=re.S)).strip()


def pick(dialog, label):
    for opt, lab in dialog.options:
        if lab == label:
            return opt
    raise Stop(f'对话里没有选项「{label}」: {dialog.options}')


def choose(app, dialog, opt, label):
    say(f'[{app.name}]   选 opt={opt}「{label}」')
    before = dialog.text
    app.game.select_dialog(opt)
    return wait(lambda: (d := app.dialog()) and d.text != before and d, 5, f'选「{label}」后的新对话')


def open_menu(app):
    app.game.click_npc(NPC)
    d = wait(lambda: (d := app.dialog()) and '师徒任务' in [l for _, l in d.options] and d, 5, '糊涂博士主菜单')
    d = choose(app, d, pick(d, '师徒任务'), '师徒任务')
    return choose(app, d, pick(d, '考验任务'), '考验任务')


def load_bank():
    return json.loads(BANK.read_text('utf-8'))


def save_bank(bank):
    BANK.write_text(json.dumps(bank, ensure_ascii=False, indent=2), 'utf-8')


def run_trials(app):
    """Trials until the third one (勇气和关心) is offered. Returns the trial intros done."""
    bank, done, starts = load_bank(), [], 0
    while True:
        d = open_menu(app)
        intro = body(d)
        say(f'[{app.name}] 考验开场: {intro[:60]}')
        if '勇气和关心' in intro or '第三次考验' in intro:      # 2026-10-27 lv25:「第三次考验要求徒弟级别不小于三十级…」
            say(f'[{app.name}] 已到第三次考验（打地头蛇），前两次已完成')
            app.game.select_dialog(0)      # leave the dialog
            return done
        if '准备好了' not in [l for _, l in d.options]:
            raise Stop(f'没见过的考验开场: {intro} {d.options}')
        starts += 1
        if starts > MAX_STARTS:
            raise Stop(f'{MAX_STARTS} 次开始考验仍没通过')
        d = choose(app, d, pick(d, '准备好了'), '准备好了')
        trial = intro[:12]
        guess = None                                   # (question, label) answered without knowing
        while True:
            text = body(d)
            m = _QUESTION.match(text)
            if m:
                q = m.group(2).strip()
                labels = [l for _, l in d.options]
                if guess:                              # previous unknown answer was right
                    bank['right'][guess[0]] = guess[1]
                    save_bank(bank)
                    say(f'[{app.name}]   学到: {guess[0]} -> {guess[1]}')
                    guess = None
                ans = bank['right'].get(q)
                if ans is None and ASK:
                    app.game.select_dialog(0)
                    raise Stop(f'第{m.group(1)}题题库里没有，请告诉我答案: {q}  选项 {labels}')
                if ans is None:
                    tried = bank['wrong'].get(q, [])
                    left = [l for l in labels if l not in tried]
                    if not left:
                        raise Stop(f'题目所有选项都试过是错的: {q}')
                    ans, guess = left[0], (q, left[0])
                    say(f'[{app.name}] 第{m.group(1)}题（题库没有，试）: {q}  选项 {labels}')
                else:
                    say(f'[{app.name}] 第{m.group(1)}题: {q}')
                time.sleep(random.uniform(*ANSWER_DELAY))
                d = choose(app, d, pick(d, ans), ans)
                continue
            if '答错' in text:
                if guess:
                    bank['wrong'].setdefault(guess[0], []).append(guess[1])
                    save_bank(bank)
                    say(f'[{app.name}]   答错，记下: {guess[0]} 不是 {guess[1]}')
                else:
                    raise Stop(f'题库答案被判错: {text}')
                app.game.select_dialog(d.options[0][0])   # 好的
                time.sleep(0.5)
                break                                      # start the trial again
            if '回答得不错' in text:
                if guess:
                    bank['right'][guess[0]] = guess[1]
                    save_bank(bank)
                    say(f'[{app.name}]   学到: {guess[0]} -> {guess[1]}')
                labels = [l for _, l in d.options]
                gold = w.read_gold(app.mem)
                if '接受奖励' not in labels and ASK and ARMOR_CHOICE is None:
                    raise Stop(f'考验二答完了，请选护甲（对话框还开着）: {d.options}')
                opt = pick(d, '接受奖励') if '接受奖励' in labels else ARMOR_CHOICE
                say(f'[{app.name}] 全部答对，领奖 opt={opt}「{dict(d.options).get(opt)}」')
                app.game.select_dialog(opt)
                wait(lambda: w.read_gold(app.mem) > gold, 5, '奖励金币到账')
                say(f'[{app.name}] 奖励到账，金币 {gold} -> {w.read_gold(app.mem)}')
                done.append(trial)
                time.sleep(1)
                break
            raise Stop(f'没见过的对话: {text} {d.options}')


def split_master(argv):
    """['--master', X, a, b] -> (X, [a, b]); no --master -> (MASTER, argv). Also takes --ask and --armor N."""
    global ASK, ARMOR_CHOICE
    argv = list(argv)
    if '--ask' in argv:
        argv.remove('--ask')
        ASK, ARMOR_CHOICE = True, None
    if '--armor' in argv:
        i = argv.index('--armor')
        ARMOR_CHOICE = int(argv[i + 1])
        del argv[i:i + 2]
    if argv[:1] == ['--master'] and len(argv) > 1:
        return argv[1], argv[2:]
    return MASTER, argv


def main(names, master_name=MASTER):
    master = Client(master_name)
    say(f'[{master_name}] pid {master.pid} char {master.char_id}')
    for name in names:
        try:
            app = Client(name)
            say(f'===== {name} pid {app.pid} char {app.char_id} 等级 {w.read_level(app.mem)}')
            form_team(app, master)
            walk_to_npc(app)
            done = run_trials(app)
            say(f'[{name}] 完成: {done or "（本来就已做完前两次）"}')
            leave_team(app, master)
        except Stop as e:
            say(f'[{name}] 停止: {e}')
            raise SystemExit(1)


if __name__ == '__main__':
    m, rest = split_master(sys.argv[1:])
    main(rest or ['mm02', 'mm03', 'mm04'], m)
