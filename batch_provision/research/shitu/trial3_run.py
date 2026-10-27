"""Hand in the third 师徒考验 (勇气和关心 = 地头蛇 killed with the master) at 糊涂博士, apprentice after apprentice.

    python -X utf8 research/shitu/trial3_run.py [--master 伏地魔1] mm02 mm03 mm04     (master default: 欧皇)

Precondition: the apprentice and 欧皇 killed 地头蛇 together (task 224 step 1 done, see GATHER.md 5c).
Per apprentice (recorded by the user with mm01 at 23:25:42): team apprentice + 欧皇 (apprentice = leader)
-> ClickNpc(341) -> 师徒任务 -> 考验任务 -> intro「这是勇气和关心的考验…」-> 我已经完成考验了
->「嗯，干得不错…请选择一个吧」7 weapons + 等会再来 -> pick WEAPON -> master leaves the team.
Same building blocks as trial_run.py (no UI clicks).
"""
import sys

import trial_run as t
from provisioner import world as w

WEAPON = '强劲之棍'          # opt 5「强劲之棍(长兵器)+(御)加钙地瓜」, the user's choice for mm02-mm04 (mm01 took 6)


def hand_in(app):
    d = t.open_menu(app)
    intro = t.body(d)
    t.say(f'[{app.name}] 考验开场: {intro[:60]}')
    if '勇气和关心' not in intro:
        raise t.Stop(f'不是第三次考验: {intro} {d.options}')
    d = t.choose(app, d, t.pick(d, '我已经完成考验了'), '我已经完成考验了')
    if '干得不错' not in t.body(d):
        raise t.Stop(f'没有给奖励: {t.body(d)} {d.options}')
    t.say(f'[{app.name}] 奖励选项: {d.options}')
    opt = next((o for o, l in d.options if l.startswith(WEAPON)), None)
    if opt is None:
        raise t.Stop(f'奖励里没有 {WEAPON}: {d.options}')
    gold = w.read_gold(app.mem)
    t.say(f'[{app.name}] 领奖 opt={opt}「{dict(d.options)[opt]}」')
    app.game.select_dialog(opt)
    t.wait(lambda: w.read_gold(app.mem) > gold, 5, '奖励金币到账')
    t.say(f'[{app.name}] 奖励到账，金币 {gold} -> {w.read_gold(app.mem)}')


def main(names, master_name=t.MASTER):
    master = t.Client(master_name)
    for name in names:
        try:
            app = t.Client(name)
            t.say(f'===== {name} pid {app.pid} char {app.char_id} 等级 {w.read_level(app.mem)} '
                  f'任务224 {w.read_quest(app.mem, 224)}')
            t.form_team(app, master)
            t.walk_to_npc(app)
            hand_in(app)
            t.leave_team(app, master)
        except t.Stop as e:
            t.say(f'[{name}] 停止: {e}')
            raise SystemExit(1)


if __name__ == '__main__':
    m, rest = t.split_master(sys.argv[1:])
    main(rest or ['mm02', 'mm03', 'mm04'], m)
