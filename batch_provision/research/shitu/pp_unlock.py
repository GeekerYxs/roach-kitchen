"""Disband the team, then each apprentice talks once to 传送操作员4号 (NPC 13, map 81 (1158,779)) and closes the
dialog without teleporting: the user says one talk opens the PP鸡 permission (2026-10-27).

    python -X utf8 research/shitu/pp_unlock.py [role ...]          (default: 十万1 十万2 十万3)

Done talks go to state.json (pp13_talk); a rerun skips them.
"""
import math
import sys
import time

import trial_run as t
from common import APPRENTICES, MASTERS
from bai_shi import done, mark

MAP, NPC, XY = 81, 13, (1158, 779)       # docs/LEVELING_STAGE0.md, NPCDirection.csv
NEAR = 80
MASTER = MASTERS[0]


def disband(cs):
    for c in cs:
        if c.team():
            t.say(f'[{c.name}] 退队 {c.team()}')
            c.game.team_leave()
    for c in cs:
        t.wait(lambda: not c.team(), 5, f'{c.name} 不在队里')
    t.say('队伍已解散')


def talk(c):
    st = c.world()
    if st.map_id != MAP:
        raise t.Stop(f'{c.name} 不在平静海岸2区 (map {st.map_id})')
    if math.dist((st.x, st.y), XY) > NEAR:
        t.say(f'[{c.name}] 走到传送操作员4号旁 {XY}（现在 {st.x:.0f},{st.y:.0f}）')
        c.game.navigate(MAP, *XY)
        t.wait(lambda: (s := c.world()) and math.dist((s.x, s.y), XY) <= NEAR and not s.moving, 30, '走到 NPC 13 旁')
    c.game.click_npc(NPC)
    d = t.wait(lambda: c.dialog(), 5, '传送操作员4号的对话框')
    t.say(f'[{c.name}] 对话: {t.body(d)[:80]} 选项 {d.options}')
    c.game.select_dialog(0)                 # 离开: no teleport
    t.wait(lambda: not c.dialog(), 5, '关掉对话框')
    mark(c.name, 'pp13_talk', npc=NPC, options=[l for _, l in d.options])
    t.say(f'[{c.name}] 已和传送操作员4号对话，没有传送')


def main(names):
    cs = {n: t.Client(n) for n in MASTERS + tuple(names)}
    disband(cs.values())
    for n in names:
        if done(n, 'pp13_talk'):
            t.say(f'[{n}] state.json 记着已对话过，跳过')
            continue
        talk(cs[n])
        time.sleep(0.5)


if __name__ == '__main__':
    try:
        main(sys.argv[1:] or list(APPRENTICES))
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
