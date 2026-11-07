"""Take the 战士 转职 task 24「力量的考验」at 七十九万禁军教头 (NPC 304, 逍遥村就职所 map 8 (894,459)).

    python -X utf8 research/shitu/zhuanzhi_take.py 十万2 十万3                 take the task
    python -X utf8 research/shitu/zhuanzhi_take.py --handin 十万2 十万3       hand in the 拳手 step

Recorded 2026-10-27 01:54:57 (十万1 by hand, lv25, ANALYSIS.md section 11): ClickNpc(304) ->「成为战士」->「真的吗？」->
「可以！」->「接受任务。」-> 0x46ff「接受了任务：力量的考验 | 去夕阳草原杀死5只75kg级拳手」, quest tree 24/0 = 000001.
Hand-in (recorded 02:03:35, 十万1 by hand, after 「已经杀死了5个75Kg级拳手」— the quest tree does NOT show the kills,
it stays steps (0,0,1)): ClickNpc(304) ->「★力量的考验［进行中］」->「知道了！」-> steps (0,0,2,0,1) =
「去梦幻岛找神仙姐姐」. A role not at that step (3 step bytes; by count only, see progress.py) is skipped.
Skips a role whose task 24 is already active. Walks there from map 1 / 8 (navigate(8, ...) crosses 逍遥村 -> 就职所).
"""
import math
import os
import sys
import time

import progress
import trial_run as t
from bai_shi import mark
from provisioner import world as w
from take224 import talk

# env SHITU_JOB picks the class (2026-11-02 元素使 team: 术士). 术士 = task 25「悟性的考验」at 半吊法师留一手 305 (642,351),
# recorded live 元素使01 21:01: 成为术士 -> 你能教我吗？-> 继续。-> 但是什么…… -> 接受任务。(the server skips the table's
# 平静海岸 葫芦籽 / 虫洞法师 steps like it does for 24; next: 夕阳草原 水滴精灵 for 3 本《看我七十二变》)
JOBS = {
    '战士': (304, (894, 459), 24, ['成为战士', '真的吗', '可以', '接受任务'], '力量的考验'),
    '术士': (305, (642, 351), 25, ['成为术士', '你能教我', '继续', '但是什么', '接受任务'], '悟性的考验'),
}
JOB = os.environ.get('SHITU_JOB', '战士')
MAP = 8
NPC, XY, QUEST, STEPS, TITLE = JOBS[JOB]
# what the hand-in takes: 战士 the 5 拳手 kills (no item), 术士 3 本《看我七十二变》 (10549, shuidi.py)
ITEM_WORD, BOOKS = {'战士': ('拳手', None), '术士': ('魔法书', (10549, 3))}[JOB]


def go(c):
    st = c.world()
    if st.map_id == MAP and math.dist((st.x, st.y), XY) <= 80:
        return
    t.say(f'[{c.name}] 走去{JOB}导师 {XY}（现在 map {st.map_id} ({st.x:.0f},{st.y:.0f})）')
    c.game.navigate(MAP, XY[0], XY[1] + 40)
    t.wait(lambda: (s := c.world()) and s.map_id == MAP and math.dist((s.x, s.y), XY) <= 80 and not s.moving,
           90, f'{c.name} 走到{JOB}导师旁')


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
    t.say(f'[{c.name}] 接到转职任务 {QUEST} {TITLE} {q}')
    time.sleep(0.5)


def handin(c):
    # 2026-11-07 r4ys25: after a relog the server's bytes for the skipped steps are garbage ((0,2,1), (0,46,1) for
    # the same (0,0,1)), so the step is judged by the step count only (progress.py), never by the tuple
    q = w.read_quest(c.mem, QUEST)
    if progress.past(q, progress.CLASS_ITEMS + 1):
        t.say(f'[{c.name}] 任务 {QUEST} 已经交过{ITEM_WORD} {q}，跳过')
        return
    if not progress.at(q, progress.CLASS_ITEMS):
        t.say(f'[{c.name}] 任务 {QUEST} 不在交{ITEM_WORD}这一步 {q}，跳过')
        return
    if BOOKS and w.item_count(w.read_bag(c.mem), BOOKS[0]) < BOOKS[1]:
        # the step fails, the rerun farms again (shuidi.Books still counts this one); a talk now would hand in nothing
        raise t.Stop(f'{c.name} 《看我七十二变》不到 {BOOKS[1]} 本，交不了')
    go(c)
    talk(c, NPC, [TITLE, '知道了'])
    t.wait(lambda: progress.past(w.read_quest(c.mem, QUEST), progress.CLASS_ITEMS + 1), 5,
           f'{c.name} 任务 {QUEST} 进到下一步')
    time.sleep(0.6)
    q = w.read_quest(c.mem, QUEST)
    mark(c.name, 'zhuanzhi_quanshou', steps=list(q.steps))
    t.say(f'[{c.name}] {ITEM_WORD}交了，任务 {QUEST} {q}（下一步：去梦幻岛找神仙姐姐）')


if __name__ == '__main__':
    try:
        args = sys.argv[1:]
        step = handin if args[:1] == ['--handin'] else take
        for n in [a for a in args if a != '--handin'] or ['十万2', '十万3']:
            step(t.Client(n))
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
