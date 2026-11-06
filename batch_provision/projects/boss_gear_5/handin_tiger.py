"""5-man boss-gear line, 虎力仙 last step: the leader reports to 银狐王勇 and takes the quest again (user 2026-11-06).

    python -X utf8 handin_tiger.py          (run go_desert2.py first; it puts the team next to 王勇)

Live 2026-11-06 16:50: ★玩死虎力仙［进行中］-> 领取奖励 -> (re-take page) 接受任务. The whole team hands in and re-takes
at once, BUT a team member without the quest makes the leader's pick close the dialog silently -> such members leave
the team first and are invited back afterwards. MainTask 1185 reward: 16980 经验 + 1860 潜能 each.
SHITU_TIGER_AGAIN=0 picks 拒绝任务 instead of re-taking.
"""
import os

from _bootstrap import LEADER, ROLES

import tiger as tg
import trial_run as t
from provisioner import world as w
from take224 import talk
from take_eagle import DailyLimit, at_limit

AGAIN = os.environ.get('SHITU_TIGER_AGAIN', '1') != '0'


def main():
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    if not any(tg.ready(c) for c in cs):
        t.say('没有人在「回荒芜之地2区找银狐王勇」这一步，跳过')
        return
    if lead.world().map_id != tg.DESERT_2:
        raise t.Stop(f'{LEADER} 不在荒芜之地2区（map {lead.world().map_id}），先跑 go_desert2.py')
    if not tg.ready(lead):
        raise t.Stop(f'{LEADER} 自己不在交任务这一步（任务 {tg.steps(lead)}），队员却在：手动看一下')
    for c in cs[1:]:
        if c.char_id in lead.team() and not tg.ready(c):
            t.say(f'[{c.name}] 不在交任务这一步（任务 {tg.steps(c)}），先离队，不然队长交不了')
            c.game.team_leave()
            t.wait(lambda: not c.team(), 5, f'{c.name} 离队')
    before = {c.name: w.read_level(c.mem) for c in cs}
    d = talk(lead, tg.WANGYONG, ['玩死虎力仙', '领取奖励'], tg.open_npc(lead, tg.WANGYONG, '银狐王勇'))
    t.wait(lambda: not tg.ready(lead), 5, f'{LEADER} 交掉任务 1185')
    limited = False
    if d is None:
        d = lead.dialog()
    if AGAIN and d and any('接受任务' in t.plain(l) for _, l in d.options):
        talk(lead, tg.WANGYONG, ['接受任务'], d)
    elif at_limit(lead):
        limited = True
    tg.close(lead)
    t.say(f'[{LEADER}] 交了「玩死虎力仙」，' +
          ('今天的次数用完了，没有续接' if limited else '已续接' if tg.has_quest(lead) else '没有续接'))
    t.say('等级: ' + str({c.name: (before[c.name], w.read_level(c.mem)) for c in cs}))
    tg.regroup(cs)
    if limited:
        raise DailyLimit('银狐王勇说「已经超过今日挑战上限了」：今天的虎力仙打满了')


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
