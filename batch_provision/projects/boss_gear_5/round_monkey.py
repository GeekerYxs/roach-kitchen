"""5-man boss-gear line: run whole 金刚猴的挑战书 rounds (user 2026-11-06), picking up wherever the team is.

    python -X utf8 round_monkey.py [rounds, default 1]     (stops at「今日挑战上限」if 龙上利 has one)

One round: (home + PP鸡 to 圣人谷 + walk to 龙上利 unless already in 秘密宝窟) -> take quest if missing -> into 秘密宝窟
-> 定土神针 / 二层 / 鲜花铠甲 / 变形金猴 -> home + PP鸡 + walk -> report to 龙上利 (re-takes the quest).
Every step skips itself when done.
"""
import sys
import time

from _bootstrap import ROLES

import trial_run as t

import reset_quest as rq

import enter_baoku
import go_forest1
import handin_monkey
import monkey as mk
import monkey_fight
import take_monkey
from take_eagle import DailyLimit


def one(n):
    t.say(f'===== 金刚猴第 {n} 轮开始 =====')
    t0 = time.monotonic()
    cs = [t.Client(r) for r in ROLES]
    # user 2026-11-07: mixed progress (one role still at an old (2,1)) -> everyone drops it, the round re-takes it;
    # then the leader alone decides fight-or-report (any(ready) skipped the fight and handin_* stopped)
    rq.check_same(cs, (mk.QUEST,), '金刚猴的挑战书', mk.ITEMS)
    if not mk.ready(cs[0]):
        if not enter_baoku.in_baoku(cs) or not all(mk.has_quest(c) for c in cs):
            go_forest1.main()                 # skips the PP鸡 when the full team is in 150 already
            take_monkey.main()
            enter_baoku.main()
        monkey_fight.main()
    go_forest1.main()
    handin_monkey.main()
    t.say(f'===== 金刚猴第 {n} 轮结束，用时 {(time.monotonic() - t0) / 60:.1f} 分钟 =====')


def main(rounds):
    rq.start_of_run((mk.QUEST,), '金刚猴的挑战书', mk.ITEMS)     # user 2026-11-07: forced fresh start once per run
    for n in range(1, rounds + 1):
        try:
            one(n)
        except DailyLimit as e:                 # 10 a day: done for today, not an error
            t.say(f'今天打满了，停在第 {n} 轮：{e}')
            return
        except monkey_fight.MonkeyLost as e:    # one retry from 逍遥村 (go_forest1 -> take_monkey re-takes)
            t.say(f'第 {n} 轮{e}，从回城开始重来一次')
            one(n)


if __name__ == '__main__':
    try:
        main(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
