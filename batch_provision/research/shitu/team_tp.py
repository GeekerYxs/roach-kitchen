"""The whole team through the 外城传送员 to 无尽2路口 (B+ cave / snake, user 2026-11-01), instead of walking map 20.

    python -X utf8 research/shitu/team_tp.py send APP ..          the apprentices start walking to 外城传送员 740
                                                                  (no wait: the master takes 224 at 大个王 meanwhile)
    python -X utf8 research/shitu/team_tp.py go MASTER APP ..     everybody to 740, one team, 740「龙之都外城中心」->
                                                                  743「传送服务」「无尽2路口」(50 金币 each hop, each pays)

Why: from the PP鸡 landing (4050,303) the team walked ~4500 px to the 141 link (396,2976), and in cave the master first
walked back from 大个王 (4398,2553) to the apprentices (~2300 px). 740 (4744,2468) is 350 px from 大个王; the teleports
land at (792,2692), ~490 px from the link. A team teleports together (GATHER.md 7.2, live 2026-10-27 01:34 with 24s).
Exit 1 on any miss: the route's cmd is soft and go_goal / go_cave walk from wherever the team stands, as before.
"""
import math
import sys
import threading

import take224 as tk
import trial_run as t
from well10 import form_team

LAND_NEAR = 300          # px: a team lands in a little cloud around the leader


def to_tp1(cs):
    """Everybody walks to 740 at once (own thread = own window, as talk_chain)."""
    errs = []

    def one(c):
        try:
            tk.walk(c, tk.TP1_XY, f'外城传送员 {tk.TP1}')
        except t.Stop as e:
            errs.append(str(e))
    ths = [threading.Thread(target=one, args=(c,)) for c in cs]
    [th.start() for th in ths]
    [th.join() for th in ths]
    if errs:
        raise t.Stop('；'.join(errs))


def landed(cs, xy):
    return all((s := c.world()).map_id == tk.MAP and math.dist((s.x, s.y), xy) <= LAND_NEAR for c in cs)


def hop(lead, cs, npc, steps, land):
    gold = tk.w.read_gold(lead.mem)
    tk.talk(lead, npc, steps)
    t.wait(lambda: landed(cs, land), 8, f'全队传送到 {land}')
    t.say(f'[{lead.name}] 全队传送到 {land}，金币 {gold} -> {tk.w.read_gold(lead.mem)}')


def go(names):
    cs = [t.Client(n) for n in names]
    lead, members = cs[0], cs[1:]
    st = lead.world()
    if st.map_id != tk.MAP:
        raise t.Stop(f'{lead.name} 不在龙之都外城 (map {st.map_id})')
    if math.dist((st.x, st.y), tk.TP2_LAND) <= 400 and landed(cs, tk.TP2_LAND):
        t.say('全队已在无尽2路口')
        return
    for c in cs:                           # everybody walks alone (a member can't walk off in a team), then one team
        if c.team():
            c.game.team_leave()
    for c in cs:
        t.wait(lambda: not c.team(), 5, f'{c.name} 离队')
    to_tp1(cs)
    form_team(lead, members)
    if set(lead.team()) != {c.char_id for c in cs}:
        raise t.Stop(f'组队没齐: {lead.team()}')
    hop(lead, cs, tk.TP1, [tk.TP1_LABEL], tk.TP1_LAND)
    tk.walk(lead, tk.TP2_XY, f'外城传送员 {tk.TP2}')
    hop(lead, cs, tk.TP2, ['传送服务', tk.TP2_LABEL], tk.TP2_LAND)


def send(names):
    for n in names:
        c = t.Client(n)
        if c.world().map_id != tk.MAP:     # a rerun from the cave / 141: go_goal / go_cave take it from there
            t.say(f'[{n}] 不在龙之都外城，不走')
            continue
        if c.team():
            c.game.team_leave()
        c.game.navigate(tk.MAP, *tk.TP1_XY)
        t.say(f'[{n}] 先走去外城传送员 {tk.TP1} {tk.TP1_XY}')


def main(argv):
    op, *names = argv
    if op not in ('send', 'go') or not names:
        raise SystemExit(__doc__)
    (send if op == 'send' else go)(names)


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
