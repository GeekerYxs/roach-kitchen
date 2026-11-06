"""5-man boss-gear line, 虎力仙 step 4: in 禁锢之地 (map 1200) break the chosen pillars, then beat 虎力仙 (quest 1185
steps 0-4) (user 2026-11-06).

    python -X utf8 tiger_fight.py
    SHITU_TIGER_PILLARS=4092,4089 python -X utf8 tiger_fight.py      (pillars to break first; empty = none)

Live 2026-11-06 16:58-17:15:
- A pillar (raw 0x50 click) asks「…先把它砸了再说。」/「传送」; 砸 -> 来就来，谁怕谁。-> a battle with its guardian
  (邪蛇 88 s, 蛟龙 98 s); the leader's pick counts for all five (step done for everyone). Once broken the pillar offers
  「传送」to「虎力仙的附近」(4092 put the team at (4350,3891)), one way.
- Through walls: 4089 answered from (3792,3880) = 499 px, 4091 did not from 519 px (the eagle's ~500 px again).
  From the tiger's room 4089 and 4092 are both within reach; 4090 / 4091 are a long walk round.
- 虎力仙 1168 menu「开打」: the first pick started nothing (no boss-quiz panel seen; the quiz bot answers silently),
  the second started the battle (eagle_cage.start_boss does exactly that). 179 s with 2 pillars broken, and then ALL
  of steps 0-4 were done for all five: the unbroken pillars are not needed for the hand-in (user's player tip).
- 17:21 with NO pillar broken the team lost after ~5 min (逍遥村, team gone, quest gone). User 2026-11-06: break at
  least 1-2 pillars. Default 4092 then 4089: both reachable through walls around the tiger's room, ~6400 px of
  walking from the landing point in all (mapgrid), no pillar teleport needed.
"""
import math
import os
import time

from _bootstrap import LEADER, ROLES

import pp_chain
import tiger as tg
import trial_run as t
from eagle_cage import click, settle, start_boss
from lunhui15 import fight_out
from provisioner import mapgrid

PILLARS = tuple(int(n) for n in os.environ.get('SHITU_TIGER_PILLARS', '4092,4089').split(',') if n.strip())
REACH = 470                  # px: 499 answered, 519 did not (live 2026-11-06)
TIGER_REACH = 300

_GRID = None


class TigerLost(t.Stop):
    """The team lost to 虎力仙: back in 逍遥村, quest gone. round_tiger.py starts the round over."""


def grid():
    global _GRID
    if _GRID is None:
        _GRID = mapgrid.load(tg.JINGU)
    return _GRID


def spot(lead, xy, reach):
    s = lead.world()
    hit = grid().touch_spot(grid().distances((s.x, s.y)), xy, reach)
    return hit[1] if hit else xy


def walk(lead, xy, why):
    for attempt in range(6):                  # battles on the way eat pp_chain.walk's 120 s (eagle 12:57)
        fight_out(lead, 300)
        if lead.world().map_id != tg.JINGU:
            raise t.Stop(f'[{LEADER}] 不在禁锢之地了（map {lead.world().map_id}），先跑 enter_jingu.py')
        try:
            pp_chain.walk(lead, tg.JINGU, xy, why)
            break
        except t.Stop:
            if attempt == 5:
                raise
    fight_out(lead, 300)


def fight_all(cs, timeout, why):
    """Like lunhui15.fight_out, but all five act (skill / normal attack + pet 烈焰爆发), not just the leader.
    Live 2026-11-06 17:55: with only the leader casting (_bootstrap: SHITU_CASTERS = leader) the team lost to the
    tiger once after 2 pillars, having won the round before. well10 runs Caster for team members the same way."""
    from lunhui15 import BATTLE_TICK, Caster
    lead = cs[0]
    casters = [Caster(c) for c in cs]
    end = time.monotonic() + timeout
    while lead.world().in_battle:
        if time.monotonic() > end:
            raise t.Stop(f'{why} 超时 {timeout}s')
        now = time.monotonic()
        for k in casters:
            if k.c.world().in_battle:
                k.tick(now)
        time.sleep(BATTLE_TICK)
    for k in casters:
        k.reset()


def menu(lead, npc, what):
    for attempt in range(1, 5):
        settle(lead)
        click(lead, npc)
        try:
            return t.wait(lambda: lead.dialog(), 5, f'{what}菜单')
        except t.Stop:
            t.say(f'第 {attempt} 次点{what}没出菜单{"（遇怪了）" if lead.world().in_battle else ""}，再点')
    raise t.Stop(f'点了 4 次{what}都没有菜单')


def pick(lead, word):
    d = lead.dialog()
    opt = next((o for o, l in d.options if word in t.plain(l)), None) if d else None
    if opt is None:
        return False
    before = d.text
    lead.game.select_dialog(opt)
    end = time.monotonic() + 5
    while time.monotonic() < end and not lead.world().in_battle:
        if (x := lead.dialog()) is not None and x.text != before:
            break
        time.sleep(0.2)
    return True


def pillar(cs, npc):
    lead = cs[0]
    step, name, xy = tg.PILLARS[npc]
    for attempt in range(1, 4):
        if tg.step_done(lead, step):
            return
        walk(lead, spot(lead, xy, REACH), f'{name}的点击位')
        menu(lead, npc, name)
        if not pick(lead, '砸了'):            # broken already: only 传送 / 离开
            tg.close(lead)
            t.wait(lambda: tg.step_done(lead, step), 3, f'{name}已经砸了')
            return
        pick(lead, '来就来')
        t0 = time.monotonic()
        fight_all(cs, 600, f'{name}守护')
        # live 2026-11-06 17:35: right after the battle the step still read 1, a moment later 2
        end = time.monotonic() + 5
        while time.monotonic() < end and not tg.step_done(lead, step):
            time.sleep(0.3)
        if tg.step_done(lead, step):
            t.say(f'[{LEADER}] {name}砸掉了（{time.monotonic() - t0:.0f} 秒）')
            return
        t.say(f'[{LEADER}] 第 {attempt} 次打{name}后任务没走，再来')
    raise t.Stop(f'{name}打了 3 次任务还没走')


def main():
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    if all(tg.beaten(c) for c in cs):
        t.say('五人都已经打过虎力仙，跳过')
        return
    if not tg.has_quest(lead):
        raise t.Stop(f'{LEADER} 没有任务 1185，先跑 take_tiger.py')
    if lead.world().map_id != tg.JINGU or set(lead.team()) != {c.char_id for c in cs}:
        raise t.Stop(f'五人不在禁锢之地或队伍不全（map {lead.world().map_id}，队伍 {lead.team()}），先跑 enter_jingu.py')
    lacking = [c.name for c in cs if not tg.has_quest(c)]
    if lacking:                                # PhaseTask 1185: every member of a team must have the quest
        raise t.Stop(f'{lacking} 没有任务 1185，先跑 take_tiger.py')
    t0 = time.monotonic()
    for npc in PILLARS:
        pillar(cs, npc)
    for attempt in range(1, 4):
        walk(lead, spot(lead, tg.TIGER_XY, TIGER_REACH), '虎力仙的点击位')
        start_boss(lead, tg.TIGER, '开打', '虎力仙')
        fight_all(cs, 900, '虎力仙战斗')
        time.sleep(2)
        if lead.world().map_id != tg.JINGU or not tg.has_quest(lead):
            # live 2026-11-06 17:26, no pillar broken: lost after ~5 min, all five woke up in 逍遥村, team gone,
            # quest 1185 gone (failed) -> retake it next round (round_tiger.py does)
            raise TigerLost(f'打输了虎力仙：队长在 map {lead.world().map_id}，任务 {tg.steps(lead)}')
        try:
            t.wait(lambda: all(tg.beaten(c) for c in cs), 10, '五人任务「打败虎力仙」完成')
            break
        except t.Stop:
            # the battle that started may have been an encounter, not the tiger (or the team lost): look again
            t.say(f'[{LEADER}] 第 {attempt} 次打完任务没走: {[tg.steps(c) for c in cs]}')
    else:
        raise t.Stop('打了 3 次虎力仙任务还没走')
    s = lead.world()
    t.say(f'虎力仙打完（{(time.monotonic() - t0) / 60:.1f} 分钟），五人任务都到「回去找银狐王勇」；'
          f'队长在 map {s.map_id} ({s.x:.0f},{s.y:.0f})')


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
