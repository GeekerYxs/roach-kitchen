"""5-man boss-gear line, 虎力仙 step 2: take 玩死虎力仙 (quest 1185) from 银狐王勇 (user 2026-11-06).

    python -X utf8 take_tiger.py          (run go_desert2.py first; it puts the team next to 王勇)

Live 2026-11-06: menu ☆玩死虎力仙(62）［未接受］-> 继续 -> 接受任务. The leader accepting gives the quest to every team
member (4 took it at once). A role that is still missing it (e.g. it was out of the team) leaves the team, takes it
alone standing where it is (王勇 answers from ~200 px) and is invited back. The daily cap is the eagle's sentence.
"""
import time

from _bootstrap import LEADER, ROLES

import tiger as tg
import trial_run as t
from take224 import talk
from take_eagle import DailyLimit, at_limit

WORDS = ['玩死虎力仙', '继续', '接受任务']


def take(c):
    talk(c, tg.WANGYONG, WORDS, tg.open_npc(c, tg.WANGYONG, '银狐王勇'))
    time.sleep(0.5)
    if at_limit(c):
        raise DailyLimit('银狐王勇说「已经超过今日挑战上限了」：今天的虎力仙打满了')
    t.wait(lambda: tg.has_quest(c), 5, f'{c.name} 接到任务 1185')


def main():
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    if all(tg.has_quest(c) for c in cs):
        t.say('五人都已经接了「玩死虎力仙」，跳过')
        return
    if lead.world().map_id != tg.DESERT_2:
        raise t.Stop(f'{LEADER} 不在荒芜之地2区（map {lead.world().map_id}），先跑 go_desert2.py')
    if not tg.has_quest(lead):
        take(lead)                            # gives it to the whole team
        try:
            t.wait(lambda: all(tg.has_quest(c) for c in cs), 3, '五人接到任务 1185')
        except t.Stop:
            pass
    for c in cs[1:]:
        if not tg.has_quest(c):
            t.say(f'[{c.name}] 还没有任务，离队自己接')
            c.game.team_leave()
            t.wait(lambda: not c.team(), 5, f'{c.name} 离队')
            take(c)
    tg.regroup(cs)
    t.say('五人都接到了「玩死虎力仙」（任务 1185）')


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
