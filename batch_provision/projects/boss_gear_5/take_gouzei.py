"""5-man boss-gear line, 狗贼贼 step 2: take 突出虫围 (quest 819) from 皮克斯 in 苦无沙漠2区 (user 2026-11-06).

    python -X utf8 take_gouzei.py          (run go_kuwu2.py first: it stops in reach of 皮克斯)

Live 2026-11-06 21:55 (from (2192,1480), 247 px, raw 0x50): the re-take page after the reward「…你可愿意再去让他领教你的
厉害？」-> 非常乐意 gave quest 819 to all five at once. Live 22:08, the first take: ☆突出虫围(43）-> two answers:「…不过看在
报酬的份上我会去做的。」takes it (all five);「你说到了我的强项…再见。」closes the dialog WITHOUT the quest.
Like take_monkey.py, a role still missing it leaves the team, takes it alone and is invited back (PhaseTask 819: every team member must have the quest).
"""
import time

from _bootstrap import LEADER, ROLES

import gouzei as gz
import tiger as tg
import trial_run as t
from take224 import talk
from take_eagle import DailyLimit, at_limit

WORDS = ['突出虫围', '报酬的份上']


def take(c):
    d = tg.open_npc(c, gz.PIKES, '皮克斯')
    if at_limit(c):
        raise DailyLimit('皮克斯说「已经超过今日挑战上限了」：今天的狗贼贼打满了')
    try:
        talk(c, gz.PIKES, WORDS, d)
    except t.Stop:
        if at_limit(c):                       # the cap page may come in place of any of the pages
            raise DailyLimit('皮克斯说「已经超过今日挑战上限了」：今天的狗贼贼打满了')
        raise
    time.sleep(0.5)
    if at_limit(c):
        raise DailyLimit('皮克斯说「已经超过今日挑战上限了」：今天的狗贼贼打满了')
    tg.close(c)
    t.wait(lambda: gz.has_quest(c), 5, f'{c.name} 接到任务 819')


def main():
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    if all(gz.has_quest(c) for c in cs):
        t.say('五人都已经接了「突出虫围」，跳过')
        return
    if lead.world().map_id != gz.KUWU_2:
        raise t.Stop(f'{LEADER} 不在苦无沙漠2区（map {lead.world().map_id}），先跑 go_kuwu2.py')
    if not gz.has_quest(lead):
        take(lead)                            # gives it to the whole team
        try:
            t.wait(lambda: all(gz.has_quest(c) for c in cs), 3, '五人接到任务 819')
        except t.Stop:
            pass
    for c in cs[1:]:
        if not gz.has_quest(c):
            t.say(f'[{c.name}] 还没有任务，离队自己接')
            if c.team():
                c.game.team_leave()
                t.wait(lambda: not c.team(), 5, f'{c.name} 离队')
            take(c)
    tg.regroup(cs)
    t.say('五人都接到了「突出虫围」（任务 819）')


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
