"""Task 224「遗忘洞穴的恐慌」at 大个王 + the 外城传送员 trip to 无尽2路口, recorded 2026-10-27 01:33 (伏地魔1, GATHER.md 7).

    python -X utf8 research/shitu/take224.py [--disband] role [role ...]

Per role, alone (a team is checked as a whole: 「有人等级不足无法接受任务哟！」when any member is below 28):
  1. not at 大个王 and task 224 not active yet -> 飞鞋 (if its record is next to 大个王) else walk there
  2. ClickNpc(557) ->「遗忘洞穴的恐慌(28)」->「我愿意接受这个光荣的任务」->「包在我身上！」-> task 224 active
  3. 外城传送员 740 (4744,2468)「龙之都外城中心 50金币」-> lands (3736,1220);
     外城传送员 743 (3610,1347)「传送服务」->「无尽2路口 50金币」-> lands (792,2692). All on map 20.
--disband: everybody in the given roles' teams leaves first.
"""
import math
import sys
import time

import trial_run as t
from common import APPRENTICES, MASTERS
from bai_shi import mark
from provisioner import world as w

MAP = 20                                   # 龙之都外城
BOSS, BOSS_XY = 557, (4398, 2553)          # 大个王
TP1, TP1_XY, TP1_LABEL, TP1_LAND = 740, (4744, 2468), '龙之都外城中心', (3736, 1220)
TP2, TP2_XY, TP2_LABEL, TP2_LAND = 743, (3610, 1347), '无尽2路口', (792, 2692)
NEAR = 80


def plain(label):
    return t.plain(label)


def pick_text(d, word):
    hits = [(o, l) for o, l in d.options if word in plain(l)]
    if len(hits) != 1:
        raise t.Stop(f'选项里找不到唯一的「{word}」: {d.options}')
    return hits[0]


def walk(c, xy, why):
    st = c.world()
    if st.map_id != MAP:
        raise t.Stop(f'{c.name} 不在龙之都外城 (map {st.map_id})')
    if math.dist((st.x, st.y), xy) <= NEAR:
        return
    t.say(f'[{c.name}] 走去{why} {xy}（距离 {math.dist((st.x, st.y), xy):.0f}）')
    end, last, last_t = time.monotonic() + 120, None, time.monotonic()
    c.game.navigate(MAP, *xy)
    while time.monotonic() < end:
        st = c.world()
        if st.in_battle:
            last_t = time.monotonic()
        elif math.dist((st.x, st.y), xy) <= NEAR and not st.moving:
            return
        elif (round(st.x), round(st.y)) != last:
            last, last_t = (round(st.x), round(st.y)), time.monotonic()
        elif time.monotonic() - last_t > 5:
            c.game.navigate(MAP, *xy)
            last_t = time.monotonic()
        time.sleep(0.2)
    raise t.Stop(f'{c.name} 120s 没走到{why}')


def talk(c, npc, steps):
    """ClickNpc(npc), then pick the option containing each word in `steps` in turn."""
    c.game.click_npc(npc)
    d = t.wait(lambda: c.dialog(), 5, f'NPC {npc} 的对话框')
    for word in steps:
        opt, label = pick_text(d, word)
        t.say(f'[{c.name}]   选 opt={opt}「{plain(label)}」')
        before = d.text
        c.game.select_dialog(opt)
        time.sleep(0.4)
        d = c.dialog()
        if d and d.text == before:
            d = t.wait(lambda: (x := c.dialog()) and x.text != before and x, 5, f'选「{word}」后的对话')
    return d


def to_boss(c):
    st = c.world()
    if st.map_id == MAP and math.dist((st.x, st.y), BOSS_XY) <= NEAR:
        return
    rec = w.read_shoe_record(c.mem)
    if rec and rec[0] == MAP and math.dist(rec[1:], BOSS_XY) <= 300:
        t.say(f'[{c.name}] 用飞鞋回大个王（记录点 {rec}）')
        c.game.shoe_return()
        time.sleep(1.5)
        st = c.world()
        if math.dist((st.x, st.y), rec[1:]) <= 30:
            t.say(f'[{c.name}] 飞鞋到了 ({st.x:.0f},{st.y:.0f})')
        else:
            t.say(f'[{c.name}] 飞鞋没生效（现在 {st.x:.0f},{st.y:.0f}），走过去')
    walk(c, BOSS_XY, '大个王')


def hand_in(c):
    """224 at (2,1) (snake already killed): 大个王 ->「遗忘洞穴的恐慌［进行中］」->「领取奖励」(round 2, 05:10: +3290 exp,
    no gold, the task is gone and can be taken again at once). Used instead of the task panel's 中断任务 (no packet known)."""
    to_boss(c)
    t.say(f'[{c.name}] 任务 224 停在 {w.read_quest(c.mem, 224)}，先去大个王交掉')
    d = talk(c, BOSS, ['遗忘洞穴的恐慌', '领取奖励'])
    t.wait(lambda: not w.read_quest(c.mem, 224).active, 5, '任务 224 交掉')
    if d:
        c.game.select_dialog(0)
        time.sleep(0.5)
    mark(c.name, 'handin224')
    t.say(f'[{c.name}] 任务 224 已交掉 {w.read_quest(c.mem, 224)}')


def take(c):
    q = w.read_quest(c.mem, 224)
    if q.active and tuple(q.steps) == (2, 1):
        hand_in(c)
    if w.read_quest(c.mem, 224).active:
        t.say(f'[{c.name}] 任务 224 已经接了 {w.read_quest(c.mem, 224)}')
        return
    to_boss(c)
    d = talk(c, BOSS, ['遗忘洞穴的恐慌', '我愿意接受', '包在我身上'])
    t.wait(lambda: w.read_quest(c.mem, 224).active, 5, '任务 224 变成进行中')
    if d:
        c.game.select_dialog(0)
    mark(c.name, 'task224', quest=str(w.read_quest(c.mem, 224)))
    t.say(f'[{c.name}] 接到任务 224 {w.read_quest(c.mem, 224)}')


def teleport(c):
    st = c.world()
    if math.dist((st.x, st.y), TP2_LAND) <= 400:
        t.say(f'[{c.name}] 已在无尽2路口 ({st.x:.0f},{st.y:.0f})')
        return
    for npc, xy, steps, land in ((TP1, TP1_XY, [TP1_LABEL], TP1_LAND),
                                 (TP2, TP2_XY, ['传送服务', TP2_LABEL], TP2_LAND)):
        if npc == TP1 and math.dist((st.x, st.y), TP2_XY) < math.dist((st.x, st.y), TP1_XY):
            continue                      # already in the city centre: skip the first hop
        walk(c, xy, f'外城传送员 {npc}')
        gold = w.read_gold(c.mem)
        talk(c, npc, steps)
        t.wait(lambda: math.dist(((s := c.world()).x, s.y), land) <= 60, 6, f'传送到 {land}')
        s = c.world()
        t.say(f'[{c.name}] 传送到 ({s.x:.0f},{s.y:.0f})，金币 {gold} -> {w.read_gold(c.mem)}')
        st = s


def main(argv):
    disband = '--disband' in argv
    names = [a for a in argv if a != '--disband'] or ['伏地魔1']
    cs = [t.Client(n) for n in names]
    if disband:
        team = set(cs[0].team())
        others = [n for n in MASTERS + APPRENTICES if n not in names]
        allc = cs + [t.Client(n) for n in others]
        for c in allc:
            if c.team():
                c.game.team_leave()
        for c in allc:
            t.wait(lambda: not c.team(), 5, f'{c.name} 离队')
        t.say(f'队伍已解散（原来 {sorted(team)}）')
    for c in cs:
        if c.team():
            raise t.Stop(f'{c.name} 还在队里 {c.team()}，单独接任务要先离队（加 --disband）')
        take(c)
        teleport(c)


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
