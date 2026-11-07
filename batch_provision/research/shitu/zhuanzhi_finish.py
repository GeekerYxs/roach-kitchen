"""Finish the 战士 转职 at 神仙姐姐 in 梦幻岛 (map 270) and come back to 逍遥村西区.

    python -X utf8 research/shitu/zhuanzhi_finish.py 十万2 十万3

Recorded 2026-10-27 02:06:38 (十万1 by hand, ANALYSIS.md section 11.2), every step a plain NPC dialog:
  map 1 传送门 NPC 10213 (1338,1053)「梦幻岛」-> map 270 lands (1098,579)
  神仙姐姐 NPC 1 (1374,628):「★力量的考验［进行中］」->「我宣誓……」->「继续。」->「好的」
      -> 0x46ff「职业变更了，现在是战士了」「任务：力量的考验完成了」(task 24 done) + 新手洗点卡, 1000 exp, 210 潜能
      ->「你已经是一个优秀的战士了…」「接受」-> task 107「光荣的使命」(the user accepted it, so do we)
  map 270 传送门 NPC 23 (954,507)「逍遥村西区」-> map 1 (1110,1173)
Precondition: task 24 at steps (0,0,2,0,1) (checked by the step count only, see progress.py). A role with task 24
done skips the 神仙姐姐 part.
"""
import math
import sys
import time

import progress
import trial_run as t
from bai_shi import mark
from provisioner import world as w
from take224 import talk
from zhuanzhi_take import JOB, QUEST, TITLE

# 术士 (live 元素使01 2026-11-02 21:14): 悟性的考验［进行中］->「我宣誓……」->「继续。」->「谢谢！」-> task 25 done ->
#「你已经是一个优秀的术士了…」「接受」-> task 107; the 战士 page has「好的」where the 术士 one has「谢谢！」
OATH = {'战士': ['我宣誓', '继续', '好的'], '术士': ['我宣誓', '继续', '谢谢']}[JOB]

ISLAND = 270
GATE_VILLAGE, GATE_VILLAGE_XY = 10213, (1338, 1053)
FAIRY, FAIRY_XY = 1, (1374, 628)
GATE_ISLAND, GATE_ISLAND_XY = 23, (954, 507)
NEAR = 80


def walk(c, map_id, xy, why):
    st = c.world()
    if st.map_id == map_id and math.dist((st.x, st.y), xy) <= NEAR:
        return
    t.say(f'[{c.name}] 走去{why} {xy}')
    c.game.navigate(map_id, *xy)
    t.wait(lambda: (s := c.world()) and s.map_id == map_id and math.dist((s.x, s.y), xy) <= NEAR and not s.moving,
           60, f'{c.name} 走到{why}')


def gate(c, npc, xy, map_from, label, map_to):
    walk(c, map_from, xy, f'传送门 {npc}')
    talk(c, npc, [label])
    t.wait(lambda: (s := c.world()) and s.map_id == map_to, 10, f'{c.name} 传送到 map {map_to}')
    s = c.world()
    t.say(f'[{c.name}] 传送门「{label}」-> map {map_to} ({s.x:.0f},{s.y:.0f})')


def finish(c):
    q = w.read_quest(c.mem, QUEST)
    if not q.done:
        # by the step count (5 bytes) only: 2026-11-07 r4ys25 read (0,2,2,0,1) / (0,46,2,3,1) after a relog (progress.py)
        if not progress.at(q, progress.CLASS_FAIRY):
            raise t.Stop(f'{c.name} 任务 {QUEST} 不在「去梦幻岛找神仙姐姐」这一步: {q}')
        if c.world().map_id != ISLAND:
            gate(c, GATE_VILLAGE, GATE_VILLAGE_XY, 1, '梦幻岛', ISLAND)
        walk(c, ISLAND, FAIRY_XY, '神仙姐姐')
        d = talk(c, FAIRY, [TITLE] + OATH)
        t.wait(lambda: w.read_quest(c.mem, QUEST).done, 5, f'{c.name} 任务 {QUEST} 完成')
        d = t.wait(lambda: c.dialog(), 5, f'「你已经是一个优秀的{JOB}了」')
        if '接受' in [l for _, l in d.options]:
            c.game.select_dialog(t.pick(d, '接受'))
            t.wait(lambda: w.read_quest(c.mem, 107).active, 5, f'{c.name} 接到任务 107 光荣的使命')
        mark(c.name, 'zhuanzhi_done', job=JOB, quest107=str(w.read_quest(c.mem, 107)))
        t.say(f'[{c.name}] 转职成{JOB}，任务 {QUEST} {w.read_quest(c.mem, QUEST)}，任务 107 {w.read_quest(c.mem, 107)}')
        time.sleep(0.5)
    if c.world().map_id == ISLAND:
        gate(c, GATE_ISLAND, GATE_ISLAND_XY, ISLAND, '逍遥村西区', 1)


if __name__ == '__main__':
    try:
        for n in sys.argv[1:] or ['十万2', '十万3']:
            finish(t.Client(n))
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
