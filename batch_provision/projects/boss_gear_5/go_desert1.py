"""5-man boss-gear line, step 1: everybody home, 伏地魔1 forms the team, PP鸡 chain to 荒芜之地1区 (user 2026-11-06).

    python -X utf8 go_desert1.py

Reuses quanshou.scroll (回城卷), well10.form_team, pp_chain.main. The PP鸡 route 逍遥村 -> 平静海岸2区 -> 龙之都 ->
恶人山 -> 苦无沙漠3区 -> 荒芜之地1区 (map 180) is the one the fullcrit70 line ran live 2026-11-05.
"""
from _bootstrap import LEADER, ROLES

import trial_run as t
from pp_chain import MAP_NAMES
import pp_chain
from quanshou import scroll
from r4_util import close_dialogs

HOME = 1
DESERT_1 = 180
VIA = ['平静海岸2区', '龙之都', '恶人山', '苦无沙漠3区']


def home(cs):
    close_dialogs(cs)
    for c in cs:
        c.game.cancel_navigation()
        if c.team():
            c.game.team_leave()

    def one(c):
        t.wait(lambda: not c.team(), 5, f'{c.name} 离队')
        if c.world().map_id != HOME:
            scroll(c)
    t.each(cs, one)
    away = {c.name: c.world().map_id for c in cs if c.world().map_id != HOME}
    if away:
        raise t.Stop(f'回城后有人不在逍遥村: {away}')
    t.say('五人都回到逍遥村')


def verify(cs, map_id):
    lead = cs[0]
    wrong = {c.name: c.world().map_id for c in cs if c.world().map_id != map_id}
    if wrong:
        raise t.Stop(f'没有全员到 {MAP_NAMES.get(map_id, map_id)}: {wrong}')
    if set(lead.team()) != {c.char_id for c in cs}:
        raise t.Stop(f'队伍不完整: {lead.team()}')
    t.say(f'核验通过：五人在 {MAP_NAMES[map_id]}，{LEADER} 带队')


def main():
    from provisioner import quizbot          # AGENTS.md: every line entry makes sure the quiz bot runs
    quizbot.ensure(say=t.say)
    cs = [t.Client(n) for n in ROLES]
    home(cs)
    pp_chain.main('荒芜之地1区', list(VIA))  # forms the team (leader = 伏地魔1), then hops
    verify(cs, DESERT_1)


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
