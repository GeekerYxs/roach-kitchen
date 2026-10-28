"""Take the 战士 转职 task 24「力量的考验」at 七十九万禁军教头 (NPC 304, 逍遥村就职所 map 8 (894,459)).

    python -X utf8 research/shitu/zhuanzhi_take.py 十万2 十万3                 take the task
    python -X utf8 research/shitu/zhuanzhi_take.py --handin 十万2 十万3       hand in the 拳手 step

Recorded 2026-10-27 01:54:57 (十万1 by hand, lv25, ANALYSIS.md section 11): ClickNpc(304) ->「成为战士」->「真的吗？」->
「可以！」->「接受任务。」-> 0x46ff「接受了任务：力量的考验 | 去夕阳草原杀死5只75kg级拳手」, quest tree 24/0 = 000001.
Hand-in (recorded 02:03:35, 十万1 by hand, after 「已经杀死了5个75Kg级拳手」— the quest tree does NOT show the kills,
it stays steps (0,0,1)): ClickNpc(304) ->「★力量的考验［进行中］」->「知道了！」-> steps (0,0,2,0,1) =
「去梦幻岛找神仙姐姐」. A role whose steps are not (0,0,1) is skipped.
Skips a role whose task 24 is already active. Walks there from map 1 / 8 (navigate(8, ...) crosses 逍遥村 -> 就职所).
"""
import math
import sys
import time

import trial_run as t
from bai_shi import mark
from provisioner import world as w
from take224 import talk

MAP, NPC, XY, QUEST = 8, 304, (894, 459), 24
STEPS = ['成为战士', '真的吗', '可以', '接受任务']


def go(c):
    st = c.world()
    if st.map_id == MAP and math.dist((st.x, st.y), XY) <= 80:
        return
    t.say(f'[{c.name}] 走去禁军教头 {XY}（现在 map {st.map_id} ({st.x:.0f},{st.y:.0f})）')
    c.game.navigate(MAP, XY[0], XY[1] + 40)
    t.wait(lambda: (s := c.world()) and s.map_id == MAP and math.dist((s.x, s.y), XY) <= 80 and not s.moving,
           90, f'{c.name} 走到禁军教头旁')


def take(c):
    q = w.read_quest(c.mem, QUEST)
    if q.active or q.done:
        t.say(f'[{c.name}] 任务 {QUEST} 已经接了或已完成 {q}')
        return
    go(c)
    talk(c, NPC, STEPS)
    t.wait(lambda: w.read_quest(c.mem, QUEST).active, 5, f'{c.name} 任务 {QUEST} 进行中')
    q = w.read_quest(c.mem, QUEST)
    mark(c.name, 'zhuanzhi_task', quest=QUEST, steps=list(q.steps))
    t.say(f'[{c.name}] 接到转职任务 {QUEST} 力量的考验 {q}')
    time.sleep(0.5)


def handin(c):
    q = w.read_quest(c.mem, QUEST)
    if tuple(q.steps) != (0, 0, 1):
        t.say(f'[{c.name}] 任务 {QUEST} 不在打拳手这一步 {q}，跳过')
        return
    go(c)
    talk(c, NPC, ['力量的考验', '知道了'])
    t.wait(lambda: tuple(w.read_quest(c.mem, QUEST).steps) != (0, 0, 1), 5, f'{c.name} 任务 {QUEST} 进到下一步')
    time.sleep(0.6)
    q = w.read_quest(c.mem, QUEST)
    mark(c.name, 'zhuanzhi_quanshou', steps=list(q.steps))
    t.say(f'[{c.name}] 拳手交了，任务 {QUEST} {q}（下一步：去梦幻岛找神仙姐姐）')


if __name__ == '__main__':
    try:
        args = sys.argv[1:]
        step = handin if args[:1] == ['--handin'] else take
        for n in [a for a in args if a != '--handin'] or ['十万2', '十万3']:
            step(t.Client(n))
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
