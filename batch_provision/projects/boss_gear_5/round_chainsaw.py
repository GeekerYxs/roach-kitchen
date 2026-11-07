"""5-man boss-gear line: run whole 惊魂监狱的杀人狂 (电锯杀人王) rounds (user 2026-11-06), picking up wherever the team is.

    SHITU_APPRENTICES=伏地魔2,伏地魔3,伏地魔4 python -X utf8 round_chainsaw.py [rounds, default 1]

Every role must be a 龙之都 citizen (铁男 lets it into 龙之都内城 for free); enter_prison.NoCitizen names the one
that is not (2026-11-06: 欧皇丨花花乀) -> leave it out of SHITU_APPRENTICES.
One round: (home + PP鸡 to 龙之都 + walk to 老刘 unless already in the prison) -> take quest if missing -> 交叉口 ->
铁男 one by one -> 内城 -> 惊魂监狱 -> 死亡游戏 keys -> 机关 -> 电锯杀人狂 -> home + PP鸡 + walk -> report to 老刘
(re-takes the quest). Every step skips itself when done. Stops at「今日挑战上限」if 老刘 has one.
"""
import sys
import time

from _bootstrap import ROLES

import trial_run as t

import reset_quest as rq

import chainsaw as cz
import enter_prison
import go_laoliu
import handin_chainsaw
import prison_fight
import take_chainsaw
from take_eagle import DailyLimit

# 2026-11-07: 1853 死亡游戏 (leader only, the prison 机关 gives it again) is dropped with 1852 at the reset
QUESTS = (cz.QUEST, 1853)


def one(n):
    t.say(f'===== 电锯杀人王第 {n} 轮开始（{len(ROLES)} 人：{"、".join(ROLES)}）=====')
    t0 = time.monotonic()
    cs = [t.Client(r) for r in ROLES]
    # user 2026-11-07: mixed progress (one role still at an old (2,1)) -> everyone drops it, the round re-takes it;
    # then the leader alone decides fight-or-report (any(ready) skipped the fight and handin_* stopped)
    rq.check_same(cs, QUESTS, '惊魂监狱的杀人狂', cz.KEYS)
    if not cz.ready(cs[0]):
        if not enter_prison.in_prison(cs) or not all(cz.has_quest(c) for c in cs):
            go_laoliu.main()                  # skips the PP鸡 when the full team is in 龙之都外城 already
            take_chainsaw.main()
            enter_prison.main()
        prison_fight.main()
    go_laoliu.main()
    handin_chainsaw.main()
    t.say(f'===== 电锯杀人王第 {n} 轮结束，用时 {(time.monotonic() - t0) / 60:.1f} 分钟 =====')


def main(rounds):
    rq.start_of_run(QUESTS, '惊魂监狱的杀人狂', cz.KEYS)     # user 2026-11-07: forced fresh start once per run
    for n in range(1, rounds + 1):
        try:
            one(n)
        except DailyLimit as e:                 # 10 a day: done for today, not an error
            t.say(f'今天打满了，停在第 {n} 轮：{e}')
            return
        except prison_fight.ChainsawLost as e:  # one retry from 逍遥村 (go_laoliu -> take_chainsaw re-takes)
            t.say(f'第 {n} 轮{e}，从回城开始重来一次')
            one(n)


if __name__ == '__main__':
    try:
        main(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
