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
import time

from _bootstrap import BATCH, LEADER, ROLES

import boss_quiz
import pp_chain
import trial_run as t
from lunhui15 import fight_out
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
DONE = 2                    # read_quest step value of a finished step
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


def walk(lead, xy, why):
    for attempt in range(5):                  # live 12:57: battles on the way ate pp_chain.walk's 120 s
        fight_out(lead, 300)
        try:
            pp_chain.walk(lead, CAGE, xy, why)
            return
        except t.Stop:
            if attempt == 4:
                raise
    fight_out(lead, 300)


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
    for i in range(1, TRIES + 1):
        if has(lead, item):
            log.pop(str(item), None)
            save_touched(log)
            return
        if not left:
            break
        st = lead.world()
        npc, xy = min(left.items(), key=lambda kv: math.dist((st.x, st.y), kv[1]))
        walk(lead, xy, f'{name}瓶 {npc}')
        settle(lead)
        here = lead.world()
        lead.game.click_npc(npc)
        time.sleep(2.5)
        s = lead.world()
        if has(lead, item):
            t.say(f'[{LEADER}] 第 {i} 次碰 {npc}: 拿到{name}')
            continue
        if s.in_battle and lost < LOST_MAX:
            lost += 1
            t.say(f'[{LEADER}] 第 {i} 次碰 {npc}: 被遇怪打断，不算，打完原地重点')
            continue
        jumped = math.dist((here.x, here.y), (s.x, s.y)) > JUMP or s.map_id != here.map_id
        t.say(f'[{LEADER}] 第 {i} 次碰 {npc}: 错，' + ('被传送走了' if jumped else '扣血'))
        wrong.append(npc)
        del left[npc]
        save_touched(log)
    if not has(lead, item):
        raise t.Stop(f'{name}的瓶子都碰过了还没拿到: {sorted(bottles)}')


def summon(lead):
    walk(lead, LIULI_XY, '琉璃瓶')
    for attempt in range(1, 5):
        fight_out(lead, 300)
        lead.game.click_npc(LIULI)
        try:
            d = t.wait(lambda: lead.dialog(), 5, '琉璃瓶菜单')
        except t.Stop:
            # live 2026-11-06 13:48: an encounter started with the click and swallowed it -> fight, click again
            t.say(f'第 {attempt} 次点琉璃瓶没出菜单{"（遇怪了）" if lead.world().in_battle else ""}，再点')
            continue
        opt = next((o for o, l in d.options if '召唤' in t.plain(l)), None)
        if opt is None:
            raise t.Stop(f'琉璃瓶菜单里没有「召唤鹰王战斗」: {[t.plain(l) for _, l in d.options]}')
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
    raise t.Stop('点了 4 次琉璃瓶都没进战斗')


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
