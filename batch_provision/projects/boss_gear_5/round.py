"""5-man boss-gear line: run whole 让鹰王倒下 rounds (user 2026-11-06), picking up wherever the team is.

    python -X utf8 round.py [rounds, default 1]      (round.py 10 = the whole day: it stops at「今日挑战上限」)

One round: (home + PP鸡 to 荒芜之地1区 unless already in 陷阱囚牢) -> take quest if missing -> into the cage ->
three crystals + 琉璃瓶 + 独眼鹰王 -> home + PP鸡 -> report to 莫吉 (re-takes the quest). Every step skips itself
when already done, so a stopped run is simply started again.
"""
import sys
import time

from _bootstrap import ROLES

import trial_run as t

import eagle_cage
import enter_cage
import go_desert1
import handin_eagle
import take_eagle


def to_desert(cs):
    """go_desert1 unless the full team already stands in 荒芜之地1区 (live 13:29: a round started there and still
    scrolled home first, ~1 min and 5 回城卷 for nothing)."""
    lead = cs[0]
    if all(c.world().map_id == go_desert1.DESERT_1 for c in cs) and set(lead.team()) == {c.char_id for c in cs}:
        t.say('五人已经在荒芜之地1区，不用回城')
        return
    go_desert1.main()


def one(n):
    t.say(f'===== 第 {n} 轮开始 =====')
    t0 = time.monotonic()
    cs = [t.Client(r) for r in ROLES]
    if not any(handin_eagle.ready(c) for c in cs):
        if not enter_cage.in_cage(cs):
            to_desert(cs)
            take_eagle.main()
            enter_cage.main()
        eagle_cage.main()
    to_desert(cs)
    handin_eagle.main()
    t.say(f'===== 第 {n} 轮结束，用时 {(time.monotonic() - t0) / 60:.1f} 分钟 =====')


def main(rounds):
    for n in range(1, rounds + 1):
        try:
            one(n)
        except take_eagle.DailyLimit as e:          # 10 a day (live 2026-11-06): done for today, not an error
            t.say(f'今天打满了，停在第 {n} 轮开头：{e}')
            return


if __name__ == '__main__':
    try:
        main(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
