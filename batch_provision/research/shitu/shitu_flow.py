"""师徒全流程 — read the state, say what each apprentice still needs, and (with --next) run ONE step.

    python -X utf8 research/shitu/shitu_flow.py [--master 伏地魔1] [十万1 十万2 十万3]           plan only (read-only)
    python -X utf8 research/shitu/shitu_flow.py --next [--master 伏地魔1] [十万1 ...]          run the first open step

Order, live-verified 2026-10-27 with 伏地魔1 + 十万1..3 (ANALYSIS.md 10-12, GATHER.md 7-8). Each step is decided from
memory (level, quest tree, map) and research/shitu/state.json (what memory cannot show: 拜师, trials 1+2, trial 3):
  1 拜师           any level < 40, master > 45 + 一转, <= 4 apprentices            bai_shi.py
  2 练到 10        well10.py (阴森古井, eats 地瓜x2 + 酒池 + 肉林 on arrival)          leveling: by hand / see below
  3 转职 task 24   lv >= 10: zhuanzhi_take.py -> 拳手 x5 in 夕阳草原 (quanshou.py, the kills show ONLY as 0x46ff)
                   -> zhuanzhi_take.py --handin -> zhuanzhi_finish.py (梦幻岛 神仙姐姐)
  4 考验一、二     needs the 转职; trial_run.py --ask --armor 3 (bank.json, 15 questions)
  5 练到 30        lunhui15.py (10-15), maze_train.py (暗影迷城 / 八阵图), tower28.py 30 (通天塔一区)
  6 task 224       lv >= 28, taken SOLO (a team is checked as a whole): take224.py
  7 地头蛇         every member has 224 steps (1,): go_cave.py, gather.py 9 + dark until 3 stones, dts.py
  8 考验三         lv >= 30 (NPC:「第三次考验要求徒弟级别不小于三十级」) and 224 steps (2,1): trial3_run.py
Leveling and the cave trip move the whole team between maps, so --next only PRINTS their command; every other step is
run as the listed script for the apprentices that need it, then the plan is printed again.
"""
import subprocess
import sys

import trial_run as t
from bai_shi import done
from common import APPRENTICES, HERE
from provisioner import world as w

PY = [sys.executable, '-X', 'utf8']


def status(c):
    lv = w.read_level(c.mem)
    q24, q224 = w.read_quest(c.mem, 24), w.read_quest(c.mem, 224)
    return dict(name=c.name, level=lv, map=c.world().map_id, q24=q24, q224=q224,
                bai_shi=done(c.name, 'bai_shi'), trial12=done(c.name, 'trial12'), trial3=done(c.name, 'trial3'))


def next_step(s):
    """(key, what, script args or None = manual/team step) for one apprentice."""
    lv, q24, q224 = s['level'], s['q24'], s['q224']
    if s['trial3']:
        return 'done', '考验三已领奖，全部完成', None
    if not s['bai_shi']:
        return 'bai_shi', '拜师', ['bai_shi.py']
    if lv < 10:
        return 'level10', f'{lv} 级：先练到 10（阴森古井 well10.py）', None
    if not q24.done:
        steps = tuple(q24.steps)
        if not q24.active:
            return 'zz_take', '接转职任务 24', ['zhuanzhi_take.py']
        if steps == (0, 0, 1):
            return 'zz_kill', '夕阳草原杀 5 只 75kg级拳手（quanshou.py，系统消息说杀够后再 --handin）', None
        if steps == (0, 0, 2, 0, 1):
            return 'zz_finish', '去梦幻岛找神仙姐姐', ['zhuanzhi_finish.py']
        return 'zz_unknown', f'转职任务 24 在没见过的步骤 {steps}', None
    if not s['trial12']:
        return 'trial12', '考验一、二', ['trial_run.py', '--ask', '--armor', '3']
    if lv < 28:
        return 'level28', f'{lv} 级：练到 28 / 30（lunhui15 / maze_train / tower28.py）', None
    if not q224.active and not q224.done:
        return 'take224', '单独接任务 224', ['take224.py', '--disband']
    if tuple(q224.steps) == (1,):
        return 'snake', '采花 + 打地头蛇（go_cave.py → gather.py → dts.py，每个队员都要接 224）', None
    if lv < 30:
        return 'level30', f'{lv} 级：考验三要 30 级（tower28.py 30）', None
    return 'trial3', '交考验三（强劲之棍）', ['trial3_run.py']


def main(argv):
    run = '--next' in argv
    argv = [a for a in argv if a != '--next']
    master, names = t.split_master(argv)
    master = master if master != t.MASTER else '伏地魔1'
    names = names or list(APPRENTICES)
    plan = {}
    for n in names:
        s = status(t.Client(n))
        key, what, args = next_step(s)
        plan[n] = (key, what, args)
        print(f'{n}: {s["level"]} 级 map {s["map"]} 拜师={s["bai_shi"]} 任务24={s["q24"]} 考验一二={s["trial12"]} '
              f'任务224={s["q224"]} 考验三={s["trial3"]}\n    下一步: {what}')
    if not run:
        return 0
    todo = [(n, k, a) for n, (k, _, a) in plan.items() if k != 'done']
    if not todo:
        print('全部完成')
        return 0
    key, args = todo[0][1], todo[0][2]
    who = [n for n, k, _ in todo if k == key]
    if args is None:
        print(f'下一步「{plan[who[0]][1]}」要带队换地图，请按说明手动跑对应脚本（{", ".join(who)}）')
        return 0
    cmd = PY + [str(HERE / args[0])] + args[1:]
    if args[0] in ('bai_shi.py', 'trial_run.py', 'trial3_run.py'):
        cmd += ['--master', master]
    cmd += who
    print('运行:', ' '.join(cmd[2:]))
    return subprocess.call(cmd, cwd=HERE.parent.parent)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
