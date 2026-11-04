"""Five-person patrol in 惊魂监狱 (264), with captain-led recovery after deaths.

Starts at the prison landing (or the captain's current point on map 264), initially patrols to (1000, 2900).
Once every apprentice reaches level 51, patrols between (1600, 500) and (1200, 700) until level 53.
Only the 方士 captain uses 天之箭 354 lv7 and pet 烈焰爆发 1504. Apprentices issue no battle commands.
If anyone leaves the prison or the five-person roster becomes incomplete, the captain stops at (2369, 2000).
Returned apprentices sell their bags; the captain leaves alone to meet them in the inner city, then leads the pickup
party back into prison. Living apprentices remain in the maze and are re-invited by the captain approaching them.
Recorded shoe cooldowns are respected: a short one is waited out, a long one (team.toml shoe_wait_max_seconds)
switches to the paid 铁男 entry; an apprentice short of the 40,000 fee first gets 60,000 from the captain.
With the configured revive item in the captain's bag, a downed apprentice is revived in battle (pet defends).
An empty captain soda bag stops the patrol out of battle with policy.SODA_EMPTY so the supervisor can restock.
Reaching level 53 returns to the caller; the supervisor then starts 陷阱囚牢.
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

import guards
import home_supply
from common import APPRENTICES
from policy import SODA_EMPTY, shoe_plan

LEADER = os.environ['SHITU_LEADER']
SHOE_WAIT_MAX = int(os.environ.get('SHITU_SHOE_WAIT_MAX', '600'))
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
PRISON_TARGET_LEVEL = int(os.environ.get('SHITU_PRISON_TARGET_LEVEL', '53'))


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
        # revive.Reviver reads/records the caster's last acted SP through .me / .pet (lunhui15.Caster layout).
        self.me, self.pet = self.player, Fight()
        self.reviver = None
        pet = w.read_fighting_pet(lead.mem)
        if pet:
            self.pet_level = pet.abilities.get(PET_MAGIC, 0)
        if not self.pet_level:
            raise t.Stop(f'队长没有出战宠物或宠物未学烈焰爆发 {PET_MAGIC}')
        # The learned-skill reader does not expose 354 on this role; level 7 was confirmed by the user.
        say(f'战斗配置：方士天之箭 {PLAYER_SKILL} lv{PLAYER_LEVEL}，宠物烈焰爆发 {PET_MAGIC} lv{self.pet_level}')
        import revive
        if revive.ITEM:
            self.reviver = revive.Reviver(lead, APPRENTICES)
            say(f'倒地复活已启用：道具 {revive.ITEM}，复活回合宠物防御')

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
        self.me, self.pet = self.player, Fight()
        if self.reviver:
            self.reviver.tick(None, self, 0.0)
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
        if self.reviver:
            pet_sent = self.pet.sent_at
            blocked = self.reviver.tick(battle, self, now)
            if self.pet.sent_at != pet_sent and battle.pet:
                # The reviver made the pet defend: that is this round's pet action; wait for it to settle.
                self.pet_memo_sp, self.pet_sent_at, self.pet_pending = battle.pet.sp, now, True
            if blocked:
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
            self.pet.record(pet.sp, now)
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
        self.pickup_arrived_at = None
        self.pickup_ready = False
        self.captain_left_prison = False

    def log_once(self, name, key, msg, now):
        if now - self.last_log.get((name, key), -1e9) >= 30:
            say(msg)
            self.last_log[(name, key)] = now

    def to_city(self, c, now, lead=None):
        """Bring a recalled character to its recorded inner-city point.

        Shoe ready: fly. Short cooldown: wait (never re-send). Missing record or a cooldown longer than
        SHOE_WAIT_MAX: the paid 铁男 entry, funded by the captain when the apprentice cannot pay 40,000."""
        st = c.world()
        if not st or st.in_battle or st.verification:
            return False
        if st.map_id == CITY_MAP:
            return True
        if st.map_id not in (1, 8):
            self.log_once(c.name, 'wait-home', f'{c.name} 当前在 map {st.map_id}，等其回到村里再接回', now)
            return False
        rec = w.read_shoe_record(c.mem)
        has_record = shoe_point.record_ok(rec, CITY_MAP, CITY_SHOE)
        left = shoe_point.cooldown_left(shoe_point.used_at(c.name), time.time())
        plan = shoe_plan(left, SHOE_WAIT_MAX, has_record)
        if plan == 'paid':
            say(f'{c.name} ' + ('没有可用的内城飞鞋记录' if not has_record else
                                f'飞鞋还要冷却 {left // 60} 分，超过 {SHOE_WAIT_MAX // 60} 分钟上限') +
                '，改走PP鸡与铁男入城兜底')
            if lead is not None and c is not lead:
                home_supply.fund_city_fee(lead, c)
            self.enter_city_by_paid_route(c)
            return c.world().map_id == CITY_MAP
        why = shoe_point.why_not(c.name, rec, shoe_point.used_at(c.name), time.time(), CITY_MAP, CITY_SHOE)
        if why:
            self.log_once(c.name, 'city-cooldown', f'{why}；角色留在城里等待，不重复请求', now)
            return False
        shoe_point.fly(CITY_MAP, CITY_SHOE, [c.name])
        t.wait(lambda: (s := c.world()) and s.map_id == CITY_MAP and
               math.dist((s.x, s.y), CITY_SHOE) <= shoe_point.ARRIVE,
               10, f'{c.name} 飞鞋到龙之都内城记录点')
        say(f'{c.name} 已到龙之都内城记录点，等队长接应')
        return True

    def enter_city_by_paid_route(self, c):
        """Recorded shoe missing: use the known PP -> 龙之都外城 -> 交叉口 -> 铁男 route.

        The fee confirmation is accepted only when the live prompt says exactly 40,000 and the character can pay.
        """
        import re
        import pp_chain
        st = c.world()
        if st.map_id not in (1, 8, 20, 25):
            raise t.Stop(f'{c.name} 不能从 map {st.map_id} 启动铁男入城兜底')
        via = ['平静海岸2区']
        if c.world().map_id not in (20, 25):
            for _ in range(8):
                st = c.world()
                if st.map_id == 20:
                    break
                pp_chain.hop(c, [c], '龙之都', via)
            else:
                if c.world().map_id != 20:
                    raise t.Stop(f'{c.name} PP鸡路线没有到龙之都外城')
        if c.world().map_id == 20:
            c.game.navigate(20, 3863, 2027)
            t.wait(lambda: (s := c.world()) and s.map_id == 20 and
                   math.dist((s.x, s.y), (3863, 2027)) <= 120 and not s.moving and
                   not s.in_battle and not s.verification,
                   240, f'{c.name} 到外城安全路点')
            c.game.navigate(20, 663, 166)
            t.wait(lambda: (s := c.world()) and s.map_id == 25,
                   180, f'{c.name} 从外城进入龙之都交叉口')
        if c.world().map_id != 25:
            if c.world().map_id == CITY_MAP:
                return
            raise t.Stop(f'{c.name} 铁男兜底前没有到交叉口：map={c.world().map_id}')
        if c.team():
            c.game.team_leave()
            t.wait(lambda: not c.team(), 5, f'{c.name} 单独办理铁男入城')
        c.game.navigate(25, 294, 171)
        t.wait(lambda: (s := c.world()) and s.map_id == 25 and
               math.dist((s.x, s.y), (294, 171)) <= 80 and not s.moving and
               not s.in_battle and not s.verification,
               180, f'{c.name} 到铁男 NPC 575')
        c.game.click_npc(575)
        d = t.wait(lambda: c.dialog(), 6, f'{c.name} 铁男入城菜单')
        labels = [(o, t.plain(label)) for o, label in d.options if o]
        free = [(o, label) for o, label in labels if '免费' in label and '内城' in label]
        paid = [(o, label) for o, label in labels if '缴费进入内城' in label]
        enter = [(o, label) for o, label in labels if label == '进入内城']
        choices = free or paid or enter
        if len(choices) != 1:
            raise t.Stop(f'{c.name} 铁男入城选项不唯一：{labels}')
        c.game.select_dialog(choices[0][0])
        t.wait(lambda: c.world().map_id == CITY_MAP or
               ((q := c.dialog()) and re.search(r'40000|40,000|4万|四万', t.plain(q.text))),
               8, f'{c.name} 入城或40,000金币确认页')
        if c.world().map_id != CITY_MAP:
            d = c.dialog()
            prompt = t.plain(d.text)
            if not re.search(r'40000|40,000|4万|四万', prompt):
                raise t.Stop(f'{c.name} 铁男费用不是已核验的40,000：{prompt}')
            gold = w.read_gold(c.mem)
            if gold < 40000:
                raise t.Stop(f'{c.name} 金币不足40,000，拒绝确认铁男入城：{gold}')
            confirm = [(o, label) for o, label in d.options
                       if o and any(x in t.plain(label) for x in ('确认', '进入', '确定'))]
            if len(confirm) != 1:
                raise t.Stop(f'{c.name} 铁男付款确认选项不唯一：{d.options}')
            say(f'{c.name} 铁男提示40,000金币；角色余额 {gold}，确认本人付费入城')
            c.game.select_dialog(confirm[0][0])
            t.wait(lambda: c.world().map_id == CITY_MAP, 12, f'{c.name} 铁男付费进入内城')
        say(f'{c.name} 铁男入城成功')

    def enter_prison_group(self, lead, group):
        """Enter prison with only the city-side rescue party; dungeon survivors stay where they are."""
        import re
        if len(group) > 1:
            form_team(lead, [c for c in group if c.name != lead.name])
        expected = {c.char_id for c in group}
        if len(group) > 1 and set(lead.team()) != expected:
            raise t.Stop(f'接人小队未组完整，拒绝进监狱：{lead.team()}，期望 {expected}')
        st = lead.world()
        if st.map_id != CITY_MAP:
            raise t.Stop(f'接人小队队长不在内城：map={st.map_id}')
        lead.game.navigate(CITY_MAP, 5660, 3258)
        t.wait(lambda: (s := lead.world()) and s.map_id == CITY_MAP and
               math.dist((s.x, s.y), (5660, 3258)) <= 80 and not s.in_battle and not s.moving,
               240, '队长到惊魂监狱入口')
        lead.game.click_npc(1339)
        d = t.wait(lambda: lead.dialog(), 6, '惊魂监狱入口确认页')
        confirm = [(o, label) for o, label in d.options if o and '确认' in t.plain(label)]
        if len(confirm) != 1:
            raise t.Stop(f'惊魂监狱确认项不唯一：{[(o, t.plain(label)) for o, label in d.options]}')
        prompt = t.plain(d.text)
        say(f'接人小队监狱入口提示：{prompt.strip()}')
        if re.search(r'回城卷', prompt) is None:
            raise t.Stop('监狱入口提示未确认回城卷要求，停止入场')
        lead.game.select_dialog(confirm[0][0])
        t.wait(lambda: all(c.world() and c.world().map_id == PRISON_MAP for c in group),
               15, '接人小队全部进入惊魂监狱')
        if len(group) > 1:
            t.wait(lambda: set(lead.team()) == expected, 5, '接人小队进监狱后名单完整')
        say(f'接人小队已进入监狱：{[c.name for c in group]}；继续由队长靠近并接回幸存队员')


def main():
    cs = {name: t.Client(name) for name in ROLES}
    lead = cs[LEADER]
    expected = {c.char_id for c in cs.values()}
    for c in cs.values():
        st = c.world()
        if not st or st.map_id != MAP_ID or st.verification:
            raise t.Stop(f'{c.name} 开始前状态不符: {st}')
    if set(lead.team()) != expected or lead.team()[0] != lead.char_id:
        raise t.Stop(f'开始前不是曾经不曾带领的完整五人队: {lead.team()}')
    start = lead.world()
    say(f'五人队伍确认，地图 {MAP_ID}；巡逻 {round(start.x), round(start.y)} ↔ {PATROL_END}')
    if start.in_battle:
        say('启动时已在战斗中；接管当前战斗并继续施法')
    guards.configure_revive()          # also when this script is started on its own
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
                reentry.pickup_ready = False
                reentry.pickup_arrived_at = None
                reentry.captain_left_prison = False
                say(f'队伍缺员 {missing}，停止刷怪，队长回到接人点 {PICKUP}')
            # First establish a safe rendezvous point. After the three-second settle, do not
            # force the captain back here between each living follower pickup.
            if captain.map_id == MAP_ID and not reentry.pickup_ready:
                if math.dist((captain.x, captain.y), PICKUP) > ARRIVE:
                    if not captain.nav_active and not captain.moving:
                        lead.game.navigate(MAP_ID, *PICKUP)
                        pickup_nav = True
                        say(f'队长前往接人点 {PICKUP}')
                else:
                    if pickup_nav and captain.nav_active:
                        lead.game.cancel_navigation()
                    pickup_nav = False
                    if reentry.pickup_arrived_at is None:
                        reentry.pickup_arrived_at = now
                        say(f'队长已到接人点，原地稳定等待 {PICKUP_SETTLE_SECONDS:.0f} 秒')
                    elif now - reentry.pickup_arrived_at >= PICKUP_SETTLE_SECONDS:
                        reentry.pickup_ready = True
                        say('接人点稳定完成；活着的迷宫队员保持原地，由队长逐个靠近')
                time.sleep(TICK)
                continue

            outside_apprentices = [n for n in APPRENTICES if states[n].map_id != MAP_ID]
            for n in outside_apprentices:
                c, st = cs[n], states[n]
                reentry.log_once(n, 'outside', f'{n} 已离开监狱；其余活队员留在迷宫原地', now)
                if st.map_id in (1, 8) and not st.in_battle and n not in sold_while_home:
                    import sell_tradable
                    say(f'{n} 已回城，按要求清理背包杂物/技能石/配方/葫芦/白装')
                    sell_tradable.main([n], 'junk-stones-white')
                    sold_while_home.add(n)
            for n in APPRENTICES:
                if states[n].map_id == MAP_ID:
                    sold_while_home.discard(n)

            if outside_apprentices and captain.map_id == MAP_ID:
                # The leader alone goes home to collect the recalled apprentice(s). The other
                # living party members remain in the prison maze and do not walk toward him.
                if not reentry.captain_left_prison:
                    if lead.team():
                        lead.game.team_leave()
                        t.wait(lambda: not lead.team(), 5, '队长单独回城前离开监狱队伍')
                    from quanshou import scroll
                    say('队长单人回城接人；活着的队员留在监狱')
                    scroll(lead)
                    reentry.captain_left_prison = True
                time.sleep(TICK)
                continue

            if captain.map_id != MAP_ID:
                if outside_apprentices:
                    # Return only the absent apprentices and captain to the recorded inner-city point.
                    # Each apprentice is sold once while home; an unavailable shoe is never spammed.
                    for n in outside_apprentices:
                        reentry.to_city(cs[n], now, lead)
                    if all(cs[n].world().map_id == CITY_MAP for n in outside_apprentices):
                        reentry.to_city(lead, now)
                        if lead.world().map_id == CITY_MAP:
                            group = [lead] + [cs[n] for n in outside_apprentices]
                            form_team(lead, group[1:])
                            reentry.enter_prison_group(lead, group)
                            reentry.pickup_ready = False
                            reentry.pickup_arrived_at = None
                            reentry.captain_left_prison = False
                            pickup_nav = False
                else:
                    # Captain died/returned alone: the followers are safe in the maze. Bring
                    # him back through his city record, re-enter prison, then approach them.
                    if reentry.to_city(lead, now):
                        reentry.enter_prison_group(lead, [lead])
                        reentry.pickup_ready = False
                        reentry.pickup_arrived_at = None
                        reentry.captain_left_prison = False
                        pickup_nav = False
                time.sleep(TICK)
                continue

            # Remaining missing roles are alive in the prison but not in the captain's party.
            # Move the captain to each one and invite from nearby; do not make the fragile alt walk.
            ungrouped = [n for n in missing if n != LEADER and states[n].map_id == MAP_ID]
            if ungrouped:
                n = min(ungrouped, key=lambda name: math.dist((captain.x, captain.y),
                                                               (states[name].x, states[name].y)))
                c, st = cs[n], states[n]
                if math.dist((captain.x, captain.y), (st.x, st.y)) <= INVITE_NEAR:
                    form_team(lead, [c])
                    say(f'队长已靠近 {n} 并发起组队')
                elif not captain.nav_active and not captain.moving:
                    lead.game.navigate(MAP_ID, round(st.x), round(st.y))
                    say(f'队长前往 {n} 的当前位置接人；队员原地不动')
            time.sleep(TICK)
            continue

        if was_missing:
            was_missing = False
            pickup_nav = False
            reentry.pickup_ready = False
            reentry.pickup_arrived_at = None
            reentry.captain_left_prison = False
            patrol = Patrol(captain, PATROL_AT_51 if route_51_active else None)
            say('五人重新到齐，恢复巡逻')
        if roster != expected:
            time.sleep(TICK)
            continue
        if captain.verification:
            time.sleep(TICK)
            continue
        if guards.count(lead, guards.SODA_ID) == 0:
            if captain.nav_active or captain.moving:
                lead.game.cancel_navigation()
            raise t.Stop(f'{SODA_EMPTY}，五人都在监狱，停止巡逻交给监督程序全队回城补给')

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
            say(f'四个小号全部到 {PRISON_TARGET_LEVEL} 级，停止惊魂监狱巡逻：{levels}；下一段由监督程序启动')
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
