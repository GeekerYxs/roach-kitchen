"""5-man boss-gear line, 电锯杀人王 last step: the leader reports to 老刘 and takes the quest again (user 2026-11-06).

    python -X utf8 handin_chainsaw.py          (run go_laoliu.py first: it stops in reach of 老刘)

Live 2026-11-06 23:12 (4 roles): ★惊魂监狱的杀人狂［进行中］-> reward page (opening it already turns quest step 1 to
done, (2, 2)) ->「接受奖励」hands in for the whole team (quest gone, not in the finished list: repeatable) -> re-take
page「…我希望你能再次去那里调查…就能制造更多电锯杀人狂！」->「接受任务」(all four have it again, (1,)).
Like handin_gouzei.py: members not at the hand-in step leave the team first and are invited back afterwards.
MainTask 1852 reward: 12000 经验 + 1500 潜能 each. SHITU_CHAINSAW_AGAIN=0 does not re-take.
"""
import os

from _bootstrap import LEADER, ROLES

import chainsaw as cz
import tiger as tg
import trial_run as t
from provisioner import world as w
from take224 import talk
from take_eagle import DailyLimit, at_limit
from take_chainsaw import LIMIT

AGAIN = os.environ.get('SHITU_CHAINSAW_AGAIN', '1') != '0'
HAND_IN = ['惊魂监狱', '接受奖励']
RETAKE = ('接受任务',)


def retake(lead, d):
    """The re-take page after the reward (or one still open from an earlier run). True = today's cap hit."""
    if d is None:
        d = lead.dialog()
    if AGAIN and d:
        word = next((x for x in RETAKE if any(x in t.plain(l) for o, l in d.options if o)), None)
        if word:
            talk(lead, cz.LAOLIU, [word], d)
            return False
    return at_limit(lead)


def main():
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    if not any(cz.ready(c) for c in cs):
        d = lead.dialog()
        if d and not cz.has_quest(lead) and '电锯杀人狂' in t.plain(d.text):  # stopped on the re-take page
            limited = retake(lead, d)
            tg.close(lead)
            if limited:
                raise DailyLimit(LIMIT)
            t.say(f'[{LEADER}] 续接了「惊魂监狱的杀人狂」' if cz.has_quest(lead) else f'[{LEADER}] 没有续接')
            return
        t.say('没有人打完电锯杀人狂还没交，跳过')
        return
    if lead.world().map_id != cz.OUTER:
        raise t.Stop(f'{LEADER} 不在龙之都外城（map {lead.world().map_id}），先跑 go_laoliu.py')
    if not cz.ready(lead):
        raise t.Stop(f'{LEADER} 自己不在交任务这一步（任务 {cz.steps(lead)}），队员却在：手动看一下')
    for c in cs[1:]:
        if c.char_id in lead.team() and not cz.ready(c):
            t.say(f'[{c.name}] 不在交任务这一步（任务 {cz.steps(c)}），先离队，不然队长交不了')
            c.game.team_leave()
            t.wait(lambda: not c.team(), 5, f'{c.name} 离队')
    before = {c.name: w.read_level(c.mem) for c in cs}
    d = talk(lead, cz.LAOLIU, HAND_IN, tg.open_npc(lead, cz.LAOLIU, '老刘'))
    t.wait(lambda: not cz.ready(lead), 5, f'{LEADER} 交掉任务 1852')
    if d:
        t.say(f'交完以后的对话: {t.plain(d.text)} {[t.plain(l) for _, l in d.options]}')
    limited = retake(lead, d)
    tg.close(lead)
    t.say(f'[{LEADER}] 交了「惊魂监狱的杀人狂」，' +
          ('今天的次数用完了，没有续接' if limited else '已续接' if cz.has_quest(lead) else '没有续接'))
    t.say('等级: ' + str({c.name: (before[c.name], w.read_level(c.mem)) for c in cs}))
    tg.regroup(cs)
    if limited:
        raise DailyLimit(LIMIT)


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
