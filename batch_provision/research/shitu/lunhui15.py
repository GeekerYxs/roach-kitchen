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
from dataclasses import is_dataclass, replace
from pathlib import Path
from types import SimpleNamespace
import sys
import time

import revive
import trial_run as t
from factory.welltrain import Decision, Fight, Talent, decide_battle, decide_talent
from provisioner import world as w
from provisioner.game import FIGHT_ATTACK
from well10 import form_team

from common import APPRENTICES, MASTERS, TALENT_STAT  # noqa: E402
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
SKILL, SCHOLAR_SKILL, PET_MAGIC, PET_MP_MIN = 803, 354, 1504, 100
# user 2026-11-05: the 元素使 master itself casts its F1 magic: 206 魔法火焰 (the game's own F1 cast sent 0x1005 skill
# 206 lv12; 1504 烈焰爆发 is the pet's, the player got 「无此魔法」). Magic goes out in the manually captured layout
# (game.cast_magic_skill_captured), 扫射 through cast_skill
PLAYER_MAGIC = 206
MAGIC_SKILLS = (SCHOLAR_SKILL, PLAYER_MAGIC)
SKILL_NAMES = {SKILL: '扫射', SCHOLAR_SKILL: '天之箭', PLAYER_MAGIC: '魔法火焰'}
# Pet 烈焰爆发 loop (user 2026-11-05, docs/PET_MAGIC_CONTINUOUS_CASTING_AND_TIANZHIJIAN.md, the 70 project's
# prison_patrol rule): one cast pending at a time; it settles on the server's 0x4111 for the pet's position (tap),
# an SP change, or (no tap) a drop of the pet's MP (the cast ran); then SP > 0 (完美施法 kept the point, or points left) ->
# cast again at once. Replaces the old blind 0.6 s resend (91e7959), which the server ignored while the cast was
# still pending. PET_SETTLE_FALLBACK only when none of the signals comes (no tap).
PET_SETTLE_FALLBACK, PET_TAP_FALLBACK, PET_MAX_CASTS = 3.2, 6.0, 30
# user 2026-11-05: act the moment the server says it is our turn. 0x4105 <u8 pos> = this position just got a
# charge point (live timelines: the command is only taken after it, a command sent at SP 0 is ignored); the
# memory SP follows a little later. SHITU_TURN_PACKET=0 turns this off (A/B test).
TURN_PACKET = os.environ.get('SHITU_TURN_PACKET', '1') != '0'
TURN_HOLD = 0.6
NEAR, ARRIVE = 80, 40
STALL, NAV_RETRY, CLICK_WAIT = 6.0, 2.0, 8.0
TICK = 0.15
# user 2026-11-05: poll every 30 ms while in a battle (A/B on 自由三号, 25 battles each at 0.03 s: 0x4105 -> our
# command median 28 ms player / 32 ms pet, vs ~45 ms reading memory only; the old 0.15 s loop added ~75 ms on top)
BATTLE_TICK = 0.03


class Caster:
    """Choose a learned player attack (猎人 扫射 / 方士 天之箭 / else the first magic slot, 元素使 魔法火焰 206; none of
    them -> 普攻) and pet 烈焰爆发."""

    def __init__(self, c):
        self.c = c
        requested = int(os.environ.get('SHITU_PLAYER_SKILL', '0') or 0) if c.name == LEADER else 0
        candidates = (requested,) if requested else (SKILL, SCHOLAR_SKILL)
        self.skill_id, self.skill = 0, 0
        for skill_id in candidates:
            level = w.read_skill_level(c.mem, skill_id) or 0
            if level:
                self.skill_id, self.skill = skill_id, level
                break
        if not self.skill and not requested:
            # 2026-11-05: 元素使 魔法火焰 is not in the skill vectors; the magic slot holds it with its level
            assist = w.read_assist_skill(c.mem)
            if assist and assist[0] in SKILL_NAMES:
                self.skill_id, self.skill = assist
        self.strict_skill = bool(requested)
        if requested and not self.skill:
            # The user confirmed 354 天之箭 is this 方士's cycle skill, but this build's learned-skill
            # reader does not expose its level. Try the requested skill at a conservative configured level;
            # if it is rejected, stop instead of silently substituting a normal attack.
            self.skill_id = requested
            self.skill = int(os.environ.get('SHITU_PLAYER_SKILL_LEVEL', '1') or 1)
        pet = w.read_fighting_pet(c.mem)
        self.pet_level = pet.abilities.get(PET_MAGIC, 0) if pet else 0
        self.me, self.pet = Fight(), Fight()
        self.casts = 0
        self.tap = pet_tap(c)
        self.reset()
        self.reviver = None
        if c.name in MASTERS and revive.ITEM:          # 2026-11-02 元素使 team: revive downed apprentices
            self.reviver = revive.Reviver(c, APPRENTICES)
        skill_name = SKILL_NAMES.get(self.skill_id, '无人物技能（普攻）') if self.skill else '无人物技能（普攻）'
        level_note = '（技能等级内存未读到，按配置级别尝试）' if requested and not w.read_skill_level(c.mem, requested) else ''
        t.say(f'[{c.name}] {skill_name} lv{self.skill}{level_note}，宠物烈焰爆发 lv{self.pet_level}' +
              (f'，魔力 {pet.mp}' if pet else '，没有出战宠物'))

    def tick(self, now):
        battle = w.read_battle(self.c.mem)
        if self.reviver:
            pet_sent = self.pet.sent_at
            blocked = self.reviver.tick(battle, self, now)
            if self.pet.sent_at != pet_sent and battle and battle.pet:
                self._pet_sent(battle.pet.sp, None, now)    # the reviver made the pet defend: that is its action
            if blocked:
                return
        if battle is None:
            return
        pet = w.read_fighting_pet(self.c.mem)
        pet_ok = bool(self.pet_level) and pet is not None and pet.mp >= PET_MP_MIN
        packets = self.tap.poll() if self.tap else []
        if TURN_PACKET:
            battle = self.with_turns(battle, packets, now)
        if pet_ok and battle.pet and not battle.pet.dead and battle.enemies:
            self.pet_tick(battle, pet, packets, now)
        for who, d in decide_battle(battle, self.me, self.pet, now, bool(self.skill), pet_ok):
            if who == 'pet' and (pet_ok or os.environ.get('SHITU_PET_MAGIC_ONLY') == '1' or d.kind != 'attack'):
                continue                    # the pet casts in pet_tick; a normal attack only once its MP is out
            if who == 'me' and self.strict_skill and d.kind == 'attack':
                raise t.Stop(f'{self.c.name} 指定技能 {self.skill_id} 多次未响应，停止，不退回普攻')
            if d.kind == 'none':
                continue
            is_pet = who == 'pet'
            if d.kind == 'cast':
                if self.skill_id in MAGIC_SKILLS:
                    self.c.game.cast_magic_skill_captured(d.arg, self.skill_id, self.skill)
                else:
                    self.c.game.cast_skill(d.arg, self.skill_id, self.skill)
            else:
                self.c.game.fight_command(FIGHT_ATTACK, is_pet=is_pet, target=d.arg)
            self.casts += 1
            f = battle.pet if is_pet else battle.me
            (self.pet if is_pet else self.me).record(f.sp, now)

    def pet_tick(self, battle, pet, packets, now):
        """One 烈焰爆发 pending at a time; recast at once when it settled with SP left."""
        f = battle.pet
        if self.pet_pending:
            why = pet_settled(f, pet.mp, packets, self.pet_sent, self.tap is not None, now)
            if not why:
                if not self.pet_warned and now - self.pet_sent[2] >= 1.0:
                    self.pet_warned = True
                    t.say(f'[{self.c.name}] 等宠物这次出手结算，不重复发（SP={f.sp}）')
                return
            self.pet_pending = False
            server_sp = server_pet_sp(packets, f.pos)
            if server_sp == 0 and f.sp > 0:
                self.pet_stale_sp = f.sp      # 2026-11-05 自由三号: 0x4111 said 0 while memory still showed 1
            elif f.sp > 0:
                t.say(f'[{self.c.name}] 宠物出手结算（{why}），蓄力还剩 {f.sp}：立即再放烈焰爆发')
        if self.pet_stale_sp is not None:
            if f.sp == self.pet_stale_sp and not server_pet_sp(packets, f.pos):
                return                        # memory not moved, and no new point from the server either
            self.pet_stale_sp = None
        if f.sp > 0 and self.pet_casts < PET_MAX_CASTS:
            self.c.game.cast_pet_magic(battle.enemies[0], PET_MAGIC, self.pet_level)
            self.pet.record(f.sp, now)
            self.pet_casts += 1
            self._pet_sent(f.sp, pet.mp, now)

    def with_turns(self, battle, packets, now):
        """battle with SP >= 1 for our fighters whose 0x4105 turn packet came, held TURN_HOLD s or until their 0x4111
        settle: the memory SP follows later, and a 0 read in between must not count as a spent point."""
        for _, d, op, body, _ in packets:
            if d != 'S->C' or not body:
                continue
            if op == 0x4105 and len(body) == 1:
                self.turn_hold[body[0]] = now + TURN_HOLD
            elif op == 0x4111 and len(body) == 2:
                self.turn_hold.pop(body[0], None)
        held = {pos for pos, until in self.turn_hold.items() if until > now}
        if not held:
            return battle

        def bump(f):
            return replace(f, sp=1) if f is not None and f.pos in held and f.sp == 0 and not f.dead else f
        if is_dataclass(battle):
            return replace(battle, me=bump(battle.me), pet=bump(battle.pet))
        return SimpleNamespace(**{**vars(battle), 'me': bump(battle.me), 'pet': bump(battle.pet)})

    def _pet_sent(self, sp, mp, now):
        self.pet_sent, self.pet_pending, self.pet_warned = (sp, mp, now), True, False

    def reset(self):
        self.me, self.pet = Fight(), Fight()
        self.pet_pending, self.pet_warned, self.pet_sent, self.pet_casts = False, False, (None, None, 0.0), 0
        self.pet_stale_sp = None
        self.turn_hold = {}


def server_pet_sp(packets, pos):
    """The pet's SP from the newest 0x4111 <u8 pos><u8 sp> for its position in packets, or None."""
    sp = None
    for _, d, op, body, _ in packets:
        if d == 'S->C' and op == 0x4111 and len(body) == 2 and body[0] == pos:
            sp = body[1]
    return sp


def pet_settled(f, mp, packets, sent, has_tap, now):
    """Why the pending pet cast counts as done, or None. sent = (sp, pet mp, time) when it was sent."""
    sp0, mp0, at = sent
    # packets are the ones polled after the send (each tick polls before it may cast); tap stamps are wall time
    if any(d == 'S->C' and op == 0x4111 and len(body) == 2 and body[0] == f.pos for _, d, op, body, _ in packets):
        return '服务器结束包'
    if has_tap:
        # with a tap the memory SP lags the packets (a 0 read before it catches up is not a settle)
        if f.sp > sp0:
            return f'蓄力 {sp0} -> {f.sp}'
        if now - at >= PET_TAP_FALLBACK:
            return f'{PET_TAP_FALLBACK:.0f}s 没等到结束包'
        return None
    if f.sp != sp0:
        return f'蓄力 {sp0} -> {f.sp}'
    # MP drops when the cast runs (0x4106), before the server settles it (0x4111, 2026-11-05 自由三号 ~60 ms later):
    # only a no-tap client goes by it, else a second recast follows for the same action
    if not has_tap and mp0 is not None and mp < mp0:
        return f'宠物蓝 {mp0} -> {mp}'
    if not has_tap and now - at >= PET_SETTLE_FALLBACK:
        return f'{PET_SETTLE_FALLBACK:.1f}s 兜底'
    return None


def pet_tap(c):
    """monitor.Tap on this client's packet log (our DLL or the BattleAssist one: the folder beside the loaded DLL
    that holds tap_<pid>_codec.json), or None."""
    import monitor
    from common import modules
    pid = getattr(c, 'pid', None)
    if not pid:
        return None
    try:
        for _, path in modules(pid):
            p = Path(path)
            if p.suffix.lower() != '.dll':
                continue
            for root in (p.parent.parent / 'runtime', p.parent.parent.parent / 'runtime'):
                if (root / f'tap_{pid}_codec.json').is_file():
                    monitor.RUNTIME = root
                    tap = monitor.Tap(pid, from_end=True)
                    if tap.ready():
                        return tap
    except (OSError, ValueError):
        return None
    return None


def leads(c):
    """Alone, or the team's leader: this role's battle is its own to fight."""
    team = c.team()
    return not team or team[0] == c.char_id


class BattleHand:
    """For walk loops that used to wait out a battle under the game's auto-skill (user 2026-11-05: every battle
    the leader's pet casts 烈焰爆发 at once and recasts while SP is left): call tick() every poll in a battle."""

    def __init__(self, c):
        self.c, self.caster = c, None

    def tick(self, now=None):
        if self.caster is None:
            if not leads(self.c):
                return
            self.caster = Caster(self.c)
        self.caster.tick(time.monotonic() if now is None else now)

    def done(self):
        if self.caster:
            self.caster.reset()


def fight_out(c, timeout=120, why=None):
    """Until c is out of its battle; the leader (or a solo role) fights it with Caster, a member only waits."""
    hand, end = BattleHand(c), time.monotonic() + timeout
    while c.world().in_battle:
        if time.monotonic() > end:
            raise t.Stop(f'{why or c.name + " 战斗结束"} 超时 {timeout}s')
        hand.tick()
        time.sleep(BATTLE_TICK)
    hand.done()


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
    gone = t.Gone()                      # a dropped client: fail after 30 s, not the 15-min watchdog (2026-11-05)
    import trash
    trasher = trash.Trasher([cs[n] for n in APPRENTICES if n in cs])     # 葫芦 / 特赦令 / 整人道具 every 20 min
    while True:
        now = time.monotonic()
        sts = {n: c.world() for n, c in cs.items()}
        if gone.tick(sts):
            time.sleep(TICK)
            continue
        trasher.tick(sts, now)
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
                t.say(f'[{n}] {d.reason.replace("体质", TALENT_STAT)}')
                cs[n].game.add_talent(d.arg, TALENT_STAT)
                tm.sent_at, tm.before = now, pts
            elif d.kind == 'verified':
                tm.sent_at, tm.misses = None, 0
            elif d.kind == 'unconfirmed':
                t.say(f'[{n}] {d.reason.replace("体质", TALENT_STAT)}')
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
