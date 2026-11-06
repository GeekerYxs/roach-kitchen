"""5-man boss-gear line, 金刚猴 step 4: in 秘密宝窟 (map 850) the leader gets 定土神针 (lower part) and 鲜花铠甲
(upper part) from wild encounters, then beats 变形金猴 (quest 518 step 0) (user 2026-11-06).

    python -X utf8 monkey_fight.py

Live 2026-11-06 20:18-20:30 (probe_monkey_walk.py / probe_monkey_hunt.py / probe_leaf.py):
- The 150 entrance lands at (2802,6603). Walking the ~4100 px to「秘密宝窟二层」10218 (3780,2628) met enough 流浪蟠桃怪
  that all five held a 定土神针. Standing on 10218 does nothing; a raw 0x50 click on it put the whole team at
  (4158,2055) in the part of 变形金猴 (no dialog).
- 鲜花铠甲 (野人狗仔队) dropped in the upper part, per role: one walk to 变形金猴 gave only 伏地魔2 one, the next leg
  back and forth gave 伏地魔1/3/4 one each. The upper part is patrolled between 变形金猴 and the 10218 landing until
  the LEADER holds both (user 2026-11-06: whoever picks「开打」needs the two items).
- 变形金猴 1180 menu「开打 / 离开」: the first pick started nothing (quiz bot / silent), the second started the battle
  (eagle_cage.start_boss does exactly that). All five casting (fight_all): won in ~40 s; quest 518 step 0 done for
  all five, both items taken from everyone; 欧皇丨花花乀 without a 鲜花铠甲 got the step too.
"""
import time

from _bootstrap import LEADER, ROLES

import monkey as mk
import trial_run as t
from eagle_cage import click, settle, start_boss
from provisioner import mapgrid
from tiger_fight import fight_all
import tiger_fight

REACH = 250                  # px to 变形金猴 (the live click came from (1824,1664), 290 px)
UP_REACH = 100               # 10218 answered from (3780,2628), standing on it
MONKEY_SPOT = (1824, 1664)   # mapgrid touch spot of 变形金猴 from the 10218 landing (clicked from there live)
UPPER_B = (4100, 2060)       # the 10218 landing side of the upper part: patrol 变形金猴 <-> here
# 2026-11-06 round 3: the leader had no 定土神针 after the walk up. That walk ENDED IN the 二层 link (walking onto
# (3780,2628) moves the team up, like a map link), and the patrol then sent it back to the lower landing from the
# upper part: no path, 8 min of path-finding. Lower patrol points now stay off the link: (3728,2944) is ~350 px of
# path before it, (4160,3784) ~1300 px (mapgrid).
LOWER_A, LOWER_B = (3728, 2944), (4160, 3784)
LEG = 600                    # px of path per walking leg (mapgrid.waypoints; the client's path-finder hung on 6650)
LEGS = 12                    # patrol legs per item before giving up

_GRID = None


class MonkeyLost(t.Stop):
    """The team lost a fight in 秘密宝窟 (out of the map afterwards). round_monkey.py starts the round over."""


def grid():
    global _GRID
    if _GRID is None:
        _GRID = mapgrid.load(mk.BAOKU)
    return _GRID


def spot(lead, xy, reach):
    s = lead.world()
    hit = grid().touch_spot(grid().distances((s.x, s.y)), xy, reach)
    return hit[1] if hit else xy


def walk(lead, xy, why):
    """Short legs along the mapgrid path. False when the leader changed part on the way (walked into a link)."""
    s = lead.world()
    part = mk.upper(lead)
    legs = grid().waypoints((s.x, s.y), xy, LEG)
    if legs is None:
        raise t.Stop(f'[{LEADER}] 从 ({s.x:.0f},{s.y:.0f}) 走不到{why} {xy}（秘密宝窟里不在同一块）')
    for i, wp in enumerate(legs, 1):
        tiger_fight.walk(lead, wp, f'{why}（第 {i}/{len(legs)} 段）', mk.BAOKU, '秘密宝窟', 'enter_baoku.py')
        if mk.upper(lead) != part:
            return False
    return True


def cross(cs, npc, xy, up, what):
    """To the other part: walk into the link (that alone moves the team), else raw-click its NPC.
    Live 2026-11-06: 10218 moved the team on a click and on a walk ending in it; 10219 did not answer 4 clicks from
    (4080,2128) (102 px), a navigate onto its own xy (4140,2208) moved the team down at once."""
    lead = cs[0]
    if mk.upper(lead) == up:
        return
    walk(lead, spot(lead, xy, UP_REACH), what)
    for attempt in range(1, 5):
        if mk.upper(lead) == up:
            break
        settle(lead)
        lead.game.navigate(mk.BAOKU, *xy)         # into the link rect (the stand spot may stop short of it)
        end = time.monotonic() + 8
        while time.monotonic() < end and mk.upper(lead) != up and not lead.world().in_battle:
            time.sleep(0.3)
        if mk.upper(lead) == up:
            break
        settle(lead)
        click(lead, npc)
        end = time.monotonic() + 5
        while time.monotonic() < end and mk.upper(lead) != up:
            time.sleep(0.3)
        if mk.upper(lead) != up:
            t.say(f'第 {attempt} 次走进 / 点{what}没过去{"（遇怪了）" if lead.world().in_battle else ""}，再点')
    else:
        raise t.Stop(f'走进 / 点了 4 次{what}都没过去')
    t.wait(lambda: all(mk.upper(c) == up for c in cs), 10, f'五人过了{what}')
    s = lead.world()
    t.say(f'五人到了{"变形金猴那一层" if up else "秘密宝窟一层"}，队长在 ({s.x:.0f},{s.y:.0f})')


def to_part(cs, up):
    if up:
        cross(cs, mk.UP_NPC, mk.UP_XY, True, '「秘密宝窟二层」')
    else:
        cross(cs, mk.DOWN_NPC, mk.DOWN_XY, False, '「秘密宝窟一层」')


def patrol(cs, up, points, item, why):
    """In one part (up = 变形金猴's), walk between points (every encounter fought on the way) until the leader holds
    item. A leg that ended in the other part (walked into the link) brings the team back first."""
    lead = cs[0]
    for i in range(LEGS):
        if mk.has(lead, item):
            return
        to_part(cs, up)
        walk(lead, points[i % len(points)], f'{why}巡逻点 {i % len(points) + 1}')
        mk.say_state(cs, f'{why}第 {i + 1} 段走完:')
    if not mk.has(lead, item):
        raise t.Stop(f'巡逻 {LEGS} 段，队长还没有{mk.ITEMS[item]}')


def main():
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    if all(mk.beaten(c) for c in cs):
        t.say('五人都已经打过变形金猴，跳过')
        return
    if not mk.has_quest(lead):
        raise t.Stop(f'{LEADER} 没有任务 518，先跑 take_monkey.py')
    if lead.world().map_id != mk.BAOKU or not mk.team_full(cs):
        raise t.Stop(f'五人不在秘密宝窟或队伍不全（map {lead.world().map_id}，队伍 {lead.team()}），先跑 enter_baoku.py')
    lacking = [c.name for c in cs if not mk.has_quest(c)]
    if lacking:                                # PhaseTask 518: every member of a team must have the quest
        raise t.Stop(f'{lacking} 没有任务 518，先跑 take_monkey.py')
    t0 = time.monotonic()
    mk.say_state(cs, '开始:')
    # 流浪蟠桃怪 live on the lower part: the walk towards 10218 usually is enough; else back and forth near it
    patrol(cs, False, [LOWER_A, LOWER_B], mk.PIN, '找定土神针')
    patrol(cs, True, [MONKEY_SPOT, UPPER_B], mk.ARMOR, '找鲜花铠甲')
    to_part(cs, True)
    for attempt in range(1, 4):
        walk(lead, spot(lead, mk.MONKEY_XY, REACH), '变形金猴的点击位')
        start_boss(lead, mk.MONKEY, '开打', '变形金猴')
        f0 = time.monotonic()
        fight_all(cs, 900, '变形金猴战斗')
        time.sleep(2)
        if lead.world().map_id != mk.BAOKU:
            raise MonkeyLost(f'打输了变形金猴：队长在 map {lead.world().map_id}，任务 {mk.steps(lead)}')
        try:
            t.wait(lambda: all(mk.beaten(c) for c in cs), 10, '五人任务「打败变形金猴」完成')
            t.say(f'[{LEADER}] 打完变形金猴（{time.monotonic() - f0:.0f} 秒）')
            break
        except t.Stop:
            # the battle that started may have been an encounter, not the monkey: look again
            t.say(f'[{LEADER}] 第 {attempt} 次打完任务没走: {[mk.steps(c) for c in cs]}')
    else:
        raise t.Stop('打了 3 次变形金猴任务还没走')
    t.say(f'变形金猴打完（{(time.monotonic() - t0) / 60:.1f} 分钟），五人任务都到「告诉龙上利」')


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
