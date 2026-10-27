"""师徒 leveling 10 -> 15 in 轮回之城 (map 555): 伏地魔1 leads 伏地魔2 + 十万1..3 from 平静海岸2区 (81).

    python -X utf8 research/shitu/lunhui15.py [target level, default 15]

User's orders (2026-10-27): 伏地魔1 = leader, enter 轮回之城 from the current map, patrol and fight, stop once
every apprentice is at the target level and wait for the next order. 伏地魔1 and 伏地魔2 cast 扫射 803, their
pets 烈焰爆发 1504, every turn (fixed loop); the apprentices send nothing (factory welltrain: member attacks only
make rounds longer). All apprentice talent points go to 体质.
Route: 81 -> 轮回之城 entrance NPC 10158 (1635,3041) -> click (a menu option with 轮回 is picked if one opens)
-> 555 (lands at (2754,291)) -> patrol PATROL A <-> B (the user's points).
Every tick decides from what is read, so a restart continues.
"""
import math
import sys
import time

import trial_run as t
from factory.welltrain import Fight, Talent, decide_battle, decide_talent
from provisioner import world as w
from provisioner.game import FIGHT_ATTACK
from well10 import form_team

from common import APPRENTICES, MASTERS  # noqa: E402
import os  # noqa: E402
# the two 70s: 扫射 + pet 烈焰爆发 whoever leads; SHITU_CASTERS overrides (a role without 扫射 just attacks)
CASTERS = tuple(os.environ.get('SHITU_CASTERS', ','.join(MASTERS)).split(','))
# team leader (walks, clicks NPCs). Default 伏地魔1; round 2 (04:48) the cave needs an apprentice: the flowers offer
#「采集」only to a role whose task 224 is at step 1, and they are 不可交易 -> the gatherer leads the snake fight too
LEADER = os.environ.get('SHITU_LEADER', CASTERS[0])
MEMBERS = tuple(n for n in dict.fromkeys(CASTERS + APPRENTICES) if n != LEADER)
HELPERS = tuple(n for n in CASTERS if n != LEADER)
COAST, MAZE = 81, 555
ENTRANCE, ENTRANCE_NPC = (1635, 3041), 10158
PATROL = ((2754, 291), (2550, 616))     # user 2026-10-27: the landing point <-> (2550,616); the 路标 NPCs are behind
                                        # walls the path-finder cannot cross from the landing area (live 00:52-00:54)
SKILL, PET_MAGIC, PET_MP_MIN = 803, 1504, 100
NEAR, ARRIVE = 80, 40
STALL, NAV_RETRY, CLICK_WAIT = 6.0, 2.0, 8.0
TICK = 0.15


class Caster:
    """One 70: player 扫射 + pet 烈焰爆发 on the first live enemy whenever SP changes (welltrain.decide_battle)."""

    def __init__(self, c):
        self.c = c
        self.skill = w.read_skill_level(c.mem, SKILL) or 0
        pet = w.read_fighting_pet(c.mem)
        self.pet_level = pet.abilities.get(PET_MAGIC, 0) if pet else 0
        self.me, self.pet = Fight(), Fight()
        self.casts = 0
        t.say(f'[{c.name}] 扫射 lv{self.skill}，宠物烈焰爆发 lv{self.pet_level}' + (f'，魔力 {pet.mp}' if pet else '，没有出战宠物'))

    def tick(self, now):
        battle = w.read_battle(self.c.mem)
        pet = w.read_fighting_pet(self.c.mem)
        pet_ok = bool(self.pet_level) and pet is not None and pet.mp >= PET_MP_MIN
        for who, d in decide_battle(battle, self.me, self.pet, now, bool(self.skill), pet_ok):
            if d.kind == 'none':
                continue
            is_pet = who == 'pet'
            if d.kind == 'cast' and is_pet:
                self.c.game.cast_pet_magic(d.arg, PET_MAGIC, self.pet_level)
            elif d.kind == 'cast':
                self.c.game.cast_skill(d.arg, SKILL, self.skill)
            else:
                self.c.game.fight_command(FIGHT_ATTACK, is_pet=is_pet, target=d.arg)
            self.casts += 1
            f = battle.pet if is_pet else battle.me
            (self.pet if is_pet else self.me).record(f.sp, now)

    def reset(self):
        self.me, self.pet = Fight(), Fight()


class Route:
    def __init__(self):
        self.last_nav, self.progress_xy, self.progress_at = -1e9, None, 0.0
        self.clicked_at, self.clicks = None, 0
        self.points, self.target, self.stalls = None, 0, 0
        self.last_reason = None

    def say(self, msg):
        if msg != self.last_reason:
            t.say(f'[{LEADER}] {msg}')
            self.last_reason = msg

    def walk(self, lead, st, map_id, xy, now, why):
        if self.progress_xy is None or math.dist((st.x, st.y), self.progress_xy) > 15:
            self.progress_xy, self.progress_at = (st.x, st.y), now
        if st.nav_active or st.moving:
            if now - self.progress_at > STALL:
                self.say(f'{STALL:.0f}s 没动，重新寻路（{why}）')
                lead.game.cancel_navigation()
                self.last_nav = -1e9
                self.stalls += 1
            return
        if now - self.last_nav < NAV_RETRY:
            return
        self.say(f'寻路{why}（距离 {math.dist((st.x, st.y), xy):.0f}）')
        lead.game.navigate(map_id, *xy)
        self.last_nav, self.progress_xy, self.progress_at = now, (st.x, st.y), now

    def tick(self, lead, st, now):
        if st.in_battle or st.busy or st.verification:
            self.progress_at = now
            self.last_nav = -1e9 if st.in_battle else self.last_nav
            return
        if st.map_id == COAST:
            if st.dialog:
                hit = [(o, l) for o, l in st.dialog.options if o and '轮回' in l] or \
                      [(o, l) for o, l in st.dialog.options if o][:1]
                if not hit:
                    raise t.Stop(f'轮回之城入口对话框不认识: {st.dialog.text!r} {st.dialog.options}')
                self.say(f'入口对话框: {st.dialog.options}，选「{hit[0][1]}」')
                lead.game.select_dialog(hit[0][0])
                time.sleep(1)
                return
            if math.dist((st.x, st.y), ENTRANCE) > NEAR:
                return self.walk(lead, st, COAST, ENTRANCE, now, '去轮回之城入口')
            if st.nav_active:
                lead.game.cancel_navigation()
                return
            if self.clicked_at and now - self.clicked_at < CLICK_WAIT:
                return
            if self.clicks >= 3:
                raise t.Stop('点了 3 次轮回之城入口都没进去')
            self.say(f'点轮回之城入口 NPC {ENTRANCE_NPC}')
            lead.game.click_npc(ENTRANCE_NPC)
            self.clicked_at, self.clicks = now, self.clicks + 1
            return
        if st.map_id != MAZE:
            raise t.Stop(f'{LEADER} 在意外的地图 {st.map_id}')
        if self.points is None:
            self.points = PATROL
            self.say(f'在轮回之城 ({st.x:.0f},{st.y:.0f})；巡逻 {PATROL[0]} <-> {PATROL[1]}')
        xy = self.points[self.target]
        if self.stalls >= 3:
            raise t.Stop(f'巡逻点 {xy} 走不到（卡住 3 次）')
        if math.dist((st.x, st.y), xy) <= ARRIVE and not st.moving:
            self.target, self.stalls, self.last_nav = 1 - self.target, 0, -1e9
            return
        self.walk(lead, st, MAZE, xy, now, f'巡逻去 {"AB"[self.target]} 点 {xy}')


def main(target):
    cs = {n: t.Client(n) for n in (LEADER,) + MEMBERS}
    lead = cs[LEADER]
    for n, c in cs.items():
        s = c.world()
        t.say(f'[{n}] 等级 {w.read_level(c.mem)} 地图 {s.map_id} ({s.x:.0f},{s.y:.0f}) 天赋 {w.read_talent_points(c.mem)}')
    form_team(lead, [cs[n] for n in MEMBERS])
    casters = [Caster(cs[n]) for n in CASTERS]
    talents = {n: Talent() for n in APPRENTICES}
    route = Route()
    battles, in_battle, last_levels, t0 = 0, False, None, time.monotonic()
    while True:
        now = time.monotonic()
        sts = {n: c.world() for n, c in cs.items()}
        if any(s is None for s in sts.values()):
            time.sleep(TICK)
            continue
        missing = [n for n, c in cs.items() if c.char_id not in lead.team()]
        if missing:
            raise t.Stop(f'{missing} 不在 {LEADER} 的队里了（掉线或死亡？）')
        levels = {n: w.read_level(cs[n].mem) for n in APPRENTICES}
        if levels != last_levels:
            t.say(f'等级 {levels}，战斗 {battles} 场，用时 {(now - t0) / 60:.1f} 分')
            last_levels = levels
        for n in APPRENTICES:
            tm, pts = talents[n], w.read_talent_points(cs[n].mem)
            d = decide_talent(pts, tm, now)
            if d.kind == 'add':
                t.say(f'[{n}] {d.reason}')
                cs[n].game.add_constitution(d.arg)
                tm.sent_at, tm.before = now, pts
            elif d.kind == 'verified':
                tm.sent_at, tm.misses = None, 0
            elif d.kind == 'unconfirmed':
                t.say(f'[{n}] {d.reason}')
                tm.sent_at, tm.misses, tm.last_miss = None, tm.misses + 1, now
        lw = sts[LEADER]
        if lw.in_battle != in_battle:
            in_battle = lw.in_battle
            battles += in_battle
            if not in_battle:
                for c in casters:
                    c.reset()
        if not lw.in_battle and all(v >= target for v in levels.values()) and \
                all(w.read_talent_points(cs[n].mem) == 0 for n in APPRENTICES):
            if lw.nav_active:
                lead.game.cancel_navigation()
            t.say(f'全部到 {target} 级 {levels}，共 {battles} 场，{(now - t0) / 60:.1f} 分；'
                  f'停在地图 {lw.map_id} ({lw.x:.0f},{lw.y:.0f})，等下一步')
            return
        for c in casters:
            if sts[c.c.name].in_battle:
                c.tick(now)
        route.tick(lead, lw, now)
        time.sleep(TICK)


if __name__ == '__main__':
    try:
        main(int(sys.argv[1]) if len(sys.argv) > 1 else 15)
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
