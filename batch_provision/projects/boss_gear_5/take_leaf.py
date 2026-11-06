"""5-man boss-gear line, 老树叶 step 2: take 传说中的老树叶 (quest 673) from 克拉苏 in 迷惑森林3区 (user 2026-11-06).

    python -X utf8 take_leaf.py          (run go_forest3.py first; the PP鸡 landing is in reach of 克拉苏)

Live 2026-11-06 19:05: ☆传说中的老树叶(48）-> 哇，这么麻烦？-> 放心这难不倒我的; the leader's accept gave the quest to
all five. Like take_tiger.py, a role still missing it leaves the team, takes it alone and is invited back (PhaseTask
673: every team member must have the quest). The daily cap is the eagle's sentence.
"""
import time

from _bootstrap import LEADER, ROLES

import leaf as lf
import tiger as tg
import trial_run as t
from take224 import talk
from take_eagle import DailyLimit, at_limit

WORDS = ['传说中的老树叶', '麻烦', '放心']


def take(c):
    try:
        talk(c, lf.KELASU, WORDS, tg.open_npc(c, lf.KELASU, '克拉苏'))
    except t.Stop:
        if at_limit(c):                       # the cap page may come in place of any of the pages
            raise DailyLimit('克拉苏说「已经超过今日挑战上限了」：今天的老树叶打满了')
        raise
    time.sleep(0.5)
    if at_limit(c):
        raise DailyLimit('克拉苏说「已经超过今日挑战上限了」：今天的老树叶打满了')
    t.wait(lambda: lf.has_quest(c), 5, f'{c.name} 接到任务 673')


def main():
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    if all(lf.has_quest(c) for c in cs):
        t.say('五人都已经接了「传说中的老树叶」，跳过')
        return
    if lead.world().map_id != lf.FOREST_3:
        raise t.Stop(f'{LEADER} 不在迷惑森林3区（map {lead.world().map_id}），先跑 go_forest3.py')
    if not lf.has_quest(lead):
        take(lead)                            # gives it to the whole team
        lf.new_round()
        try:
            t.wait(lambda: all(lf.has_quest(c) for c in cs), 3, '五人接到任务 673')
        except t.Stop:
            pass
    for c in cs[1:]:
        if not lf.has_quest(c):
            t.say(f'[{c.name}] 还没有任务，离队自己接')
            if c.team():
                c.game.team_leave()
                t.wait(lambda: not c.team(), 5, f'{c.name} 离队')
            take(c)
    tg.regroup(cs)
    t.say('五人都接到了「传说中的老树叶」（任务 673）')


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
