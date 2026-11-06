"""5-man boss-gear line, 老树叶 step 1: everybody home, 伏地魔1 forms the team, PP鸡 chain to 迷惑森林3区 (map 152)
(user 2026-11-06: the PP鸡 landing there is in talking range of 克拉苏).

    python -X utf8 go_forest3.py

Route from pp_chain's graph (old pp data: 20 -> 40, 40 -> 152): 逍遥村 -> 平静海岸2区 -> 龙之都外城 -> 圣人谷 -> 迷惑森林3区.
Skips itself when the full team already stands in 152.
"""
from _bootstrap import ROLES

import trial_run as t
import pp_chain

import go_desert1
from go_desert2 import full_team

FOREST_3 = 152
VIA = ['平静海岸2区', '龙之都', '圣人谷']


def main():
    from provisioner import quizbot          # AGENTS.md: every line entry makes sure the quiz bot runs
    quizbot.ensure(say=t.say)
    cs = [t.Client(n) for n in ROLES]
    if full_team(cs, FOREST_3):
        t.say('五人已经在迷惑森林3区，跳过')
        return
    go_desert1.home(cs)
    pp_chain.main('迷惑森林3区', list(VIA))  # forms the team (leader = 伏地魔1), then hops
    go_desert1.verify(cs, FOREST_3)


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
