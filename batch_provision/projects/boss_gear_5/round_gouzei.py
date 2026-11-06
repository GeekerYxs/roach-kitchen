"""5-man boss-gear line: run whole 突出虫围 (狗贼贼) rounds (user 2026-11-06), picking up wherever the team is.

    python -X utf8 round_gouzei.py [rounds, default 1]     (stops at「今日挑战上限」if 皮克斯 has one)

One round: (home + PP鸡 to 苦无沙漠3区 + walk to 皮克斯 unless already in the ruins) -> take quest if missing -> into
巨石之城南部遗址 -> 遗址守护者 / 1号传送机 / 遗址守卫者 / 2号传送机 / 狗贼贼 -> home + PP鸡 + walk -> report to 皮克斯
(re-takes the quest). Every step skips itself when done.
"""
import sys
import time

from _bootstrap import ROLES

import trial_run as t

import enter_ruins
import go_kuwu2
import gouzei as gz
import handin_gouzei
import ruins_fight
import take_gouzei
from take_eagle import DailyLimit


def one(n):
    t.say(f'===== 狗贼贼第 {n} 轮开始 =====')
    t0 = time.monotonic()
    cs = [t.Client(r) for r in ROLES]
    if not any(gz.ready(c) for c in cs):
        if not enter_ruins.in_ruins(cs) or not all(gz.has_quest(c) for c in cs):
            go_kuwu2.main()                   # skips the PP鸡 when the full team is in 171 / 172 already
            take_gouzei.main()
            enter_ruins.main()
        ruins_fight.main()
    go_kuwu2.main()
    handin_gouzei.main()
    t.say(f'===== 狗贼贼第 {n} 轮结束，用时 {(time.monotonic() - t0) / 60:.1f} 分钟 =====')


def main(rounds):
    for n in range(1, rounds + 1):
        try:
            one(n)
        except DailyLimit as e:                 # 10 a day: done for today, not an error
            t.say(f'今天打满了，停在第 {n} 轮：{e}')
            return
        except ruins_fight.GouzeiLost as e:     # one retry from 逍遥村 (go_kuwu2 -> take_gouzei re-takes)
            t.say(f'第 {n} 轮{e}，从回城开始重来一次')
            one(n)


if __name__ == '__main__':
    try:
        main(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
