"""5-man boss-gear line, step 5: the leader tells 莫吉 (quest 1130 last step), the team takes the reward and the
quest again for the next round (user 2026-11-06: scroll home + PP鸡 back is faster than walking out of the cage).

    python -X utf8 handin_eagle.py          (run go_desert1.py first; it puts the team on 莫吉's doorstep)

Live 2026-11-06 13:27: 莫吉 menu「★让鹰王倒下［进行中］」is option 1 then (option 5 when it was untaken: pick by text)
-> 接受报酬 -> 没问题，非常乐意为您工作。 Each of the five got 14580 经验 + 1740 潜能 (MainTask row 1130) and the quest
again at once (steps back to (1,1,1,1)). SHITU_EAGLE_AGAIN=0 stops before the re-take page.
"""
import os

from _bootstrap import LEADER, ROLES

import trial_run as t
from provisioner import world as w
from take224 import talk

QUEST = 1130
MOJI = 2503
DESERT_1 = 180
EAGLE_STEP, REPORT_STEP, DONE = 3, 4, 2
AGAIN = os.environ.get('SHITU_EAGLE_AGAIN', '1') != '0'


def steps(c):
    q = w.read_quest(c.mem, QUEST)
    return q.steps if q and q.active else ()


def ready(c):                              # beat the eagle, not reported yet
    s = steps(c)
    return len(s) > REPORT_STEP and s[EAGLE_STEP] == DONE and s[REPORT_STEP] != DONE


def main():
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    if not any(ready(c) for c in cs):
        t.say('没有人在「回去告诉莫吉」这一步，跳过')
        return
    if lead.world().map_id != DESERT_1 or set(lead.team()) != {c.char_id for c in cs}:
        raise t.Stop(f'五人不在荒芜之地1区或队伍不全（map {lead.world().map_id}），先跑 go_desert1.py')
    exp = {c.name: w.read_level(c.mem) for c in cs}
    words = ['让鹰王倒下', '接受报酬'] + (['没问题'] if AGAIN else [])
    talk(lead, MOJI, words)
    t.wait(lambda: not any(ready(c) for c in cs), 5, '五人交掉任务 1130')
    t.say(f'[{LEADER}] 交了「让鹰王倒下」，' + ('五人已重新接上，下一轮从 enter_cage.py 开始' if AGAIN else '没有续接'))
    t.say('等级: ' + str({c.name: (exp[c.name], w.read_level(c.mem)) for c in cs}))


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
