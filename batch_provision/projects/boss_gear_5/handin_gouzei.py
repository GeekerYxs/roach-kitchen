"""5-man boss-gear line, 狗贼贼 last step: the leader reports to 皮克斯 and takes the quest again (user 2026-11-06).

    python -X utf8 handin_gouzei.py          (run go_kuwu2.py first: it stops in reach of 皮克斯)

Live 2026-11-06 21:55: 突出虫围［进行中］-> 接受报酬 (all five handed in at once, quest 819 not in the finished list:
repeatable) -> re-take page「…你可愿意再去让他领教你的厉害？」-> 非常乐意 (all five have it again). Like
handin_monkey.py, members not at the hand-in step leave the team first and are invited back afterwards.
MainTask 819 reward: 8010 经验 + 1290 潜能 each. SHITU_GOUZEI_AGAIN=0 does not re-take.
"""
import os

from _bootstrap import LEADER, ROLES

import gouzei as gz
import tiger as tg
import trial_run as t
from provisioner import world as w
from take224 import talk
from take_eagle import DailyLimit, at_limit

AGAIN = os.environ.get('SHITU_GOUZEI_AGAIN', '1') != '0'


def retake(lead, d):
    """The re-take page after the reward (or the one still open from an earlier run). True = today's cap hit."""
    if d is None:
        d = lead.dialog()
    if AGAIN and d and any('乐意' in t.plain(l) for _, l in d.options):
        talk(lead, gz.PIKES, ['乐意'], d)
        return False
    return at_limit(lead)


def main():
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    if not any(gz.ready(c) for c in cs):
        d = lead.dialog()
        if d and not gz.has_quest(lead) and '狗贼贼' in t.plain(d.text):       # stopped on the re-take page
            limited = retake(lead, d)
            tg.close(lead)
            if limited:
                raise DailyLimit('皮克斯说「已经超过今日挑战上限了」：今天的狗贼贼打满了')
            t.say(f'[{LEADER}] 续接了「突出虫围」' if gz.has_quest(lead) else f'[{LEADER}] 没有续接')
            return
        t.say('没有人在「告诉皮克斯」这一步，跳过')
        return
    if lead.world().map_id != gz.KUWU_2:
        raise t.Stop(f'{LEADER} 不在苦无沙漠2区（map {lead.world().map_id}），先跑 go_kuwu2.py')
    if not gz.ready(lead):
        raise t.Stop(f'{LEADER} 自己不在交任务这一步（任务 {gz.steps(lead)}），队员却在：手动看一下')
    for c in cs[1:]:
        if c.char_id in lead.team() and not gz.ready(c):
            t.say(f'[{c.name}] 不在交任务这一步（任务 {gz.steps(c)}），先离队，不然队长交不了')
            c.game.team_leave()
            t.wait(lambda: not c.team(), 5, f'{c.name} 离队')
    before = {c.name: w.read_level(c.mem) for c in cs}
    d = talk(lead, gz.PIKES, ['突出虫围', '接受报酬'], tg.open_npc(lead, gz.PIKES, '皮克斯'))
    t.wait(lambda: not gz.ready(lead), 5, f'{LEADER} 交掉任务 819')
    limited = retake(lead, d)
    tg.close(lead)
    t.say(f'[{LEADER}] 交了「突出虫围」，' +
          ('今天的次数用完了，没有续接' if limited else '已续接' if gz.has_quest(lead) else '没有续接'))
    t.say('等级: ' + str({c.name: (before[c.name], w.read_level(c.mem)) for c in cs}))
    tg.regroup(cs)
    if limited:
        raise DailyLimit('皮克斯说「已经超过今日挑战上限了」：今天的狗贼贼打满了')


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
