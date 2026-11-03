"""189: the 土之微尘 (10721) from 土拨鼠 in 秘密宝窟 (850), for every apprentice (元素使 route).

    python -X utf8 research/shitu/mole.py MASTER APP ...          (the team in 迷惑森林1区 150 or already in 850)

Live 2026-11-03 02:40-03:07: 150 entrance NPC 10170 (212,211), a click sends the team in (maze_train npc leg);
土拨鼠 1133 at (474,3891). Each apprentice first talks to it alone up to the fight page (元素使的考验 -> 弄醒它。->
能给我土之微尘吗？->「伤心地离开」): that activates its share (189 slot 6 -> 1). Then an apprentice still without
dust leads the team,「那只好抢了」, the master fights the pets (~9 s). The dust then lands in the bag of whoever has
room (02 / 04 got none with 40/40 bags), and the 土拨鼠 is back only ~4.5 min after a fight: free bag slots first,
then fight again with a leader that still lacks it.
"""
import sys
import time

import boss_fight
import farm
import maze_train as m
import trial_run as t
from factory.items import load_items
from provisioner import world as w

DUST, MOLE, XY, TRIES, BACK = 10721, 1133, (474, 3891), 8, 300


def go_in():
    m.STAGES = (dict(name='秘密宝窟 土拨鼠', goal=(850, XY), maze=None, until=None, patrol_b=None,
                     legs={150: ('npc', 10170, (212, 211))}),)
    m.main()


def activate(name):
    c = t.Client(name)
    if c.team():
        c.game.team_leave()
        t.wait(lambda: not c.team(), 5, f'{name} 离队')
    if c.dialog():
        c.game.select_dialog(0)
        time.sleep(0.5)
    c.game.click_npc(MOLE)
    t.wait(lambda: c.dialog(), 5, f'{name} 土拨鼠')
    last, end = None, time.monotonic() + 15
    while time.monotonic() < end and c.dialog():
        d = c.dialog()
        if d.text + str(d.options) != last:
            hit = [(o, l) for o, l in d.options if o and any(k in t.plain(l) for k in
                                                              ('元素使的考验', '弄醒', '能给我', '伤心地离开'))]
            if not hit:
                break
            last = d.text + str(d.options)
            c.game.select_dialog(hit[0][0])
            if '伤心' in t.plain(hit[0][1]):
                break
        time.sleep(0.3)
    t.say(f'[{name}] 土拨鼠激活，189 {w.read_quest(c.mem, 189).steps}')


def main(master, apps):
    if t.Client(master).world().map_id != 850:
        go_in()
    items = load_items()
    have = lambda n: w.item_count(w.read_bag(t.Client(n).mem), DUST)     # noqa: E731
    t.each([n for n in apps if not have(n)], activate)
    for k in range(TRIES):
        lacking = [n for n in apps if not have(n)]
        if not lacking:
            break
        for n in lacking:                       # a full bag silently loses the dust
            c = t.Client(n)
            if w.read_bag_capacity(c.mem) - len(w.read_bag(c.mem)) < farm.MIN_FREE:
                farm.make_room(c, items)
        end = time.monotonic() + BACK
        while not boss_fight.fight(lacking[0], MOLE, ['元素使的考验', '弄醒', '能给我', '那只好抢了'], master, apps):
            if time.monotonic() > end:
                raise t.Stop(f'土拨鼠 {BACK}s 都没打起来')
            time.sleep(20)                      # it comes back ~4.5 min after the last fight
        t.say(f'第 {k + 1} 场：' + ' '.join(f'{n} {have(n)}' for n in apps))
    lacking = [n for n in apps if not have(n)]
    if lacking:
        raise t.Stop(f'{TRIES} 场后还没有土之微尘: {lacking}')


if __name__ == '__main__':
    try:
        main(sys.argv[1], sys.argv[2:])
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
