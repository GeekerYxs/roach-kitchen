"""5-man boss-gear line: run whole 玩死虎力仙 rounds (user 2026-11-06), picking up wherever the team is.

    python -X utf8 round_tiger.py [rounds, default 1]     (round_tiger.py 10 = the whole day: stops at「今日挑战上限」)

One round: (home + PP鸡 + walk to 王勇 unless already in 禁锢之地) -> take quest if missing -> into 禁锢之地 ->
pillars + 虎力仙 -> home + PP鸡 + walk -> report to 王勇 (re-takes the quest). Every step skips itself when done.
"""
import sys
import time

from _bootstrap import ROLES

import trial_run as t

import reset_quest as rq

import enter_jingu
import go_desert2
import handin_tiger
import take_tiger
import tiger as tg
import tiger_fight
from take_eagle import DailyLimit


def to_wangyong(cs):
    """go_desert2 unless the full team already stands at 王勇 (it would walk 0 px anyway, but skips the log noise)."""
    lead = cs[0]
    s = lead.world()
    if go_desert2.full_team(cs, tg.DESERT_2) and abs(s.x - go_desert2.STAND[0]) + abs(s.y - go_desert2.STAND[1]) < 400:
        return
    go_desert2.main()


def one(n):
    t.say(f'===== 虎力仙第 {n} 轮开始 =====')
    t0 = time.monotonic()
    cs = [t.Client(r) for r in ROLES]
    # user 2026-11-07: mixed progress (one role still at an old (2,1)) -> everyone drops it, the round re-takes it;
    # then the leader alone decides fight-or-report (any(ready) skipped the fight and handin_* stopped)
    rq.check_same(cs, (tg.QUEST,), '玩死虎力仙')
    if not tg.ready(cs[0]):
        if not enter_jingu.in_jingu(cs) or not all(tg.has_quest(c) for c in cs):
            to_wangyong(cs)
            take_tiger.main()
            enter_jingu.main()
        tiger_fight.main()
    to_wangyong(cs)
    handin_tiger.main()
    t.say(f'===== 虎力仙第 {n} 轮结束，用时 {(time.monotonic() - t0) / 60:.1f} 分钟 =====')


def main(rounds):
    rq.start_of_run((tg.QUEST,), '玩死虎力仙')     # user 2026-11-07: forced fresh start once per run
    for n in range(1, rounds + 1):
        try:
            one(n)
        except DailyLimit as e:                 # 10 a day: done for today, not an error
            t.say(f'今天打满了，停在第 {n} 轮：{e}')
            return
        except tiger_fight.TigerLost as e:      # one retry from 逍遥村 (go_desert2 -> take_tiger re-takes)
            t.say(f'第 {n} 轮{e}，从回城开始重来一次')
            one(n)


if __name__ == '__main__':
    try:
        main(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
