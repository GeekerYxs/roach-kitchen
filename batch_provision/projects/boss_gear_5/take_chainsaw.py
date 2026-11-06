"""5-man boss-gear line, 电锯杀人王 step 2: take 惊魂监狱的杀人狂 (quest 1852) from 老刘 in 龙之都外城 (user 2026-11-06).

    python -X utf8 take_chainsaw.py          (run go_laoliu.py first: it stops in reach of 老刘)

The menu pages are picked by the words in WORDS (take224.talk). Like take_gouzei.py, a role still missing the quest
leaves the team, takes it alone and is invited back (in a team every member must have it).
"""
import time

from _bootstrap import LEADER, ROLES

import chainsaw as cz
import tiger as tg
import trial_run as t
from take224 import talk
from take_eagle import DailyLimit, at_limit

WORDS = ['惊魂监狱', '接受']
LIMIT = '老刘说「已经超过今日挑战上限了」：今天的电锯杀人王打满了'


def take(c):
    d = tg.open_npc(c, cz.LAOLIU, '老刘')
    if at_limit(c):
        raise DailyLimit(LIMIT)
    try:
        talk(c, cz.LAOLIU, WORDS, d)
    except t.Stop:
        if at_limit(c):                       # the cap page may come in place of any of the pages
            raise DailyLimit(LIMIT)
        raise
    time.sleep(0.5)
    if at_limit(c):
        raise DailyLimit(LIMIT)
    tg.close(c)
    t.wait(lambda: cz.has_quest(c), 5, f'{c.name} 接到任务 1852')


def main():
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    if all(cz.has_quest(c) for c in cs):
        t.say('全队都已经接了「惊魂监狱的杀人狂」，跳过')
        return
    if lead.world().map_id != cz.OUTER:
        raise t.Stop(f'{LEADER} 不在龙之都外城（map {lead.world().map_id}），先跑 go_laoliu.py')
    if not cz.has_quest(lead):
        take(lead)                            # gives it to the whole team
        try:
            t.wait(lambda: all(cz.has_quest(c) for c in cs), 3, '全队接到任务 1852')
        except t.Stop:
            pass
    for c in cs[1:]:
        if not cz.has_quest(c):
            t.say(f'[{c.name}] 还没有任务，离队自己接')
            if c.team():
                c.game.team_leave()
                t.wait(lambda: not c.team(), 5, f'{c.name} 离队')
            take(c)
    tg.regroup(cs)
    t.say('全队都接到了「惊魂监狱的杀人狂」（任务 1852）')


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
