"""5-man boss-gear line, 电锯杀人王 step 3: from 老刘 in 龙之都外城 into 惊魂监狱 (map 264) (user 2026-11-06).

    python -X utf8 enter_prison.py

Route: walk-on exit 10227 (663,166) of map 20 -> 龙之都交叉口 (25) -> 守门人 铁男 575 (294,171) -> 龙之都内城 (24) ->
惊魂监狱入口 1339 (5660,3258) -> 惊魂监狱.
Live 2026-11-06 22:48: in a team 铁男 only offers「缴费进入内城」when ANYBODY in it lacks 龙之都公民证; alone, a
citizen gets「进入内城」(free). 伏地魔1-4 are citizens, 欧皇丨花花乀 is not (user 2026-11-06: then leave it out
and go four: SHITU_APPRENTICES=伏地魔2,伏地魔3,伏地魔4). So everybody leaves the team and talks to 铁男 alone; a role
without「进入内城」stops the run (nobody pays here). In 24 the leader invites everybody back.
"""
import math

from _bootstrap import LEADER, ROLES

import chainsaw as cz
import tiger as tg
import trial_run as t
from eagle_cage import click, settle

TIENAN_REACH = 200
GATE_REACH = 250


class NoCitizen(t.Stop):
    """A role is no 龙之都 citizen: 铁男 wants a fee. Leave it out of SHITU_APPRENTICES."""


def in_prison(cs):
    return cz.all_in(cs, cz.PRISON)


def through_tienan(c):
    """c (out of the team, in 25 near 铁男) talks to 铁男 alone and takes the free「进入内城」."""
    for attempt in range(1, 4):
        d = tg.open_npc(c, cz.TIENAN, '铁男')
        opts = [(o, t.plain(l)) for o, l in d.options if o]
        free = [o for o, l in opts if l == '进入内城']
        if not free:
            tg.close(c)
            raise NoCitizen(f'{c.name} 没有龙之都公民证，铁男只给 {[l for _, l in opts]}（要付费）：'
                            f'把它从 SHITU_APPRENTICES 里去掉再跑')
        c.game.select_dialog(free[0])
        try:
            t.wait(lambda: c.world().map_id == cz.INNER, 10, f'{c.name} 进内城')
            return
        except t.Stop:
            t.say(f'[{c.name}] 第 {attempt} 次选了「进入内城」还在 map {c.world().map_id}')
    raise t.Stop(f'{c.name} 选了 3 次「进入内城」都没进去')


def to_inner(cs):
    lead = cs[0]
    if lead.world().map_id == cz.OUTER:
        cz.cross(lead, cs, cz.CROSS_EXIT, cz.CROSS, '龙之都交叉口出口')
    if lead.world().map_id == cz.CROSS:
        cz.walk(lead, cz.TIENAN_XY, '铁男', reach=TIENAN_REACH, fix='enter_prison.py')
    stand = lead.world()
    tg.close(lead)
    for c in cs:
        if c.world().map_id == cz.INNER:
            continue
        if c.world().map_id != cz.CROSS:
            raise t.Stop(f'{c.name} 不在龙之都交叉口（map {c.world().map_id}）')
        if c.team():
            c.game.team_leave()
            t.wait(lambda: not c.team(), 5, f'{c.name} 离队')
        s = c.world()
        if math.dist((s.x, s.y), (stand.x, stand.y)) > 80:   # the team trailed behind the leader
            c.game.navigate(cz.CROSS, round(stand.x), round(stand.y))
            t.wait(lambda: (q := c.world()) and math.dist((q.x, q.y), (stand.x, stand.y)) <= 80 and not q.moving,
                   30, f'{c.name} 走到铁男旁')
        through_tienan(c)
    t.wait(lambda: all(c.world().map_id == cz.INNER for c in cs), 10, '全员进内城')
    tg.regroup(cs)
    t.wait(lambda: cz.team_full(cs), 15, '内城重新组队')
    s = lead.world()
    t.say(f'{len(cs)} 人进了龙之都内城并组好队，队长在 ({s.x:.0f},{s.y:.0f})')


def main():
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    if in_prison(cs):
        t.say('全队已经在惊魂监狱，跳过')
        return
    if lead.world().map_id not in (cz.OUTER, cz.CROSS, cz.INNER):
        raise t.Stop(f'{LEADER} 不在龙之都（map {lead.world().map_id}），先跑 go_laoliu.py')
    if not cz.all_in(cs, cz.INNER):
        to_inner(cs)
    cz.walk(lead, cz.GATE_XY, '惊魂监狱入口', reach=GATE_REACH, fix='enter_prison.py')
    for attempt in range(1, 5):
        settle(lead)
        click(lead, cz.GATE_NPC)
        try:
            t.wait(lambda: lead.world().map_id == cz.PRISON or lead.dialog(), 6, '惊魂监狱入口')
        except t.Stop:
            t.say(f'第 {attempt} 次点惊魂监狱入口没反应{"（遇怪了）" if lead.world().in_battle else ""}')
            continue
        d = lead.dialog()
        if d and lead.world().map_id != cz.PRISON:
            t.say(f'入口对话: {t.plain(d.text)} {[(o, t.plain(l)) for o, l in d.options]}')
            opt = next((o for o, l in d.options if o and '监狱' in t.plain(l)), None) or \
                next((o for o, l in d.options if o), None)
            if opt is None:
                tg.close(lead)
                raise t.Stop('惊魂监狱入口的对话框没有可选项')
            lead.game.select_dialog(opt)
        try:
            t.wait(lambda: in_prison(cs), 15, '全队进惊魂监狱')
            break
        except t.Stop:
            t.say(f'第 {attempt} 次没全队进监狱: {[(c.name, c.world().map_id) for c in cs]}')
    else:
        raise t.Stop('点了 4 次惊魂监狱入口没全队进去')
    s = lead.world()
    t.say(f'{len(cs)} 人进了惊魂监狱（map {cz.PRISON}），队长在 ({s.x:.0f},{s.y:.0f})')


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
