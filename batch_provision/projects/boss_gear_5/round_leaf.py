"""5-man boss-gear line: run whole 传说中的老树叶 rounds (user 2026-11-06), picking up wherever the team is.

    python -X utf8 round_leaf.py [rounds, default 1]     (round_leaf.py 10 = the whole day: stops at「今日挑战上限」)

One round: (home + PP鸡 to 迷惑森林3区 unless already in 失落之地) -> take quest if missing -> into 失落之地 ->
guard / 石碑 + 暗天爪牙 + 传送门 / follower / 黑山老妖 -> home + PP鸡 -> report to 克拉苏 (re-takes the quest).
Every step skips itself when done.
"""
import sys
import time

from _bootstrap import ROLES

import trial_run as t

import reset_quest as rq

import enter_lost
import go_forest3
import handin_leaf
import leaf as lf
import leaf_fight
import take_leaf
from take_eagle import DailyLimit


def one(n):
    t.say(f'===== 老树叶第 {n} 轮开始 =====')
    t0 = time.monotonic()
    cs = [t.Client(r) for r in ROLES]
    # user 2026-11-07: mixed progress (one role still at an old (2,1)) -> everyone drops it, the round re-takes it;
    # then the leader alone decides fight-or-report (any(ready) skipped the fight and handin_* stopped)
    rq.check_same(cs, (lf.QUEST,), '传说中的老树叶', lf.ITEMS)
    if not lf.ready(cs[0]):
        if not enter_lost.in_lost(cs) or not all(lf.has_quest(c) for c in cs):
            go_forest3.main()                 # skips itself when the full team is in 152 already
            take_leaf.main()
            enter_lost.main()
        leaf_fight.main()
    go_forest3.main()
    handin_leaf.main()
    t.say(f'===== 老树叶第 {n} 轮结束，用时 {(time.monotonic() - t0) / 60:.1f} 分钟 =====')


def main(rounds):
    rq.start_of_run((lf.QUEST,), '传说中的老树叶', lf.ITEMS)     # user 2026-11-07: forced fresh start once per run
    for n in range(1, rounds + 1):
        try:
            one(n)
        except DailyLimit as e:                 # 10 a day: done for today, not an error
            t.say(f'今天打满了，停在第 {n} 轮：{e}')
            return
        except leaf_fight.LeafLost as e:        # one retry from 逍遥村 (go_forest3 -> take_leaf re-takes)
            t.say(f'第 {n} 轮{e}，从回城开始重来一次')
            one(n)


if __name__ == '__main__':
    try:
        main(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
