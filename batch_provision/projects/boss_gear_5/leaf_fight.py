"""5-man boss-gear line, 老树叶 step 4: in 失落之地 (map 950) get 拜山帖 from the right 老树护卫, cross to the south half
(传送石 + 暗天爪牙 + 传送门), get 老树根 from the right 老树随从, then beat 黑山老妖 (quest 673 step 0) (user 2026-11-06).

    python -X utf8 leaf_fight.py

Picks up from the bag: 老树根 -> 黑山老妖; 拜山帖 -> (cross south) -> followers; nothing -> guards. Which guard /
follower / 石碑 is right is unknown in advance (克拉苏: only the right one gives the item); the wrong ones tried this
round are kept in runtime/boss_gear_5_leaf.json (a restart does not fight them again) and last round's right one is
tried first. Candidates otherwise go nearest-path first (mapgrid). All fights: start_boss「开打」+ all five casting
(tiger_fight.fight_all). Facts from the live round are in leaf.py.
"""
import time

from _bootstrap import LEADER, ROLES

import leaf as lf
import tiger as tg
import trial_run as t
from eagle_cage import click, settle, start_boss
from provisioner import mapgrid
from tiger_fight import fight_all, menu, pick
import tiger_fight

REACH = 300                  # px: guards / followers / 老妖 answered from ~300 (live 2026-11-06)
STELE_REACH = 400            # 4040 answered from 393 px, 4041 not from 446
CLAW_REACH = 150             # 19:30: nothing from 287 px while the 爪牙 was dead; it answered from 80 px
CLAW_WAIT = 300              # s to wait for the 爪牙 to respawn (19:31: back within ~1 min)

_GRID = None


class LeafLost(t.Stop):
    """The team lost a fight in 失落之地 (out of the map afterwards). round_leaf.py starts the round over."""


def grid():
    global _GRID
    if _GRID is None:
        _GRID = mapgrid.load(lf.LOST)
    return _GRID


def walk(lead, xy, why):
    tiger_fight.walk(lead, xy, why, lf.LOST, '失落之地', 'enter_lost.py')


def ranked(lead, npcs, reach, first=None):
    """[(npc, spot)] nearest walk first (first = last round's right one, put in front)."""
    s = lead.world()
    dist = grid().distances((s.x, s.y))
    out = []
    for npc, xy in npcs.items():
        hit = grid().touch_spot(dist, xy, reach)
        out.append((0 if npc == first else 1, hit[0] if hit else 1e9, npc, hit[1] if hit else xy))
    return [(npc, spot) for _, _, npc, spot in sorted(out)]


def fight(cs, npc, what):
    lead = cs[0]
    t0 = time.monotonic()
    start_boss(lead, npc, '开打', what)
    fight_all(cs, 600, what)
    time.sleep(2)
    if lead.world().map_id != lf.LOST:
        raise LeafLost(f'打{what}输了：队长在 map {lead.world().map_id}，任务 {lf.steps(lead)}')
    t.say(f'[{LEADER}] 打完{what}（{time.monotonic() - t0:.0f} 秒）')


def trial(cs, kind, npcs, item, what, reach=REACH):
    """Fight npcs one by one until the leader holds item. Wrong ones are logged for this round."""
    lead = cs[0]
    log = lf.load_log()
    for _ in range(2 * len(npcs)):
        if lf.has(lead, item):
            return
        wrong = log['wrong'].setdefault(kind, [])
        left = {n: xy for n, xy in npcs.items() if n not in wrong}
        if not left:                               # all marked wrong: an encounter may have stood in for a fight
            t.say(f'三个{what}都记成错的了，清掉重来')
            wrong.clear()
            left = dict(npcs)
        npc, spot = ranked(lead, left, reach, log['right'].get(kind))[0]
        walk(lead, spot, f'{what} {npc} 的点击位')
        fight(cs, npc, f'{what} {npc}')
        end = time.monotonic() + 5
        while time.monotonic() < end and not lf.has(lead, item):
            time.sleep(0.3)
        if lf.has(lead, item):
            log['right'][kind] = npc
            lf.save_log(log)
            t.say(f'[{LEADER}] {what} {npc} 是对的，拿到{lf.ITEMS[item]}')
            return
        t.say(f'[{LEADER}] {what} {npc} 打赢了没给东西：错的')
        wrong.append(npc)
        lf.save_log(log)
    raise t.Stop(f'{what}都打过了还没拿到{lf.ITEMS[item]}')


def stone(cs):
    """传送石 from the right 石碑: 搜查石碑的背面 -> 拾取 (only the leader gets one)."""
    lead = cs[0]
    log = lf.load_log()
    for _ in range(2 * len(lf.STELES)):
        if lf.has(lead, lf.STONE):
            return
        wrong = log['wrong'].setdefault('stele', [])
        left = {n: xy for n, xy in lf.STELES.items() if n not in wrong}
        if not left:                               # emptied by someone else? look at all four again
            wrong.clear()
            left = dict(lf.STELES)
        npc, spot = ranked(lead, left, STELE_REACH, log['right'].get('stele'))[0]
        walk(lead, spot, f'石碑 {npc} 的点击位')
        menu(lead, npc, f'石碑 {npc}')
        pick(lead, '背面')
        if pick(lead, '拾取'):
            t.wait(lambda: lf.has(lead, lf.STONE), 5, '拿到传送石')
            log['right']['stele'] = npc
            lf.save_log(log)
            t.say(f'[{LEADER}] 石碑 {npc} 背面有传送石，拿到了')
        else:
            t.say(f'[{LEADER}] 石碑 {npc} 背面是空的')
            wrong.append(npc)
            lf.save_log(log)
        tg.close(lead)
    if not lf.has(lead, lf.STONE):
        raise t.Stop('四块石碑都看过了，没拿到传送石')


def look(lead, npc):
    """Raw click, the dialog if one opens within 2 s (None: not there, e.g. the 爪牙 dead / portal closed)."""
    tg.close(lead)
    click(lead, npc)
    end = time.monotonic() + 2
    while time.monotonic() < end:
        if (d := lead.dialog()) is not None:
            return d
        time.sleep(0.2)
    return None


def cross(cs):
    """North half -> south half: 传送石, then the 传送门 that the dead 暗天爪牙 leaves (beat it if it stands)."""
    lead = cs[0]
    stone(cs)
    spot = ranked(lead, {lf.CLAW: lf.CLAW_XY}, CLAW_REACH)[0][1]
    walk(lead, spot, '暗天爪牙旁边')
    end = time.monotonic() + CLAW_WAIT
    while time.monotonic() < end:
        settle(lead)
        d = look(lead, lf.PORTAL)
        if d and any('传送' in t.plain(l) for _, l in d.options):
            pick(lead, '传送')
            t.wait(lambda: all(lf.south(c) for c in cs), 10, '五人传到失落之地二层')
            s = lead.world()
            t.say(f'五人到了失落之地二层，队长在 ({s.x:.0f},{s.y:.0f})')
            return
        d = look(lead, lf.CLAW)
        if d and any('开打' in t.plain(l) for _, l in d.options):
            tg.close(lead)
            fight(cs, lf.CLAW, '暗天爪牙')
            continue
        tg.close(lead)
        t.say('暗天爪牙和传送门都不在（别人刚打过？），等它复活')
        time.sleep(10)
    raise t.Stop(f'等了 {CLAW_WAIT} 秒，暗天爪牙和传送门都没出来')


def yao(cs):
    lead = cs[0]
    for attempt in range(1, 4):
        spot = ranked(lead, {lf.YAO: lf.YAO_XY}, REACH)[0][1]
        walk(lead, spot, '黑山老妖的点击位')
        fight(cs, lf.YAO, '黑山老妖')
        try:
            t.wait(lambda: all(lf.beaten(c) for c in cs), 10, '五人任务「打败黑山老妖」完成')
            return
        except t.Stop:
            # the battle that started may have been an encounter, not the 老妖: look again
            t.say(f'[{LEADER}] 第 {attempt} 次打完任务没走: {[lf.steps(c) for c in cs]}')
    raise t.Stop('打了 3 次黑山老妖任务还没走')


def main():
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    if all(lf.beaten(c) for c in cs):
        t.say('五人都已经打过黑山老妖，跳过')
        return
    if not lf.has_quest(lead):
        raise t.Stop(f'{LEADER} 没有任务 673，先跑 take_leaf.py')
    if lead.world().map_id != lf.LOST or not lf.team_full(cs):
        raise t.Stop(f'五人不在失落之地或队伍不全（map {lead.world().map_id}，队伍 {lead.team()}），先跑 enter_lost.py')
    lacking = [c.name for c in cs if not lf.has_quest(c)]
    if lacking:                                # PhaseTask 673: every member of a team must have the quest
        raise t.Stop(f'{lacking} 没有任务 673，先跑 take_leaf.py')
    t0 = time.monotonic()
    lf.say_state(cs, '开始:')
    if not lf.has(lead, lf.ROOT):
        if not lf.has(lead, lf.BAISHAN):
            if lf.south(lead):
                raise t.Stop('队伍在失落之地二层，但队长没有拜山帖也没有老树根：手动看一下')
            trial(cs, 'guard', lf.GUARDS, lf.BAISHAN, '老树护卫')
        if not lf.south(lead):
            cross(cs)
        trial(cs, 'follower', lf.FOLLOWERS, lf.ROOT, '老树随从')
    if not lf.south(lead):
        raise t.Stop('有老树根但队伍不在失落之地二层：手动看一下')
    yao(cs)
    s = lead.world()
    t.say(f'黑山老妖打完（{(time.monotonic() - t0) / 60:.1f} 分钟），五人任务都到「交给克拉苏」；'
          f'队长在 ({s.x:.0f},{s.y:.0f})')


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
