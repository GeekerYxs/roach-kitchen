"""曾经不曾 five-person patrol in 惊魂监狱 (264), with strict party-presence recovery.

Starts at the prison landing (or the captain's current point on map 264), initially patrols to (1000, 2900).
Once every apprentice reaches level 51, patrols between (1600, 500) and (1200, 700) until level 53.
Only the 方士 captain uses 天之箭 354 lv7 and pet 烈焰爆发 1504. Apprentices issue no battle commands.
If anyone leaves the prison or the five-person roster becomes incomplete, the captain stops the patrol and returns
to (2369, 2000). A missing role may use its recorded map-24 shoe point, enter through NPC 1339, and rejoin there;
shoe cooldowns are respected instead of repeatedly sending a return request.
"""
import _bootstrap  # noqa: F401
import math
import os
import time
from pathlib import Path

import monitor
import shoe_point
import trial_run as t
from common import modules, TALENT_STAT
from provisioner import world as w
from factory.welltrain import Fight, Talent, decide_talent
from well10 import form_team

LEADER = os.environ.get('SHITU_LEADER', '曾经不曾')
APPRENTICES = tuple(n for n in os.environ.get(
    'SHITU_APPRENTICES', '元素使01,元素使02,元素使03,元素使04').split(',') if n)
ROLES = (LEADER,) + APPRENTICES
MAP_ID = 264
PRISON_MAP = 264
CITY_MAP, CITY_SHOE = 24, (2982, 3303)
ENTRANCE_NPC, ENTRANCE_XY = 1339, (5660, 3258)
PICKUP = (2369, 2000)
PATROL_END = (1000, 2900)
PATROL_START = (2369, 2000)
PATROL_AT_51 = ((1600, 500), (1200, 700))
PLAYER_SKILL, PLAYER_LEVEL = 354, 7
PET_MAGIC, MIN_PET_MP = 1504, 100
TICK, ARRIVE, STALL = 0.15, 70, 8.0
INVITE_NEAR = 130
PICKUP_SETTLE_SECONDS = 3.0
PET_ACTION_FALLBACK = 3.2   # used only if this already-running client has no live packet tap
MAX_PET_CASTS = 30
PRISON_TARGET_LEVEL = int(__import__('os').environ.get('SHITU_PRISON_TARGET_LEVEL', '53'))


def say(msg):
    t.say(f'[{LEADER}] {msg}')


class CaptainCombat:
    def __init__(self, lead):
        self.c = lead
        self.player = Fight()
        self.pet_level = 0
        self.pet_memo_sp = None
        self.pet_pending = False
        self.pet_sent_at = 0.0
        self.pet_warned = False
        self.pet_blocked_sp = None
        self.pet_casts = 0
        self.last_battle = False
        pet = w.read_fighting_pet(lead.mem)
        if pet:
            self.pet_level = pet.abilities.get(PET_MAGIC, 0)
        if not self.pet_level:
            raise t.Stop(f'队长没有出战宠物或宠物未学烈焰爆发 {PET_MAGIC}')
        # The learned-skill reader does not expose 354 on this role; level 7 was confirmed by the user.
        say(f'战斗配置：方士天之箭 {PLAYER_SKILL} lv{PLAYER_LEVEL}，宠物烈焰爆发 {PET_MAGIC} lv{self.pet_level}')

        self.tap = None
        dll = next((Path(path) for _, path in modules(lead.pid) if 'provision_native' in path.lower()), None)
        if dll:
            # The DLL writes beside its own bin folder. A valid older runtime can also be tailed if this build uses
            # the shared batch runtime; Tap starts at EOF, so old packets are never mistaken for current actions.
            roots = (dll.parent.parent / 'runtime', dll.parent.parent.parent / 'runtime')
            for root in roots:
                monitor.RUNTIME = root
                candidate = monitor.Tap(lead.pid, from_end=True)
                try:
                    if candidate.ready():
                        self.tap = candidate
                        break
                except (ValueError, OSError):
                    continue
        say('宠物行动结束包监听已就绪' if self.tap else
            f'当前客户端无可用实时封包监听；同蓄力重试使用 {PET_ACTION_FALLBACK:.1f}s 保守间隔')

    def reset(self):
        self.player = Fight()
        self.pet_memo_sp = None
        self.pet_pending = False
        self.pet_sent_at = 0.0
        self.pet_warned = False
        self.pet_blocked_sp = None
        self.pet_casts = 0

    def tick(self, now):
        battle = w.read_battle(self.c.mem)
        if not battle:
            return
        live_pet = w.read_fighting_pet(self.c.mem)
        pet_ok = bool(live_pet and live_pet.mp >= MIN_PET_MP)
        if not battle.me or battle.me.dead or not battle.enemies:
            return
        target = battle.enemies[0]

        # 方士 uses the captured manual magic packet layout; never substitute a normal attack.
        me_sp = battle.me.sp
        if self.player.last_sp is None or me_sp != self.player.last_sp or \
                (me_sp > 0 and now - self.player.sent_at >= 5.0):
            self.c.game.cast_magic_skill_captured(target, PLAYER_SKILL, PLAYER_LEVEL)
            self.player.record(me_sp, now)
            say(f'队长天之箭 lv{PLAYER_LEVEL}，SP={me_sp}，目标位={target}')

        pet = battle.pet
        if not pet or pet.dead or not pet_ok:
            return
        packets = self.tap.poll() if self.tap else []
        pet_done = any(direction == 'S->C' and opcode == 0x4111 and len(body) == 2
                       and body[0] == pet.pos and stamp >= self.pet_sent_at
                       for stamp, direction, opcode, body, _caller in packets)
        charge_changed = self.pet_pending and pet.sp != self.pet_memo_sp
        fallback_done = (self.pet_pending and not self.tap and pet.sp > 0 and
                         now - self.pet_sent_at >= PET_ACTION_FALLBACK)
        if self.pet_pending and (pet_done or charge_changed or fallback_done):
            self.pet_pending = False
            self.pet_warned = False
            if pet.sp > 0:
                self.pet_blocked_sp = None
                say(f'宠物行动结束，仍剩蓄力 {pet.sp}：立即继续烈焰爆发')
            else:
                self.pet_blocked_sp = 0
        elif self.pet_pending and not self.pet_warned and now - self.pet_sent_at >= 1.0:
            self.pet_warned = True
            say('等待宠物本次行动结算；暂不重复发包')

        if not self.pet_pending and pet.sp > 0 and pet.sp != self.pet_blocked_sp and \
                self.pet_casts < MAX_PET_CASTS:
            self.c.game.cast_pet_magic(target, PET_MAGIC, self.pet_level)
            self.pet_memo_sp, self.pet_sent_at, self.pet_pending = pet.sp, now, True
            self.pet_casts += 1
            self.pet_warned = False
            say(f'宠物烈焰爆发 lv{self.pet_level}，SP={pet.sp}，目标位={target}（本场第 {self.pet_casts} 次）')
        elif self.pet_casts >= MAX_PET_CASTS and not self.pet_pending:
            self.pet_blocked_sp = pet.sp


class Patrol:
    def __init__(self, start, points=None):
        self.points = list(points) if points else [PATROL_START, PATROL_END]
        self.target = min(range(len(self.points)), key=lambda i: math.dist((start.x, start.y), self.points[i]))
        self.progress_xy = (start.x, start.y)
        self.progress_at = time.monotonic()
        self.stalls = 0

    def tick(self, lead, st, now):
        goal = self.points[self.target]
        if math.dist((st.x, st.y), self.progress_xy) > 12:
            self.progress_xy, self.progress_at = (st.x, st.y), now
        if math.dist((st.x, st.y), goal) <= ARRIVE and not st.moving:
            self.target = 1 - self.target
            self.stalls = 0
            self.progress_xy, self.progress_at = (st.x, st.y), now
            say(f'到达巡逻点 {goal}，掉头去 {self.points[self.target]}')
            return
        if st.nav_active or st.moving:
            if now - self.progress_at >= STALL:
                lead.game.cancel_navigation()
                self.stalls += 1
                self.progress_at, self.progress_xy = now, (st.x, st.y)
                say(f'巡逻寻路停滞 {STALL:.0f}s，取消后重试 {goal}（第 {self.stalls} 次）')
                if self.stalls >= 5:
                    raise t.Stop(f'巡逻到 {goal} 连续停滞 5 次')
            return
        lead.game.navigate(MAP_ID, *goal)
        self.progress_at, self.progress_xy = now, (st.x, st.y)
        say(f'巡逻寻路至 {goal}')


class Reentry:
    def __init__(self):
        self.last_log = {}
        self.shoe_retry_after = {}
        self.entrance_click = {}
        self.pickup_arrived_at = None

    def log_once(self, name, key, msg, now):
        if now - self.last_log.get((name, key), -1e9) >= 30:
            say(msg)
            self.last_log[(name, key)] = now

    def tick(self, c, now):
        """Bring an absent role back through its map-24 shoe record and prison entrance; one observed step at a time."""
        st = c.world()
        if not st or st.in_battle or st.verification:
            return
        if st.map_id == PRISON_MAP:
            return
        if st.map_id != CITY_MAP:
            if now < self.shoe_retry_after.get(c.name, 0):
                left = int(self.shoe_retry_after[c.name] - now)
                self.log_once(c.name, 'retry', f'{c.name} 飞鞋请求未到达，等待冷却约 {left // 60} 分钟', now)
                return
            rec = w.read_shoe_record(c.mem)
            why = shoe_point.why_not(c.name, rec, shoe_point.used_at(c.name), time.time(), CITY_MAP, CITY_SHOE)
            if why:
                self.log_once(c.name, 'cooldown', f'{c.name} 暂不飞鞋：{why}', now)
                return
            try:
                shoe_point.fly(CITY_MAP, CITY_SHOE, [c.name])
                say(f'{c.name} 飞鞋回内城记录点，继续前往监狱入口')
            except t.Stop as e:
                self.shoe_retry_after[c.name] = now + 3600
                say(f'{c.name} 飞鞋未能返回：{e}；停止重试，等待冷却')
            return

        if st.nav_active or st.moving:
            return
        if math.dist((st.x, st.y), ENTRANCE_XY) > 80:
            c.game.navigate(CITY_MAP, *ENTRANCE_XY)
            self.log_once(c.name, 'entrance', f'{c.name} 从飞鞋点前往惊魂监狱入口', now)
            return
        d = c.dialog()
        if not d:
            c.game.click_npc(ENTRANCE_NPC)
            self.log_once(c.name, 'click', f'{c.name} 对话 NPC {ENTRANCE_NPC} 申请回监狱', now)
            return
        hits = [(o, label) for o, label in d.options if o and ('确认' in label or '进入监狱' in label)]
        if len(hits) != 1:
            raise t.Stop(f'{c.name} 监狱入口选项不明确: {d.options}')
        c.game.select_dialog(hits[0][0])
        say(f'{c.name} 确认重新进入惊魂监狱')


def main():
    cs = {name: t.Client(name) for name in ROLES}
    lead = cs[LEADER]
    expected = {c.char_id for c in cs.values()}
    for c in cs.values():
        st = c.world()
        if not st or st.map_id != MAP_ID or st.in_battle or st.verification:
            raise t.Stop(f'{c.name} 开始前状态不符: {st}')
    if set(lead.team()) != expected or lead.team()[0] != lead.char_id:
        raise t.Stop(f'开始前不是曾经不曾带领的完整五人队: {lead.team()}')
    start = lead.world()
    say(f'五人队伍确认，地图 {MAP_ID}；巡逻 {round(start.x), round(start.y)} ↔ {PATROL_END}')
    combat = CaptainCombat(lead)
    patrol = Patrol(start)
    route_51_active = False
    reentry = Reentry()
    sold_while_home = set()
    was_battle = False
    was_missing = False
    pickup_nav = False
    talents = {n: Talent() for n in APPRENTICES}
    last_levels = None

    while True:
        now = time.monotonic()
        states = {n: c.world() for n, c in cs.items()}
        if any(s is None for s in states.values()):
            time.sleep(TICK)
            continue
        roster = set(lead.team())
        missing = [n for n, c in cs.items() if c.char_id not in roster or states[n].map_id != MAP_ID]
        captain = states[LEADER]

        if captain.in_battle:
            if not was_battle:
                combat.reset()
                say('进入战斗：队长循环天之箭，宠物循环烈焰爆发；四小号不下指令')
            was_battle = True
            if captain.nav_active or captain.moving:
                lead.game.cancel_navigation()
            combat.tick(now)
            time.sleep(TICK)
            continue
        elif was_battle:
            was_battle = False
            combat.reset()
            say('战斗结束')

        if missing:
            if not was_missing:
                was_missing = True
                if captain.nav_active or captain.moving:
                    lead.game.cancel_navigation()
                pickup_nav = False
                say(f'队伍缺员 {missing}，停止刷怪，队长回到接人点 {PICKUP}')
            if captain.map_id == MAP_ID and math.dist((captain.x, captain.y), PICKUP) > ARRIVE:
                reentry.pickup_arrived_at = None
                if not captain.nav_active and not captain.moving:
                    lead.game.navigate(MAP_ID, *PICKUP)
                    pickup_nav = True
                    say(f'队长前往接人点 {PICKUP}')
            else:
                if pickup_nav:
                    if captain.nav_active:
                        lead.game.cancel_navigation()
                    pickup_nav = False
                    say(f'队长已到接人点 {PICKUP}，等待并重组')
                if reentry.pickup_arrived_at is None:
                    reentry.pickup_arrived_at = now
                    say(f'队长已到接人点，原地稳定等待 {PICKUP_SETTLE_SECONDS:.0f} 秒')
                    time.sleep(TICK)
                    continue
                if now - reentry.pickup_arrived_at < PICKUP_SETTLE_SECONDS:
                    time.sleep(TICK)
                    continue
                # Never send living followers toward the captain; the captain approaches a stranded follower.
                for n in missing:
                    c = cs[n]
                    st = c.world()
                    if st.map_id != MAP_ID:
                        reentry.log_once(n, 'outside',
                            f'{n} 已离开监狱；队长保持停刷。按项目手册由队长单人回城接人，队友留在迷宫', now)
                        if n in APPRENTICES and st.map_id in (1, 8) and n not in sold_while_home:
                            import sell_tradable
                            say(f'{n} 已回城，按要求清理背包杂物/技能石/配方/葫芦/白装')
                            sell_tradable.main([n], 'junk-stones-white')
                            sold_while_home.add(n)
                    elif n != LEADER and captain.map_id == MAP_ID:
                        sold_while_home.discard(n)
                        if math.dist((captain.x, captain.y), (st.x, st.y)) <= INVITE_NEAR:
                            form_team(lead, [c])
                            say(f'队长走到 {n} 身边并邀请入队')
                        elif not captain.nav_active and not captain.moving:
                            lead.game.navigate(MAP_ID, round(st.x), round(st.y))
                            say(f'队长前往 {n} 的当前位置接人；队员原地不动')
            time.sleep(TICK)
            continue

        if was_missing:
            was_missing = False
            pickup_nav = False
            patrol = Patrol(captain, PATROL_AT_51 if route_51_active else None)
            say('五人重新到齐，恢复巡逻')
        if captain.map_id != MAP_ID:
            # The captain himself may have returned to town. Treat him as missing and let Reentry bring him back.
            was_missing = True
            say('队长不在监狱，暂停巡逻并使用自己的飞鞋记录返回')
            reentry.tick(lead, now)
            time.sleep(TICK)
            continue
        if roster != expected:
            time.sleep(TICK)
            continue

        levels = {n: w.read_level(cs[n].mem) for n in APPRENTICES}
        if levels != last_levels:
            say(f'等级 {levels}，惊魂监狱目标 {PRISON_TARGET_LEVEL}')
            last_levels = levels
        if not route_51_active and all(v >= 51 for v in levels.values()):
            if captain.nav_active or captain.moving:
                lead.game.cancel_navigation()
            patrol = Patrol(captain, PATROL_AT_51)
            route_51_active = True
            say(f'四个小号全部达到51级；切换巡逻点 {PATROL_AT_51[0]} ↔ {PATROL_AT_51[1]}，到53离开')
        for n in APPRENTICES:
            tm, pts = talents[n], w.read_talent_points(cs[n].mem)
            d = decide_talent(pts, tm, now)
            if d.kind == 'add':
                say(f'[{n}] {d.reason.replace("体质", TALENT_STAT)}')
                cs[n].game.add_talent(d.arg, TALENT_STAT)
                tm.sent_at, tm.before = now, pts
            elif d.kind == 'verified':
                tm.sent_at, tm.misses = None, 0
            elif d.kind == 'unconfirmed':
                say(f'[{n}] {d.reason.replace("体质", TALENT_STAT)}')
                tm.sent_at, tm.misses, tm.last_miss = None, tm.misses + 1, now

        if PRISON_TARGET_LEVEL > 0 and not captain.in_battle and \
                all(v >= PRISON_TARGET_LEVEL for v in levels.values()) and \
                all(w.read_talent_points(cs[n].mem) == 0 for n in APPRENTICES):
            if captain.nav_active or captain.moving:
                lead.game.cancel_navigation()
            say(f'四个小号全部到 {PRISON_TARGET_LEVEL} 级，停止惊魂监狱巡逻：{levels}')
            import trap_cage_53_58
            trap_cage_53_58.main()
            return
        patrol.tick(lead, captain, now)
        time.sleep(TICK)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        try:
            for name in ROLES:
                c = t.Client(name)
                if c.world().nav_active:
                    c.game.cancel_navigation()
        except Exception:
            pass
        say('收到停止指令，已取消队长寻路')
    except t.Stop as e:
        say(f'停止：{e}')
        raise SystemExit(1)
