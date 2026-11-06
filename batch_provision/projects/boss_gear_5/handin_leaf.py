"""5-man boss-gear line, 老树叶 last step: the leader hands the leaf to 克拉苏 and takes the quest again (user 2026-11-06).

    python -X utf8 handin_leaf.py          (run go_forest3.py first; the PP鸡 landing is in reach of 克拉苏)

Live 2026-11-06 19:46: 传说中的老树叶［进行中］-> 接受奖励 (the whole team handed in at once) -> re-take page「…长期为我
做这件工作…」-> 接受 (all five took it again). Like handin_tiger.py, members not at the hand-in step leave the team first
(the tiger's rule: one such member makes the leader's pick close the dialog) and are invited back afterwards.
MainTask 673 reward: 9840 经验 + 1440 潜能 each. SHITU_LEAF_AGAIN=0 does not re-take.
"""
import os

from _bootstrap import LEADER, ROLES

import leaf as lf
import tiger as tg
import trial_run as t
from provisioner import world as w
from take224 import talk
from take_eagle import DailyLimit, at_limit

AGAIN = os.environ.get('SHITU_LEAF_AGAIN', '1') != '0'


def main():
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    if not any(lf.ready(c) for c in cs):
        t.say('没有人在「把老树叶交给克拉苏」这一步，跳过')
        return
    if lead.world().map_id != lf.FOREST_3:
        raise t.Stop(f'{LEADER} 不在迷惑森林3区（map {lead.world().map_id}），先跑 go_forest3.py')
    if not lf.ready(lead):
        raise t.Stop(f'{LEADER} 自己不在交任务这一步（任务 {lf.steps(lead)}），队员却在：手动看一下')
    for c in cs[1:]:
        if c.char_id in lead.team() and not lf.ready(c):
            t.say(f'[{c.name}] 不在交任务这一步（任务 {lf.steps(c)}），先离队，不然队长交不了')
            c.game.team_leave()
            t.wait(lambda: not c.team(), 5, f'{c.name} 离队')
    before = {c.name: w.read_level(c.mem) for c in cs}
    d = talk(lead, lf.KELASU, ['老树叶', '接受奖励'], tg.open_npc(lead, lf.KELASU, '克拉苏'))
    t.wait(lambda: not lf.ready(lead), 5, f'{LEADER} 交掉任务 673')
    lf.new_round()
    limited = False
    if d is None:
        d = lead.dialog()
    if AGAIN and d and any(t.plain(l) == '接受' or '接受任务' in t.plain(l) for _, l in d.options):
        talk(lead, lf.KELASU, ['接受'], d)
    elif at_limit(lead):
        limited = True
    tg.close(lead)
    t.say(f'[{LEADER}] 交了「传说中的老树叶」，' +
          ('今天的次数用完了，没有续接' if limited else '已续接' if lf.has_quest(lead) else '没有续接'))
    t.say('等级: ' + str({c.name: (before[c.name], w.read_level(c.mem)) for c in cs}))
    tg.regroup(cs)
    if limited:
        raise DailyLimit('克拉苏说「已经超过今日挑战上限了」：今天的老树叶打满了')


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
