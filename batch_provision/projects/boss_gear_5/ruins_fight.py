"""5-man boss-gear line, 狗贼贼 step 4: in 巨石之城南部遗址 (map 1050) beat 遗址守护者, take 遗址1号传送机, beat
遗址守卫者, take 遗址2号传送机, beat 狗贼贼 (quest 819 step 0) (user 2026-11-06).

    python -X utf8 ruins_fight.py

Live 2026-11-06 21:56-22:05 (probe_ruins_walk.py / probe_leaf.py, all five casting):
- The 171 entrance lands at (1194,4995). ~3700 px of path to 遗址守护者 1191 (558,2013): clicked from (576,2256)
  (243 px) its menu is「开打 / 离开」, the first pick started the battle; won in 46 s, each of the five got
  遗址守护者白旗 11162 + 遗址1号通行证 11175.
- 遗址1号传送机 10196 (702,1971), clicked from the same spot (311 px):「你确定要用1个遗址1号通行证…」-> 确定 moved the
  whole team to (3654,5205) in the middle part; only the leader's pass was used.
- ~5300 px to 遗址守卫者 1192 (4158,1413): clicked from (4320,1600) (247 px),「开打」at once, 60 s; each got
  遗址守卫者白旗 11163 + 遗址2号通行证 11176. 遗址2号传送机 10198 (4410,1449) from the same spot: 确定 -> (4014,4125).
- ~5500 px to 狗贼贼 1193 (1065,967): clicked from (1168,1192),「开打」: the first pick started nothing, the second
  did (eagle_cage.start_boss); won in ~30 s, quest 819 step 0 done for all five, both flags taken from everyone.
  The members keep their unused passes.
Where the team stands (which mapgrid part) and the leader's flags tell where to go on, so a rerun picks up anywhere.
"""
import time

from _bootstrap import LEADER, ROLES

import gouzei as gz
import tiger as tg
import trial_run as t
from eagle_cage import click, settle, start_boss
from provisioner import mapgrid
from tiger_fight import fight_all
import tiger_fight

REACH = 250                  # px: every click above came from 176..311 px
LEG = 600                    # px of path per walking leg (mapgrid.waypoints, as in monkey_fight.py)
ENTRY, MIDDLE, DEEP = 0, 1, 2
LANDINGS = {ENTRY: (1194, 4995), MIDDLE: (3654, 5205), DEEP: (4014, 4125)}   # live landings of each part
PART_NAMES = {ENTRY: '入口那块', MIDDLE: '中间那块', DEEP: '狗贼贼那块'}

_GRID = None
_PARTS = None


class GouzeiLost(t.Stop):
    """The team lost a fight in the ruins (out of the map afterwards). round_gouzei.py starts the round over."""


def grid():
    global _GRID
    if _GRID is None:
        _GRID = mapgrid.load(gz.RUINS)
    return _GRID


def part(c):
    """Which of the three walking parts of 1050 c stands in (None: elsewhere)."""
    global _PARTS
    s = c.world()
    if s.map_id != gz.RUINS:
        return None
    if _PARTS is None:
        _PARTS = {k: set(grid().distances(xy)) for k, xy in LANDINGS.items()}
    cell = grid().nearest_walkable(*grid().cell(s.x, s.y), limit=4)
    return next((k for k, cells in _PARTS.items() if cell in cells), None)


def walk(lead, xy, why):
    s = lead.world()
    hit = grid().touch_spot(grid().distances((s.x, s.y)), xy, REACH)
    if not hit:
        raise t.Stop(f'[{LEADER}] 从 ({s.x:.0f},{s.y:.0f}) 走不到{why} {xy}（遗址里不在同一块）')
    legs = grid().waypoints((s.x, s.y), hit[1], LEG)
    for i, wp in enumerate(legs, 1):
        tiger_fight.walk(lead, wp, f'{why}（第 {i}/{len(legs)} 段）', gz.RUINS, '巨石之城南部遗址', 'enter_ruins.py')


def fight(cs, npc, xy, what, won):
    """Walk to npc, pick「开打」, all five cast; won(lead) tells the fight was the right one."""
    lead = cs[0]
    for attempt in range(1, 4):
        walk(lead, xy, what)
        start_boss(lead, npc, '开打', what)
        f0 = time.monotonic()
        fight_all(cs, 900, f'{what}战斗')
        time.sleep(2)
        if lead.world().map_id != gz.RUINS:
            raise GouzeiLost(f'打输了{what}：队长在 map {lead.world().map_id}，任务 {gz.steps(lead)}')
        try:
            t.wait(lambda: won(lead), 10, f'打完{what}')
            t.say(f'[{LEADER}] 打完{what}（{time.monotonic() - f0:.0f} 秒）')
            return
        except t.Stop:
            # the battle that started may have been an encounter, not the guard: look again
            t.say(f'[{LEADER}] 第 {attempt} 次打完{what}没拿到东西: {gz.items(lead)} {gz.steps(lead)}')
    raise t.Stop(f'打了 3 次{what}还没拿到东西')


def teleport(cs, npc, xy, pass_item, to, what):
    """Click the 传送机 and confirm (uses one pass of the leader's); the whole team lands in part `to`."""
    lead = cs[0]
    if not gz.has(lead, pass_item):
        raise t.Stop(f'[{LEADER}] 没有{gz.ITEMS[pass_item]}，过不了{what}')
    walk(lead, xy, what)
    for attempt in range(1, 5):
        settle(lead)
        click(lead, npc)
        try:
            d = t.wait(lambda: lead.dialog(), 5, f'{what}的对话框')
        except t.Stop:
            t.say(f'第 {attempt} 次点{what}没出对话框{"（遇怪了）" if lead.world().in_battle else ""}，再点')
            continue
        opt = next((o for o, l in d.options if '确定' in t.plain(l)), None)
        if opt is None:
            tg.close(lead)
            raise t.Stop(f'{what}的对话框里没有「确定」: {t.plain(d.text)} {[t.plain(l) for _, l in d.options]}')
        lead.game.select_dialog(opt)
        try:
            t.wait(lambda: part(lead) == to, 8, f'过{what}')
            break
        except t.Stop:
            t.say(f'第 {attempt} 次选了确定没过去，再点')
    else:
        raise t.Stop(f'点了 4 次{what}都没过去')
    t.wait(lambda: all(part(c) == to for c in cs), 10, f'五人过了{what}')
    s = lead.world()
    t.say(f'五人到了遗址{PART_NAMES[to]}，队长在 ({s.x:.0f},{s.y:.0f})')


def main():
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    if all(gz.beaten(c) for c in cs):
        t.say('五人都已经打过狗贼贼，跳过')
        return
    if not gz.has_quest(lead):
        raise t.Stop(f'{LEADER} 没有任务 819，先跑 take_gouzei.py')
    if lead.world().map_id != gz.RUINS or not gz.team_full(cs):
        raise t.Stop(f'五人不在遗址或队伍不全（map {lead.world().map_id}，队伍 {lead.team()}），先跑 enter_ruins.py')
    lacking = [c.name for c in cs if not gz.has_quest(c)]
    if lacking:                                # PhaseTask 819: every member of a team must have the quest
        raise t.Stop(f'{lacking} 没有任务 819，先跑 take_gouzei.py')
    t0 = time.monotonic()
    gz.say_state(cs, '开始:')
    if part(lead) == ENTRY:
        if not gz.has(lead, gz.FLAG1):
            fight(cs, gz.GUARD1, gz.GUARD1_XY, '遗址守护者', lambda c: gz.has(c, gz.FLAG1))
        teleport(cs, gz.TP1, gz.TP1_XY, gz.PASS1, MIDDLE, '遗址1号传送机')
    if part(lead) == MIDDLE:
        if not gz.has(lead, gz.FLAG2):
            fight(cs, gz.GUARD2, gz.GUARD2_XY, '遗址守卫者', lambda c: gz.has(c, gz.FLAG2))
        teleport(cs, gz.TP2, gz.TP2_XY, gz.PASS2, DEEP, '遗址2号传送机')
    if part(lead) != DEEP:
        raise t.Stop(f'[{LEADER}] 不知道在遗址哪一块 ({lead.world().x:.0f},{lead.world().y:.0f})')
    if not (gz.has(lead, gz.FLAG1) and gz.has(lead, gz.FLAG2)):
        raise t.Stop(f'[{LEADER}] 到了狗贼贼那块却没有两面白旗: {gz.items(lead)}')
    fight(cs, gz.GOUZEI, gz.GOUZEI_XY, '狗贼贼', gz.beaten)
    t.wait(lambda: all(gz.beaten(c) for c in cs), 10, '五人任务「打败狗贼贼」完成')
    t.say(f'狗贼贼打完（{(time.monotonic() - t0) / 60:.1f} 分钟），五人任务都到「告诉皮克斯」')


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
