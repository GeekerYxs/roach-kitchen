"""5-man boss-gear line, step 4: in 陷阱囚牢 the leader gets the three crystals, summons 独眼鹰王 at the 琉璃瓶 and
the team beats it (quest 1130 steps 1-4) (user 2026-11-06).

    python -X utf8 eagle_cage.py

Live 2026-11-06 12:52-13:24 (probe_bottle.py / probe_team_loop.py):
- A bottle is touched with ClickNpc; no dialog. Wrong touch = a chat line only: hp loss, a battle, or「醒来后发现你已经到了
  另外一个地方」(the team is put back at the entrance (4722,3681)). Which bottle is right is unknown in advance; one
  touch tells (user 2026-11-06). 4076 first looked like「failed, then gave it」, but both failures were followed at
  once by a battle with no penalty line: most likely swallowed touches, see crystal().
- Only the LEADER's touch counts in a team (a member's click did nothing), and it gives the crystal to all five at
  once, quest steps 0-2 too (user 2026-11-06: like 地头蛇, the leader collects, the members pass by fighting).
- 琉璃瓶 4077 menu「召唤鹰王战斗」: the first pick opened the boss quiz (答题器 answered,「测试通过！」+100 金币), the
  second pick started the battle; Caster won in ~90 s; all five got step 3 done and lost the three crystals.
Next step (4): tell 莫吉 in 荒芜之地1区.
"""
import json
import math
import struct
import time

from _bootstrap import BATCH, LEADER, ROLES

import boss_quiz
import pp_chain
import trial_run as t
from lunhui15 import fight_out
from provisioner import mapgrid
from provisioner import world as w

QUEST = 1130
CAGE = 1150
LIULI, LIULI_XY = 4077, (3381, 1998)
# kind -> (quest step index, crystal item, bottles walked to live 2026-11-06 (ResLib NPCDirection coordinates))
# 4071 / 4072 / 4067 / 4068 not walked to yet; ordered by distance at run time
KINDS = (('荒土结晶', 0, 11050, {4073: (4122, 3969), 4074: (5322, 3417), 4075: (5874, 3129), 4076: (7062, 2475)}),
         ('大风结晶', 1, 11051, {4070: (6630, 2139), 4071: (4386, 999), 4072: (3750, 687)}),
         ('烈火结晶', 2, 11052, {4069: (3186, 3447), 4067: (834, 2259), 4068: (1446, 2613)}))
EAGLE_STEP = 3
TRIES = 10                  # touches per crystal before giving up
STILL = 0.6                 # s the leader stands without moving before a touch
JUMP = 300                  # px: a position change this big after a touch = teleported (to the gate (4722,3681))
LOST_MAX = 3                # touches lost to encounters per crystal before a battle counts as wrong
WATCH = 6.0                 # s to watch a touch's result (15:47: the teleport came after 2.5 s)
CLOSE_REACH = 150           # px for the second touch of a bottle that showed nothing from farther away
DONE = 2                    # read_quest step value of a finished step
OP_CLICK_NPC = 0x50         # raw click: the client's ClickNpc would walk up to the NPC first
# 2026-11-06 live: the server answers a click from up to ~500 px (琉璃瓶: 500 yes, 520 no; through walls too) and a
# bottle touched from 427 px counted (teleport penalty) -> stand at the path-nearest spot within mapgrid.REACH
# user 2026-11-06: less walking = fewer encounters
# this round's touches survive a restart (14:28: a restarted run would have gone back to the nearest wrong bottle)
TOUCHED = BATCH / 'runtime' / 'boss_gear_5_touched.json'


def load_touched():
    try:
        return json.loads(TOUCHED.read_text(encoding='utf8'))
    except (OSError, ValueError):
        return {}


def save_touched(data):
    TOUCHED.parent.mkdir(exist_ok=True)
    TOUCHED.write_text(json.dumps(data, ensure_ascii=False), encoding='utf8')


def steps(c):
    q = w.read_quest(c.mem, QUEST)
    return q.steps if q and q.active else ()


def step_done(c, i):
    s = steps(c)
    return len(s) > i and s[i] == DONE


def has(c, item):
    return any(b.item_id == item for b in w.read_bag(c.mem) or ())


def back_in_cage(lead):
    """15:47 live: a wrong 荒土瓶 put the team OUT of the cage (荒芜之地1区 at the entrance, (2418,369)), and the walk
    kept steering at 1150 coordinates for 10 minutes -> re-enter first (enter_cage walks in from 180)."""
    fight_out(lead, 300)
    if lead.world().map_id != CAGE:
        import enter_cage
        t.say(f'[{LEADER}] 队伍不在陷阱囚牢（map {lead.world().map_id}），重新进去')
        enter_cage.main()


def walk(lead, xy, why):
    back_in_cage(lead)
    for attempt in range(5):                  # live 12:57: battles on the way ate pp_chain.walk's 120 s
        fight_out(lead, 300)
        try:
            pp_chain.walk(lead, CAGE, xy, why)
            return
        except t.Stop:
            if attempt == 4:
                raise
    fight_out(lead, 300)


_GRID = None


def grid():
    global _GRID
    if _GRID is None:
        _GRID = mapgrid.load(CAGE)
    return _GRID


def nearest(lead, targets, reach=mapgrid.REACH):
    """(npc, spot) among targets {npc: xy} whose touch spot is the shortest walk from the leader."""
    s = lead.world()
    g = grid()
    dist = g.distances((s.x, s.y))
    best = None
    for npc, xy in targets.items():
        hit = g.touch_spot(dist, xy, reach)
        if hit and (best is None or hit[0] < best[0]):
            best = (hit[0], npc, hit[1])
    if best is None:                              # no grid answer: fall back to the NPC's own spot
        npc = min(targets, key=lambda n: math.dist((s.x, s.y), targets[n]))
        return npc, targets[npc]
    return best[1], best[2]


def click(lead, npc):
    lead.game.send(OP_CLICK_NPC, struct.pack('<II', 0, npc))


def settle(lead, timeout=15):
    """Fight any battle, then wait until the leader really stands still: a click while still walking can meet an
    encounter and be lost (user 2026-11-06: encounters come from the walking, not from the bottle)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        fight_out(lead, 300)
        s = lead.world()
        if not s.in_battle and not s.moving and not s.nav_active and s.still_for >= STILL:
            return
        time.sleep(0.2)


def watch(lead, here, item, timeout=WATCH):
    """'got' / 'moved' (teleported: other map or a jump) / 'battle' / 'hp' (nothing seen = the hp penalty).
    15:47 live: the teleport came later than 2.5 s, so the touch result is watched for a while."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if has(lead, item):
            return 'got'
        s = lead.world()
        if s is None or s.map_id != here.map_id or math.dist((here.x, here.y), (s.x, s.y)) > JUMP:
            time.sleep(1.5)                       # let the map change finish before anything reads the leader
            return 'moved'
        if s.in_battle:
            return 'battle'
        time.sleep(0.2)
    return 'got' if has(lead, item) else 'hp'


def crystal(lead, name, item, bottles):
    """Each bottle of the kind once, nearest untried first; the touch result is read from the leader, not guessed
    (user 2026-11-06): the crystal in the bag = right; a jump in position = wrong (teleported to the gate); a battle
    right after = the touch was lost to an encounter -> fight, touch the same bottle again; else wrong (hp penalty).
    Live check: 4069 14:25 and 4067 14:31 — battle, then the same bottle's real touch decided."""
    log = load_touched()
    wrong = log.setdefault(str(item), {}).setdefault('wrong', [])
    left = {n: xy for n, xy in bottles.items() if n not in wrong}
    if wrong:
        t.say(f'[{LEADER}] {name}这一轮已经点错过: {wrong}')
    lost = 0
    close = None                                  # a bottle that showed nothing from afar: touch it again up close
    for i in range(1, TRIES + 1):
        if has(lead, item):
            log.pop(str(item), None)
            save_touched(log)
            return
        if not left:
            break
        back_in_cage(lead)
        if close:
            npc, spot = nearest(lead, {close: left[close]}, CLOSE_REACH)
        else:
            npc, spot = nearest(lead, left)
        walk(lead, spot, f'{name}瓶 {npc} 的点击位')
        settle(lead)
        here = lead.world()
        click(lead, npc)
        outcome = watch(lead, here, item)
        far = math.dist((here.x, here.y), left[npc]) > CLOSE_REACH + 50
        close = None
        if outcome == 'hp' and far:
            # 16:08 live: 4067 from 450 px showed nothing (no chat line either) and gave the crystal from 199 px.
            # Memory cannot tell「no answer」from the hp penalty (no hp reader yet) -> once more from up close.
            close = npc
            t.say(f'[{LEADER}] 第 {i} 次碰 {npc}: 没看到结果（可能太远没收到），走近再点一次')
            continue
        if outcome == 'got':
            t.say(f'[{LEADER}] 第 {i} 次碰 {npc}: 拿到{name}')
            continue
        if outcome == 'battle' and lost < LOST_MAX:
            lost += 1
            t.say(f'[{LEADER}] 第 {i} 次碰 {npc}: 被遇怪打断，不算，打完原地重点')
            continue
        t.say(f'[{LEADER}] 第 {i} 次碰 {npc}: 错，' + ('被传送走了' if outcome == 'moved' else '扣血'))
        wrong.append(npc)
        del left[npc]
        save_touched(log)
    if not has(lead, item):
        raise t.Stop(f'{name}的瓶子都碰过了还没拿到: {sorted(bottles)}')


def summon(lead):
    _, spot = nearest(lead, {LIULI: LIULI_XY})
    walk(lead, spot, '琉璃瓶的点击位')
    start_boss(lead, LIULI, '召唤', '琉璃瓶')


def start_boss(lead, npc, word, what):
    """Click the boss NPC (raw 0x50), pick the option containing `word`, until the battle starts. Shared with
    tiger_fight.py (2026-11-06: 虎力仙「开打」behaved the same: the first pick started nothing, the second did)."""
    for attempt in range(1, 5):
        settle(lead)
        click(lead, npc)                          # raw 0x50 opened the menu from 100..500 px (2026-11-06)
        try:
            d = t.wait(lambda: lead.dialog(), 5, f'{what}菜单')
        except t.Stop:
            # live 2026-11-06 13:48: an encounter started with the click and swallowed it -> fight, click again
            t.say(f'第 {attempt} 次点{what}没出菜单{"（遇怪了）" if lead.world().in_battle else ""}，再点')
            continue
        opt = next((o for o, l in d.options if word in t.plain(l)), None)
        if opt is None:
            raise t.Stop(f'{what}菜单里没有「{word}」: {[t.plain(l) for _, l in d.options]}')
        lead.game.select_dialog(opt)
        end = time.monotonic() + 8
        while time.monotonic() < end and not lead.world().in_battle:
            time.sleep(0.2)
        if lead.world().in_battle:
            return
        # same as scorpion_king: the first「开打」becomes the boss quiz; answered, the next pick starts the battle
        if boss_quiz.solve(lead, say=t.say) is None:
            t.say(f'第 {attempt} 次没进战斗，也没有 boss 题面板，再点')
        t.wait(lambda: not getattr(lead.world(), 'verification', False), 120, '答题结束')
        if boss_quiz.kicked(lead):
            raise t.Stop(f'[{LEADER}] boss 题答错被踢下线，重登后重跑这一步')
        time.sleep(1)
    raise t.Stop(f'点了 4 次{what}都没进战斗')


def main():
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    if all(step_done(c, EAGLE_STEP) for c in cs):
        t.say('五人都已经打过独眼鹰王，跳过')
        return
    if not steps(lead):
        raise t.Stop(f'{LEADER} 没有任务 1130，先跑 take_eagle.py')
    if lead.world().map_id != CAGE or set(lead.team()) != {c.char_id for c in cs}:
        raise t.Stop(f'五人不在陷阱囚牢或队伍不全（map {lead.world().map_id}，队伍 {lead.team()}），先跑 enter_cage.py')
    for name, step, item, bottles in KINDS:
        if not step_done(lead, step) or not has(lead, item):
            crystal(lead, name, item, bottles)
    summon(lead)
    fight_out(lead, 900, '鹰王战斗')
    t.wait(lambda: all(step_done(c, EAGLE_STEP) for c in cs), 10, '五人任务「战胜独眼鹰王」完成')
    save_touched({})                            # the right bottles are dealt anew next round
    t.say('独眼鹰王打完，五人任务都到「回去告诉莫吉」这一步')


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
