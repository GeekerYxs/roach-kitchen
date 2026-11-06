"""5-man boss-gear line, 金刚猴 step 2: take 金刚猴的挑战书 (quest 518) from 龙上利 in 迷惑森林1区 (user 2026-11-06).

    python -X utf8 take_monkey.py          (run go_forest1.py first: it stops in reach of 龙上利)

Live 2026-11-06 20:17 (from (1504,264), 251 px, raw 0x50): ☆变形金猴的挑战书(38）-> 什么事情？-> 没问题，不过……报酬
方面…… -> 等着我的好消息吧！; the leader's accept gave quest 518 to all five at once. Like take_leaf.py, a role still
missing it leaves the team, takes it alone and is invited back (PhaseTask 518: every team member must have the quest).
"""
import time

from _bootstrap import LEADER, ROLES

import monkey as mk
import tiger as tg
import trial_run as t
from take224 import talk
from take_eagle import DailyLimit, at_limit

WORDS = ['变形金猴', '什么事情', '报酬', '好消息']


def take(c):
    try:
        talk(c, mk.LONG, WORDS, tg.open_npc(c, mk.LONG, '龙上利'))
    except t.Stop:
        if at_limit(c):                       # the cap page may come in place of any of the pages
            raise DailyLimit('龙上利说「已经超过今日挑战上限了」：今天的金刚猴打满了')
        raise
    time.sleep(0.5)
    if at_limit(c):
        raise DailyLimit('龙上利说「已经超过今日挑战上限了」：今天的金刚猴打满了')
    t.wait(lambda: mk.has_quest(c), 5, f'{c.name} 接到任务 518')


def main():
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    if all(mk.has_quest(c) for c in cs):
        t.say('五人都已经接了「金刚猴的挑战书」，跳过')
        return
    if lead.world().map_id != mk.FOREST_1:
        raise t.Stop(f'{LEADER} 不在迷惑森林1区（map {lead.world().map_id}），先跑 go_forest1.py')
    if not mk.has_quest(lead):
        take(lead)                            # gives it to the whole team
        try:
            t.wait(lambda: all(mk.has_quest(c) for c in cs), 3, '五人接到任务 518')
        except t.Stop:
            pass
    for c in cs[1:]:
        if not mk.has_quest(c):
            t.say(f'[{c.name}] 还没有任务，离队自己接')
            if c.team():
                c.game.team_leave()
                t.wait(lambda: not c.team(), 5, f'{c.name} 离队')
            take(c)
    tg.regroup(cs)
    t.say('五人都接到了「金刚猴的挑战书」（任务 518）')


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
