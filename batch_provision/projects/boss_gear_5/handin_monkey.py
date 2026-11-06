"""5-man boss-gear line, 金刚猴 last step: the leader reports to 龙上利 and takes the quest again (user 2026-11-06).

    python -X utf8 handin_monkey.py          (run go_forest1.py first: it stops in reach of 龙上利)

Live 2026-11-06 20:33: 变形金猴的挑战书［进行中］-> 接受奖励 (all five handed in at once) -> re-take page「…再次去秘密宝窟
教训他一顿吧！」-> 接受. Like handin_leaf.py, members not at the hand-in step leave the team first (the tiger's rule: one
such member makes the leader's pick close the dialog) and are invited back afterwards.
MainTask 518 reward: 5400 经验 + 950 潜能 each. SHITU_MONKEY_AGAIN=0 does not re-take.
"""
import os

from _bootstrap import LEADER, ROLES

import monkey as mk
import tiger as tg
import trial_run as t
from provisioner import world as w
from take224 import talk
from take_eagle import DailyLimit, at_limit

AGAIN = os.environ.get('SHITU_MONKEY_AGAIN', '1') != '0'


def retake(lead, d):
    """The re-take page after the reward (or the one still open from an earlier run). True = today's cap hit."""
    if d is None:
        d = lead.dialog()
    if AGAIN and d and any(t.plain(l) == '接受' or '接受任务' in t.plain(l) for _, l in d.options):
        talk(lead, mk.LONG, ['接受'], d)
        return False
    return at_limit(lead)


def main():
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    if not any(mk.ready(c) for c in cs):
        d = lead.dialog()
        if d and not mk.has_quest(lead) and '秘密宝窟' in t.plain(d.text):     # stopped on the re-take page
            limited = retake(lead, d)
            tg.close(lead)
            if limited:
                raise DailyLimit('龙上利说「已经超过今日挑战上限了」：今天的金刚猴打满了')
            t.say(f'[{LEADER}] 续接了「金刚猴的挑战书」' if mk.has_quest(lead) else f'[{LEADER}] 没有续接')
            return
        t.say('没有人在「告诉龙上利」这一步，跳过')
        return
    if lead.world().map_id != mk.FOREST_1:
        raise t.Stop(f'{LEADER} 不在迷惑森林1区（map {lead.world().map_id}），先跑 go_forest1.py')
    if not mk.ready(lead):
        raise t.Stop(f'{LEADER} 自己不在交任务这一步（任务 {mk.steps(lead)}），队员却在：手动看一下')
    for c in cs[1:]:
        if c.char_id in lead.team() and not mk.ready(c):
            t.say(f'[{c.name}] 不在交任务这一步（任务 {mk.steps(c)}），先离队，不然队长交不了')
            c.game.team_leave()
            t.wait(lambda: not c.team(), 5, f'{c.name} 离队')
    before = {c.name: w.read_level(c.mem) for c in cs}
    d = talk(lead, mk.LONG, ['挑战书', '接受奖励'], tg.open_npc(lead, mk.LONG, '龙上利'))
    t.wait(lambda: not mk.ready(lead), 5, f'{LEADER} 交掉任务 518')
    limited = retake(lead, d)
    tg.close(lead)
    t.say(f'[{LEADER}] 交了「金刚猴的挑战书」，' +
          ('今天的次数用完了，没有续接' if limited else '已续接' if mk.has_quest(lead) else '没有续接'))
    t.say('等级: ' + str({c.name: (before[c.name], w.read_level(c.mem)) for c in cs}))
    tg.regroup(cs)
    if limited:
        raise DailyLimit('龙上利说「已经超过今日挑战上限了」：今天的金刚猴打满了')


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
