"""5-man boss-gear line, 电锯杀人王 step 4: in 惊魂监狱 (map 264) take 死亡游戏 (quest 1853) at the 机关, beat one
prisoner of each group for a key, open the 机关 with a full set, beat 电锯杀人狂 (quest 1852 step 0) (user 2026-11-06).

    python -X utf8 prison_fight.py

Live 2026-11-06 (4 roles, 欧皇丨花花乀 out: no 龙之都公民证):
- The prison entrance lands at (2369,2000), next to 惊魂监狱机关 1336:「继续」->「接受」gives quest 1853 死亡游戏
  (1,1,1,1) to the LEADER only. Steps 0..2 = the three keys, step 3 = open the 机关.
- A prisoner's menu is only「迎战」; the first pick starts the battle. Only the leader gets the key (1853 step of
  that group 1 -> 2). Round 1: 1333 巡警 177 s -> 11297, 1330 猎人 96 s -> 11295, 1334 警察 127 s -> 11299.
- That odd-numbered set (11295 / 11297 / 11299) was right: 机关 1336「如果要开启机关，请点确定」-> 确定 took the keys,
  ended 1853 and moved the whole team to (3618,5175) in the boss part (not connected on foot to the rest).
- 电锯杀人狂 1337 (3498,5139), 125 px from there: ★惊魂监狱的杀人狂［进行中］->「我是来干掉你的」starts the battle at
  once (no boss quiz); 48 s with four casting, quest 1852 step 0 done for all four.
- Walking: ~22000 px of path for landing -> 行刑官 -> 看守 -> 监狱官 -> 机关, encounters on the way (51-52 级).
Which set to try: the last good one (state file); a group whose key the leader already holds is skipped, so a rerun
picks up anywhere.
"""
import json
import time

from _bootstrap import BATCH, LEADER, ROLES

import chainsaw as cz
import tiger as tg
import trial_run as t
from eagle_cage import settle, start_boss
from provisioner import world as w
from take224 import talk
from tiger_fight import fight_all

GAME = 1853
REACH = 200
STATE = BATCH / 'runtime' / 'boss_gear_5_chainsaw.json'


class ChainsawLost(t.Stop):
    """The team lost a fight in the prison (out of the map afterwards). round_chainsaw.py starts the round over."""


def game_steps(c):
    q = w.read_quest(c.mem, GAME)
    return q.steps if q and q.active else ()


def load_state():
    try:
        return json.loads(STATE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def save_state(state):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding='utf-8')


def take_game(lead):
    if game_steps(lead):
        return
    cz.walk(lead, cz.MACHINE_XY, '惊魂监狱机关', reach=REACH, fix='enter_prison.py')
    d = tg.open_npc(lead, cz.MACHINE, '惊魂监狱机关')
    talk(lead, cz.MACHINE, ['继续', '接受'], d)
    tg.close(lead)
    t.wait(lambda: game_steps(lead), 5, f'{LEADER} 接到死亡游戏（任务 1853）')
    t.say(f'[{LEADER}] 接了死亡游戏 {game_steps(lead)}')


def fight(cs, npc, xy, what, won):
    """Walk to npc, pick「迎战」/「开打」, everybody casts; won(lead) tells the fight was the right one."""
    lead = cs[0]
    for attempt in range(1, 4):
        cz.walk(lead, xy, what, reach=REACH, fix='enter_prison.py')
        start_boss(lead, npc, '迎战', what)
        f0 = time.monotonic()
        fight_all(cs, 900, f'{what}战斗')
        time.sleep(2)
        if lead.world().map_id != cz.PRISON:
            raise ChainsawLost(f'打输了{what}：队长在 map {lead.world().map_id}，任务 {cz.steps(lead)}')
        try:
            t.wait(lambda: won(lead), 10, f'打完{what}')
            t.say(f'[{LEADER}] 打完{what}（{time.monotonic() - f0:.0f} 秒）')
            return
        except t.Stop:
            t.say(f'[{LEADER}] 第 {attempt} 次打完{what}没拿到东西: {cz.keys(lead)} {game_steps(lead)}')
    raise t.Stop(f'打了 3 次{what}还没拿到东西')


SETS = ((11295, 11297, 11299), (11296, 11298, 11300))     # live round 1: the odd one opened the 机关
BOSS_LAND = (3618, 5175)
_BOSS_PART = None


def in_boss_part(c):
    global _BOSS_PART
    s = c.world()
    if s.map_id != cz.PRISON:
        return False
    g = cz.grid(cz.PRISON)
    if _BOSS_PART is None:
        _BOSS_PART = set(g.distances(BOSS_LAND))
    return g.nearest_walkable(*g.cell(s.x, s.y), limit=4) in _BOSS_PART


def held(lead):
    return {b.item_id for b in w.read_bag(lead.mem) or () if b.item_id in cz.KEYS}


def pick_set(lead, state):
    """The set to collect: the one the held keys belong to, else the last good one, else the odd one."""
    have = held(lead)
    for keys in SETS:
        if have and have <= set(keys):
            return keys
    if have:
        raise t.Stop(f'[{LEADER}] 身上的钥匙不是同一套: {cz.keys(lead)}')
    good = state.get('good')
    return tuple(good) if good else SETS[0]


def collect(cs, keys):
    lead = cs[0]
    todo = []
    for group, key in zip(cz.PRISONERS, keys):
        if key in held(lead):
            continue
        npc, xy, _ = next(p for p in group if p[2] == key)
        todo.append((npc, xy, key))
    while todo:                                   # nearest group by path first
        s = lead.world()
        dist = cz.grid(cz.PRISON).distances((s.x, s.y))
        todo.sort(key=lambda p: (cz.grid(cz.PRISON).touch_spot(dist, p[1], REACH) or (1e9,))[0])
        npc, xy, key = todo.pop(0)
        fight(cs, npc, xy, f'俘虏 {npc}（{cz.KEYS[key]}）', lambda c, k=key: k in held(c))


def open_machine(cs, keys, state):
    lead = cs[0]
    cz.walk(lead, cz.MACHINE_XY, '惊魂监狱机关', reach=REACH, fix='enter_prison.py')
    d = tg.open_npc(lead, cz.MACHINE, '惊魂监狱机关')
    talk(lead, cz.MACHINE, ['确定'], d)
    try:
        t.wait(lambda: in_boss_part(lead), 10, '开机关传到电锯杀人狂那块')
    except t.Stop:
        tg.close(lead)
        s = lead.world()
        state['wrong'] = sorted(set(state.get('wrong', [])) | {','.join(map(str, keys))})
        save_state(state)
        raise t.Stop(f'开机关没传过去（钥匙 {list(keys)}，队长在 map {s.map_id} ({s.x:.0f},{s.y:.0f})，'
                     f'剩下钥匙 {cz.keys(lead)}，死亡游戏 {game_steps(lead)}）：手动看一下')
    state['good'] = list(keys)
    save_state(state)
    t.wait(lambda: all(in_boss_part(c) for c in cs), 10, '全队传到电锯杀人狂那块')
    t.say(f'机关开了（钥匙 {[cz.KEYS[k] for k in keys]}），全队到了电锯杀人狂那块')


def boss_fight(cs):
    lead = cs[0]
    for attempt in range(1, 4):
        cz.walk(lead, cz.BOSS_XY, '电锯杀人狂', reach=REACH, fix='enter_prison.py')
        settle(lead)
        d = tg.open_npc(lead, cz.BOSS, '电锯杀人狂')
        talk(lead, cz.BOSS, ['进行中', '干掉你'], d)
        try:
            t.wait(lambda: lead.world().in_battle, 8, '和电锯杀人狂开打')
        except t.Stop:
            tg.close(lead)
            t.say(f'第 {attempt} 次选了「我是来干掉你的」没进战斗，再点')
            continue
        f0 = time.monotonic()
        fight_all(cs, 900, '电锯杀人狂战斗')
        time.sleep(2)
        if lead.world().map_id != cz.PRISON:
            raise ChainsawLost(f'打输了电锯杀人狂：队长在 map {lead.world().map_id}，任务 {cz.steps(lead)}')
        try:
            t.wait(lambda: cz.beaten(lead), 10, '打完电锯杀人狂')
            t.say(f'[{LEADER}] 打完电锯杀人狂（{time.monotonic() - f0:.0f} 秒）')
            return
        except t.Stop:
            t.say(f'[{LEADER}] 第 {attempt} 次打完没算（遇怪？）任务 {cz.steps(lead)}')
    raise t.Stop('打了 3 次电锯杀人狂还没算')


def main():
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    if all(cz.beaten(c) for c in cs):
        t.say('全队都已经打过电锯杀人狂，跳过')
        return
    if not cz.has_quest(lead):
        raise t.Stop(f'{LEADER} 没有任务 1852，先跑 take_chainsaw.py')
    if lead.world().map_id != cz.PRISON or not cz.team_full(cs):
        raise t.Stop(f'全队不在惊魂监狱或队伍不全（map {lead.world().map_id}，队伍 {lead.team()}），先跑 enter_prison.py')
    lacking = [c.name for c in cs if not cz.has_quest(c)]
    if lacking:                                # in a team every member must have the quest
        raise t.Stop(f'{lacking} 没有任务 1852，先跑 take_chainsaw.py')
    t0 = time.monotonic()
    cz.say_state(cs, '开始:')
    if not in_boss_part(lead):
        state = load_state()
        take_game(lead)
        keys = pick_set(lead, state)
        t.say(f'这一轮收集钥匙 {[cz.KEYS[k] for k in keys]}')
        collect(cs, keys)
        t.say(f'三把钥匙齐了（{(time.monotonic() - t0) / 60:.1f} 分钟）')
        open_machine(cs, keys, state)
    boss_fight(cs)
    t.wait(lambda: all(cz.beaten(c) for c in cs), 10, '全队任务「打败电锯杀人狂」完成')
    t.say(f'电锯杀人狂打完（监狱里 {(time.monotonic() - t0) / 60:.1f} 分钟），全队任务都到「找老刘领取奖励」')


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
