"""Kill 地头蛇 (task 224 step 1) with 伏地魔1's 5-man team, already in 遗忘洞穴 (map 750), then stop.

    python -X utf8 research/shitu/dts.py

Recorded 2026-10-26 23:21 (欧皇, GATHER.md 5c): every member must have task 224; only the leader's 遗忘之花/石 count
(all taken on a win). Steps:
  1. walk to 蛇王卧室入口 NPC 10214 (3306,6183) (maze_train goal stage: random battles are fought on the way)
  2. ClickNpc(10214): no dialog, the whole team jumps to (4194,8157) in the same map
  3. ClickNpc(1172 地头蛇) ->「啊哈！新鲜的肉！…」opt 1 -> battle. The anti-bot quiz 0x46f5 may pop up instead
     (live 23:21:54); that is the quizbot's business: wait until it is gone, then click again (up to 4 times)
  4. 伏地魔1/2 cast 扫射 + 烈焰爆发 (lunhui15.Caster) until the battle ends
  5. report task 224 of all 5 (expected steps (2,1)) and the leader's flowers / stones
"""
import math
import os
import time

import maze_train as m
from lunhui15 import CASTERS, LEADER, MEMBERS, Caster
from provisioner import world as w

t = m.t
DOOR, DOOR_XY, ROOM_XY = 10214, (3306, 6183), (4194, 8157)
LAYER2, LAYER2_XY = 10190, (2304, 1320)      # user 2026-10-27: go to (2300,1300) first = the passage to 二层; the
                                             # path-finder cannot reach the door from the upper part (stuck 02:41)
LOWER_Y = 4000                               # 二层 = lower part of map 750 (dark flowers y 4121..7841)
SNAKE = 1172
FLOWER, STONE = 11150, 11151


def main():
    lead = t.Client(LEADER)
    st = lead.world()
    if math.dist((st.x, st.y), ROOM_XY) > 600:
        if st.y < LOWER_Y:
            m.STAGES = (dict(name='二层通道', goal=(750, LAYER2_XY), maze=None, until=None, patrol_b=None, legs={}),)
            m.main()
            st = lead.world()
            t.say(f'[{LEADER}] 到二层通道 ({st.x:.0f},{st.y:.0f})，点 NPC {LAYER2}')
            lead.game.click_npc(LAYER2)
            t.wait(lambda: lead.world().y > LOWER_Y or lead.dialog(), 8, '进二层')
            d = lead.dialog()
            if d:
                t.say(f'[{LEADER}] 二层通道对话: {t.body(d)[:60]} {d.options}')
                lead.game.select_dialog(next(o for o, _ in d.options if o))
                t.wait(lambda: lead.world().y > LOWER_Y, 8, '进二层')
            st = lead.world()
            t.say(f'[{LEADER}] 进了二层 ({st.x:.0f},{st.y:.0f})')
            time.sleep(1.5)
        m.STAGES = (dict(name='蛇王卧室入口', goal=(750, DOOR_XY), maze=None, until=None, patrol_b=None, legs={}),)
        m.main()
        lead.game.click_npc(DOOR)
        t.wait(lambda: math.dist(((s := lead.world()).x, s.y), ROOM_XY) <= 300, 8, '传进蛇王卧室')
        time.sleep(1.5)
    cs = [t.Client(n) for n in (LEADER,) + MEMBERS]
    for c in cs:
        s = c.world()
        t.say(f'[{c.name}] 卧室 ({s.x:.0f},{s.y:.0f}) 任务224 {w.read_quest(c.mem, 224)}')
    bag = w.read_bag(lead.mem)
    t.say(f'[{LEADER}] 遗忘之花 {w.item_count(bag, FLOWER)}，遗忘之石 {w.item_count(bag, STONE)}')
    casters = [Caster(c) for c in cs if c.name in CASTERS]
    for attempt in range(1, 5):
        lead.game.click_npc(SNAKE)
        d = t.wait(lambda: lead.dialog() or lead.world().in_battle, 5, '地头蛇的对话')
        if d is True or getattr(d, 'options', None) is None:
            break
        t.say(f'[{LEADER}] 地头蛇: {t.body(d)[:60]} 选项 {d.options}')
        lead.game.select_dialog(d.options[0][0])
        end = time.monotonic() + 15
        while time.monotonic() < end and not lead.world().in_battle:
            time.sleep(0.2)
        if lead.world().in_battle:
            break
        st = lead.world()
        if st.dialog:
            raise t.Stop(f'地头蛇不肯开打: {t.body(st.dialog)} {st.dialog.options}')
        if os.environ.get('SHITU_DTS_ONCE') == '1':     # round 3: stop at once, the user answers the 0x46f5 by hand
            raise t.Stop(f'没开打（多半是反外挂答题 0x46f5，验证中={st.verification}），等用户手动答完再重跑')
        t.say(f'第 {attempt} 次没开打（可能是反外挂答题 0x46f5，验证中={st.verification}），等它结束再点')
        t.wait(lambda: not lead.world().verification, 120, '反外挂答题结束')
        time.sleep(1)
    else:
        raise t.Stop('点了 4 次地头蛇都没开打')
    t.say('和地头蛇开打')
    t0 = time.monotonic()
    while lead.world().in_battle:
        now = time.monotonic()
        for c in casters:
            if c.c.world().in_battle:
                c.tick(now)
        time.sleep(m.TICK)
        if now - t0 > 600:
            raise t.Stop('地头蛇打了 10 分钟还没结束')
    time.sleep(2)
    t.say(f'战斗结束，用时 {time.monotonic() - t0:.0f}s')
    for c in cs:
        t.say(f'[{c.name}] 任务224 {w.read_quest(c.mem, 224)}')
    bag = w.read_bag(lead.mem)
    t.say(f'[{LEADER}] 遗忘之花 {w.item_count(bag, FLOWER)}，遗忘之石 {w.item_count(bag, STONE)}')


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
