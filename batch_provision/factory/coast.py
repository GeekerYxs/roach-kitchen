"""Stage 7: the two coast leaders each take up to 4 alts (phase queue_coast, quest 78 active) on 平静海岸2区
(map 81), farm 小强的大腿 10571 at A and 鸡屁股 10572 at B, then bring the team back and disband it.

Entry: python -m factory.coast [factory.toml]
Every station registered with role 'coast' (一键登录工位.cmd) runs one batch, all leaders in parallel. Per leader:
  1. back to the coast, chosen from the map it is on (user-agreed 2026-10-12):
       map 81 -> nothing;  map 1 -> PP鸡 (stage 5 calls, 190 gold);  other map -> 飞鞋 (only if its point is on
       map 81; the server ignores a return within the hour, then the map does not change) -> 回城卷 -> PP鸡
  2. standing at the PP鸡 landing (1152,932) with a 飞鞋 point that is not there: record it there (once)
  3. walk to the rendezvous (1750,1300). Members already in its team are kept (restart: a team is fixed for the
     whole batch, no refill). Otherwise claim queue_coast alts on map 81, oldest first, up to 4, one at a time
     (the other leader claims from the same queue); far ones walk over (escaping battles), then invite -> accept
  4. farm: someone has legs < 10 -> patrol the legs pair; else someone has rumps < 20 -> the rumps pair; else
     done. The leader casts 扫射 803, its pet 烈焰爆发 1504 (stage 4b); members only spend talent on 体质
  5. walk back to the rendezvous, wait for the members, the leader leaves the team; a member still in a team
     after 5 s leaves itself. Members are then phase handin (stage 8)
A member that leaves the team (died -> village, dropped) is released and queued again by its phase.
Decisions are pure (tests/test_factory_coast.py).
"""
import json
import math
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from provisioner import log, native, procs
from provisioner.game import FIGHT_ATTACK, FIGHT_ESCAPE, Game, NotSent
from provisioner.memory import ProcessMemory
from provisioner.world import (item_count, read_bag, read_battle, read_fighting_pet, read_invite_byte, read_level,
                               read_shoe_record, read_skill_level, read_talent_points, read_team, read_world)

from . import db
from .config import ROOT, load_settings
from .observe import observe
from .phase import (COAST, COAST_MAP, LEGS_ITEM, LEGS_NEEDED, QUEUE_COAST, RUMPS_ITEM, RUMPS_NEEDED, VILLAGE_MAP,
                    derive_phase)
from .runner import ROLE_NAME
from .transport import Trip, behind, decide_trip
from .welltrain import Fight, Talent, decide_battle, decide_talent, scroll_slot
from .wellteam import ACTION_INVITE, INVITE_GAP, INVITE_RANGE, Join, decide_member

LANDING = (1152, 932)           # PP鸡 lands the team here (stage 5, live) = the leaders' 飞鞋 point
LANDING_RANGE = 80
RENDEZVOUS = (1750, 1300)       # coast teams form and disband here (next to 海子 (1830,1377))
ARRIVE = 30                     # this close to a point counts as there
NEAR_LEADER = 200               # a member this close to the leader can be invited (server limit ~300)
NAV_RETRY = 2.0
STALL = 6.0
SETTLE = 0.5
RECORD_SETTLE = 1.5             # stand this long before recording 飞鞋 (the server records its own position)
RECORD_WAIT = 3.0
RECORD_TOLERANCE = 3
RECORD_TRIES = 2
RETURN_WAIT = 6.0               # map must change this long after 飞鞋 / 回城卷
ESCAPE_FALLBACK = 6.0
FOLLOW_WAIT = 15.0              # back at the rendezvous: wait this long for members still walking
LEAVE_WAIT = 5.0
DROP_AFTER = 3.0
OBSERVE_EVERY = 10.0
ACTION_RECORD = 'coast_shoe_record'


@dataclass(frozen=True)
class Decision:
    kind: str
    reason: str
    arg: object = None


def _dist(w, point):
    return math.dist((w.x, w.y), point)


# ---- leader back to the coast -----------------------------------------------------------------------------

@dataclass
class Away:
    """The leader on a map other than 1 / 81: which return was sent and which were tried."""
    method: str | None = None
    sent_at: float | None = None
    tried: set = field(default_factory=set)


def decide_away(w, shoe_on_coast, scroll, memo, now):
    """Leader neither on the coast nor in the village. 'wait' | 'cancel_nav' | 'shoe' | 'scroll' | 'unconfirmed' |
    'fail'. shoe_on_coast: its 飞鞋 point is on map 81; scroll: bag slot of a 回城卷 or None."""
    if w is None:
        return Decision('wait', '队长加载中')
    name = {'shoe': '飞鞋', 'scroll': '回城卷'}.get(memo.method)
    if memo.sent_at is not None:
        if now - memo.sent_at < RETURN_WAIT:
            return Decision('wait', f'等{name}生效')
        return Decision('unconfirmed', f'{name} {RETURN_WAIT:.0f}s 后仍在地图 {w.map_id}')
    if w.verification:
        return Decision('wait', '队长验证码弹窗，等待答题')
    if w.in_battle or w.busy:
        return Decision('wait', '队长忙/战斗中')
    if w.nav_active:
        return Decision('cancel_nav', '停止寻路')
    if shoe_on_coast and 'shoe' not in memo.tried:
        return Decision('shoe', f'在地图 {w.map_id}，用飞鞋回平静海岸2区')
    if scroll is not None and 'scroll' not in memo.tried:
        return Decision('scroll', f'在地图 {w.map_id}，用回城卷回逍遥村（背包第 {scroll} 格）', scroll)
    return Decision('fail', f'在地图 {w.map_id}，飞鞋和回城卷都没能离开（试过 {sorted(memo.tried)}）')


# ---- 飞鞋 point at the landing ----------------------------------------------------------------------------

@dataclass
class Record:
    sent_at: float | None = None
    tries: int = 0


def decide_record(w, record, memo, now, point=LANDING, near=LANDING_RANGE):
    """'done' | 'skip' (not at the point: record another time) | 'wait' | 'record' | 'verified' | 'unconfirmed' |
    'give_up' (not fatal: the 回城卷 + PP鸡 path still works). point: where the 飞鞋 point belongs on map 81."""
    if w is None or record is None:
        return Decision('wait', '加载中')
    if record[0] == COAST_MAP and math.dist(record[1:], point) <= near:
        if memo.sent_at is not None:
            return Decision('verified', f'飞鞋记录点 = 地图{record[0]} ({record[1]},{record[2]})')
        return Decision('done', f'飞鞋记录点已在 ({record[1]},{record[2]})')
    if memo.sent_at is not None:
        if now - memo.sent_at < RECORD_WAIT:
            return Decision('wait', '等飞鞋记录点更新')
        return Decision('unconfirmed', f'{RECORD_WAIT:.0f}s 内飞鞋记录点没变（读到 {record}）')
    if memo.tries >= RECORD_TRIES:
        return Decision('give_up', f'记录飞鞋 {memo.tries} 次都没成功，先不记（回城卷 + PP 鸡照样能回来）')
    if w.map_id != COAST_MAP or _dist(w, point) > near:
        return Decision('skip', f'不在 {point}，这次不记录飞鞋（记录点 {record}）')
    if w.verification or w.in_battle or w.busy or w.nav_active or w.moving:
        return Decision('wait', '忙/移动中，站稳后记录飞鞋')
    if w.still_for < RECORD_SETTLE:
        return Decision('wait', '站稳后记录飞鞋')
    return Decision('record', f'在 ({w.x:.0f},{w.y:.0f}) 记录飞鞋，原记录点 {record}')


# ---- leader walking on the coast ----------------------------------------------------------------------------

@dataclass
class Walk:
    last_nav: float = -1e9
    progress_xy: tuple | None = None
    progress_at: float = 0.0
    patrol: int = 0              # index of the patrol point we are walking to
    spot: str | None = None

    def observe(self, w, now):
        if w and (self.progress_xy is None or _dist(w, self.progress_xy) > 15):
            self.progress_xy, self.progress_at = (w.x, w.y), now

    def record(self, d, w, now):
        if d.kind == 'navigate':
            self.last_nav, self.progress_xy, self.progress_at = now, (w.x, w.y), now
            if d.arg[3] is not None:
                self.patrol = d.arg[3]
        elif d.kind == 'cancel_nav':
            self.last_nav = -1e9


def _ready(w, who='队长'):
    if w is None:
        return Decision('wait', f'{who}加载中')
    if w.in_battle:
        return Decision('battle', '战斗中')
    if w.verification:
        return Decision('wait', f'{who}验证码弹窗，等待答题')
    if w.busy:
        return Decision('wait', f'{who}忙 flags={w.flags:#x}')
    if w.map_id != COAST_MAP:
        return Decision('lost', f'{who}不在平静海岸2区（地图 {w.map_id}）')
    return None


def _walk(w, target, memo, now, why, patrol=None):
    if w.nav_active or w.moving:
        if now - memo.progress_at > STALL:
            return Decision('cancel_nav', f'{STALL:.0f}s 没有移动，重新寻路')
        return Decision('wait', f'寻路中：{why}')
    if now - memo.last_nav < NAV_RETRY:
        return Decision('wait', f'等寻路开始：{why}')
    return Decision('navigate', f'寻路{why}（距离 {_dist(w, target):.0f}）', (COAST_MAP, *target, patrol))


def decide_goto(w, target, memo, now, why):
    """Leader to a point on map 81, fighting on the way. 'arrived' | 'battle' | 'lost' | 'wait' | 'navigate' |
    'cancel_nav'."""
    d = _ready(w)
    if d:
        return d
    if _dist(w, target) > ARRIVE:
        return _walk(w, target, memo, now, why)
    if w.nav_active:
        return Decision('cancel_nav', f'已到（{why}），停止寻路')
    if w.moving or w.still_for < SETTLE:
        return Decision('wait', f'站稳（{why}）')
    return Decision('arrived', f'已到（{why}）')


def choose_spot(counts):
    """counts: [(legs, rumps)] of the members still in the batch -> 'legs' | 'rumps' | 'done'."""
    if any(legs < LEGS_NEEDED for legs, _ in counts):
        return 'legs'
    if any(rumps < RUMPS_NEEDED for _, rumps in counts):
        return 'rumps'
    return 'done'


def decide_farm(w, points, memo, now):
    """Patrol between the two points of the current spot. 'battle' | 'lost' | 'wait' | 'navigate' | 'cancel_nav'."""
    d = _ready(w)
    if d:
        return d
    label = '刷腿' if memo.spot == 'legs' else '刷鸡屁股'
    target = points[memo.patrol]
    if _dist(w, target) <= ARRIVE:
        nxt = 1 - memo.patrol
        return Decision('navigate', f'{label}：到第 {memo.patrol + 1} 点，去第 {nxt + 1} 点', (COAST_MAP, *points[nxt], nxt))
    return _walk(w, target, memo, now, f'{label}：去第 {memo.patrol + 1} 点 {target}', memo.patrol)


# ---- members coming to the leader --------------------------------------------------------------------------

@dataclass
class Approach:
    last_sp: int | None = None
    last_escape: float = -1e9
    last_nav: float = -1e9
    progress_xy: tuple | None = None
    progress_at: float = 0.0

    def observe(self, w, now):
        if w and (self.progress_xy is None or _dist(w, self.progress_xy) > 15):
            self.progress_xy, self.progress_at = (w.x, w.y), now

    def record(self, d, w, now):
        if d.kind == 'escape':
            self.last_sp, self.last_escape = w.my_sp, now
        elif d.kind == 'navigate':
            self.last_nav, self.progress_xy, self.progress_at = now, (w.x, w.y), now
        elif d.kind == 'cancel_nav':
            self.last_nav = -1e9


def decide_approach(w, leader_w, memo, now):
    """A claimed member not yet in the team walks next to the leader alone (escaping battles like stage 6).
    'near' | 'wait' | 'escape' | 'navigate' | 'cancel_nav' | 'fail'."""
    if w is None or leader_w is None:
        return Decision('wait', '加载中')
    if w.map_id != COAST_MAP:
        return Decision('fail', f'不在平静海岸2区（地图 {w.map_id}）')
    if w.verification:
        return Decision('wait', '验证码弹窗，等待答题')
    if w.in_battle:
        if w.my_sp is None:
            return Decision('wait', '战斗中，读不到自己的蓄力点')
        if w.my_sp != memo.last_sp:
            return Decision('escape', f'战斗中蓄力点 {memo.last_sp} -> {w.my_sp}，发送逃跑')
        if now - memo.last_escape >= ESCAPE_FALLBACK:
            return Decision('escape', f'蓄力点 {w.my_sp} 已 {ESCAPE_FALLBACK:.0f}s 未变，补发逃跑')
        return Decision('wait', '战斗中，等蓄力点变化')
    if w.busy:
        return Decision('wait', f'忙 flags={w.flags:#x}')
    distance = math.dist((w.x, w.y), (leader_w.x, leader_w.y))
    if distance <= NEAR_LEADER:
        if w.nav_active:
            return Decision('cancel_nav', f'已到队长旁边（{distance:.0f}），停止寻路')
        if w.moving:
            return Decision('wait', '站稳')
        return Decision('near', f'在队长旁边（{distance:.0f}）')
    if w.nav_active or w.moving:
        if now - memo.progress_at > STALL:
            return Decision('cancel_nav', f'{STALL:.0f}s 没有移动，重新寻路')
        return Decision('wait', f'走向集合点（离队长 {distance:.0f}）')
    if now - memo.last_nav < NAV_RETRY:
        return Decision('wait', '等寻路开始')
    return Decision('navigate', f'离队长 {distance:.0f}，寻路去集合点', (COAST_MAP, *RENDEZVOUS))


# ---- disbanding ----------------------------------------------------------------------------------------------

def decide_disband(leader_in_team, members_in_team, leader_left_at, members_left_at, now):
    """Back at the rendezvous. 'done' | 'wait' | 'leader_leave' | 'members_leave' | 'fail'."""
    if not leader_in_team and not members_in_team:
        return Decision('done', '队伍已解散')
    if leader_left_at is None:
        if leader_in_team:
            return Decision('leader_leave', '队长退队解散队伍')
        leader_left_at = -1e9
    if now - leader_left_at < LEAVE_WAIT:
        return Decision('wait', f'队长已退队，等名单更新（还有 {members_in_team} 个队员在队里）')
    if members_left_at is None:
        return Decision('members_leave', f'队长退队 {LEAVE_WAIT:.0f}s 后还有 {members_in_team} 个队员在队里，各自退队')
    if now - members_left_at < LEAVE_WAIT:
        return Decision('wait', '队员已退队，等名单更新')
    return Decision('fail', f'退队后还有 {members_in_team} 个队员在队里' + ('，队长也还在队里' if leader_in_team else ''))


# ---- the run ---------------------------------------------------------------------------------------------------

class Member:
    def __init__(self, client, account, slot, mem):
        self.c, self.account, self.slot, self.mem = client, account, slot, mem
        self.game = Game(client.session, mem)
        self.join, self.approach, self.talent = Join(), Approach(), Talent()
        self.state = 'joining'          # joining -> farming -> done | dropped
        self.missing_since = None
        self.left_at = None
        self.error = None
        self.reasons = {}
        self.log = log.for_account(client.name)

    def say(self, topic, d):
        if self.reasons.get(topic) != d.reason:
            self.log.info('%s', d.reason)
        self.reasons[topic] = d.reason


class CoastRun:
    shoe_point = (LANDING, LANDING_RANGE)      # where this station keeps its 飞鞋 point (and how close counts)

    def __init__(self, conn, station, leader, leader_mem, alts, settings, logger):
        self.conn, self.station, self.leader, self.lmem = conn, station, leader, leader_mem
        self.alts, self.s, self.log = alts, settings, logger     # alts: {char_id: (client, account, slot)}
        self.lgame = Game(leader.session, leader_mem)
        self.members, self.mems = {}, []
        self.walk, self.me_fight, self.pet_fight = Walk(), Fight(), Fight()
        self.in_battle, self.battles, self.casts = False, 0, {'cast': 0, 'attack': 0}
        self.skill_level = self.pet_level = 0
        self.last_reason = None
        self.last_observe = -1e9
        self.started = time.monotonic()

    def close(self):
        for m in self.members.values():
            m.game.close()
        self.lgame.close()
        for mem in self.mems:
            mem.close()

    def say(self, d):
        if d.reason != self.last_reason:
            self.log.info('%s', d.reason)
        self.last_reason = d.reason

    def sid(self):
        return self.station['station_id']

    def active(self):
        return [m for m in self.members.values() if m.state != 'dropped']

    def drop(self, m, error):
        m.state, m.error = 'dropped', error
        m.log.error('移出本批: %s', error)
        db.release(self.conn, self.sid(), [m.c.char_id], time.time())

    def check(self):
        if time.monotonic() - self.started > self.s.coast_farm_timeout:
            raise RuntimeError(f'{self.s.coast_farm_timeout:.0f}s 内没有完成')
        if not native.alive(self.leader.session.pid):
            raise RuntimeError(f'队长游戏进程 {self.leader.session.pid} 已退出')
        for m in self.active():
            if not native.alive(m.c.session.pid):
                self.drop(m, '游戏进程已退出')
        lw = read_world(self.lmem)
        if lw and lw.char_id != self.leader.char_id:
            raise RuntimeError('队长角色变了')
        return lw

    def periodic(self, now, status):
        if now - self.last_observe < OBSERVE_EVERY:
            return
        self.last_observe = now
        wall = time.time()
        db.renew(self.conn, self.sid(), self.s.coast_lease, wall)
        db.heartbeat(self.conn, self.sid(), COAST, self.leader.char_id, status, wall)
        roles = db.station_roles(self.conn)
        for m in self.active():
            obs = observe(m.mem, read_world(m.mem))
            if obs is not None:
                db.save_observation(self.conn, obs, derive_phase(obs, db.ledger(self.conn, m.c.char_id), roles), wall)

    # ---- 1: back to the coast
    def to_coast(self):
        trip, away, last_map = Trip(), Away(), None
        while True:
            w = self.check()
            now = time.monotonic()
            self.periodic(now, 'returning')
            if w is None:
                time.sleep(self.s.tick)
                continue
            if w.map_id != last_map:
                if last_map is not None:
                    self.log.info('队长到了地图 %d (%.0f,%.0f)', w.map_id, w.x, w.y)
                trip, last_map = Trip(), w.map_id
                if away.sent_at is not None and away.method:
                    away = Away(tried=away.tried)
            if w.map_id == COAST_MAP:
                return w
            if w.map_id == VILLAGE_MAP:
                trip.observe(w, now)
                d = decide_trip(w, [], trip, now)
                self.say(Decision(d.kind, d.reason.replace('调度员', '队长')))
                if d.kind == 'fail':
                    raise RuntimeError(d.reason.replace('调度员', '队长'))
                if d.kind == 'navigate':
                    self.lgame.navigate(*d.arg)
                elif d.kind == 'cancel_nav':
                    self.lgame.cancel_navigation()
                elif d.kind == 'click':
                    self.lgame.click_npc(d.arg)
                elif d.kind in ('select', 'destination'):
                    if d.kind == 'destination':
                        db.log_event(self.conn, time.time(), 'teleport', f'海岸队长 {d.reason}', station_id=self.sid())
                    self.lgame.select_dialog(d.arg)
                if d.kind not in ('wait', 'arrived'):
                    trip.record(d, w, now)
            else:
                record = read_shoe_record(self.lmem)
                d = decide_away(w, bool(record and record[0] == COAST_MAP), scroll_slot(read_bag(self.lmem)),
                                away, now)
                self.say(d)
                if d.kind == 'fail':
                    raise RuntimeError(d.reason)
                if d.kind == 'unconfirmed':
                    away.tried.add(away.method)
                    away.method = away.sent_at = None
                elif d.kind == 'cancel_nav':
                    self.lgame.cancel_navigation()
                elif d.kind in ('shoe', 'scroll'):
                    try:
                        self.lgame.shoe_return() if d.kind == 'shoe' else self.lgame.use_item(d.arg)
                    except NotSent as e:
                        self.log.warning('请求没发出: %s', e)
                        away.tried.add(d.kind)
                    else:
                        away.method, away.sent_at = d.kind, now
            time.sleep(self.s.tick)

    # ---- 2: 飞鞋 point
    def record_shoe(self):
        memo, deadline = Record(), time.monotonic() + 20
        while time.monotonic() < deadline:
            w = self.check()
            now = time.monotonic()
            d = decide_record(w, read_shoe_record(self.lmem), memo, now, *self.shoe_point)
            if d.kind != 'wait' or d.reason != self.last_reason:
                self.say(d)
            if d.kind in ('done', 'skip', 'verified', 'give_up'):
                if d.kind == 'verified':
                    db.log_event(self.conn, time.time(), 'coast_shoe', d.reason, station_id=self.sid())
                return
            if d.kind == 'unconfirmed':
                memo.sent_at = None
            elif d.kind == 'record':
                try:
                    self.lgame.shoe_record()
                except NotSent as e:
                    self.log.warning('记录飞鞋请求没发出: %s', e)
                    memo.tries += 1
                else:
                    memo.sent_at, memo.tries = now, memo.tries + 1
            time.sleep(self.s.tick)
        self.log.warning('20s 内没记录好飞鞋，先不记')

    # ---- leader walking + fighting
    def step_battle(self, now):
        battle = read_battle(self.lmem)
        if not self.in_battle:
            self.in_battle, self.battles = True, self.battles + 1
            self.me_fight, self.pet_fight = Fight(), Fight()
            self.log.info('进入战斗（第 %d 场）', self.battles)
        pet = read_fighting_pet(self.lmem)
        pet_ok = bool(self.pet_level) and pet is not None and pet.mp >= self.s.pet_mp_min
        for who, d in decide_battle(battle, self.me_fight, self.pet_fight, now, bool(self.skill_level), pet_ok):
            if d.kind == 'none':
                continue
            is_pet = who == 'pet'
            if d.kind == 'cast' and is_pet:
                self.lgame.cast_pet_magic(d.arg, self.s.pet_magic, self.pet_level)
                what = f'烈焰爆发 {self.s.pet_magic} lv{self.pet_level}（魔力 {pet.mp}）'
            elif d.kind == 'cast':
                self.lgame.cast_skill(d.arg, self.s.leader_skill, self.skill_level)
                what = f'扫射 {self.s.leader_skill} lv{self.skill_level}'
            else:
                self.lgame.fight_command(FIGHT_ATTACK, is_pet=is_pet, target=d.arg)
                what = '普通攻击'
            self.casts[d.kind] += 1
            self.log.debug('%s → %s，目标位置 %d', d.reason, what, d.arg)
            f = battle.pet if is_pet else battle.me
            (self.pet_fight if is_pet else self.me_fight).record(f.sp, now)

    def leave_battle(self, now):
        if self.in_battle:
            self.in_battle = False
            self.walk.last_nav = -1e9           # a battle interrupts navigation; allow re-issue at once
            self.walk.progress_at = now
            counts = ', '.join(f'{m.c.name} 腿{c[0]} 屁股{c[1]}' for m, c in self.counts())
            self.log.info('战斗结束（第 %d 场）。%s', self.battles, counts)

    def act(self, d, w, now):
        """Run a walking decision. Returns d.kind for the caller."""
        if d.kind == 'battle':
            self.step_battle(now)
            return d.kind
        self.leave_battle(now)
        self.say(d)
        if d.kind == 'navigate':
            self.lgame.navigate(*d.arg[:3])
        elif d.kind == 'cancel_nav':
            self.lgame.cancel_navigation()
        if d.kind in ('navigate', 'cancel_nav'):
            self.walk.record(d, w, now)
        return d.kind

    def goto(self, target, why, status):
        """Walk the leader (fighting on the way) until it stands at target; recover if it left the coast."""
        while True:
            w = self.check()
            now = time.monotonic()
            self.periodic(now, status)
            self.walk.observe(w, now)
            d = decide_goto(w, target, self.walk, now, why)
            if d.kind == 'lost':
                self.say(d)
                self.to_coast()
                continue
            if self.act(d, w, now) == 'arrived':
                return w
            time.sleep(self.s.tick)

    # ---- 3: team
    def adopt(self):
        team = read_team(self.lmem)
        if team is None:
            raise RuntimeError('读不到队长的队伍')
        if team.members and team.leader != self.leader.char_id:
            raise RuntimeError(f'队长在别人的队里（队长 {team.leader}），请手动退队')
        strangers = [cid for cid in team.members[1:] if cid not in self.alts]
        if strangers:
            raise RuntimeError(f'队里有不认识的角色 {strangers}（不是本工具窗口里的平静海岸2区小号），请手动处理')
        got = self.claim_list(list(team.members[1:]))
        for cid in got:
            self.add_member(cid).state = 'farming'
        return got

    def add_member(self, cid):
        c, account, slot = self.alts[cid]
        mem = ProcessMemory(c.session.pid, c.session.base)
        self.mems.append(mem)
        m = self.members[cid] = Member(c, account, slot, mem)
        return m

    def claim_list(self, cids):
        got = db.claim(self.conn, self.sid(), cids, self.s.coast_lease, time.time()) if cids else []
        for cid in set(cids) - set(got):
            self.log.warning('%s 被别的工位占着或已隔离，本批不管它', self.alts[cid][0].name)
        return [cid for cid in cids if cid in got]

    def choose(self):
        """Refresh every coast alt's phase, then claim queue_coast alts one by one (the other leader claims from the
        same queue at the same time)."""
        roles, now = db.station_roles(self.conn), time.time()
        for cid, (c, account, slot) in self.alts.items():
            db.register_alt(self.conn, cid, account, slot, c.name, now)
            try:
                with ProcessMemory(c.session.pid, c.session.base) as mem:
                    obs = observe(mem, read_world(mem))
            except OSError:
                obs = None      # the window closed meanwhile (live 2026-10-13 04:19: WinError 87 stopped the well leader)
            if obs is None:
                continue
            plan = derive_phase(obs, db.ledger(self.conn, cid), roles)
            db.save_observation(self.conn, obs, plan, now)
        got = []
        for row in db.waiting(self.conn, QUEUE_COAST, time.time()):
            if len(got) >= self.s.coast_team_size:
                break
            if row['char_id'] in self.alts and db.claim(self.conn, self.sid(), [row['char_id']], self.s.coast_lease,
                                                        time.time()):
                got.append(row['char_id'])
        return got

    def form(self):
        level, invite_byte = read_level(self.lmem), read_invite_byte(self.lmem)
        deadline, last_invite = time.monotonic() + self.s.coast_form_timeout, 0.0
        while any(m.state == 'joining' for m in self.active()):
            lw = self.check()
            now = time.monotonic()
            if now > deadline:
                for m in self.active():
                    if m.state == 'joining':
                        self.drop(m, f'{self.s.coast_form_timeout:.0f}s 内没有入队')
                break
            self.periodic(now, 'forming')
            if lw is None:
                time.sleep(self.s.tick)
                continue
            if lw.in_battle:                     # someone walked into the leader? fight it, then go on
                self.step_battle(now)
                time.sleep(self.s.tick)
                continue
            self.leave_battle(now)
            lteam = read_team(self.lmem)
            for m in self.active():
                if m.state != 'joining':
                    continue
                w, team = read_world(m.mem), read_team(m.mem)
                if w and w.char_id != m.c.char_id:
                    raise RuntimeError(f'{m.c.name} 角色变了')
                in_team = bool(team and lteam and team.leader == self.leader.char_id
                               and m.c.char_id in lteam.members)
                if not in_team and m.join.invited_at is None and m.join.accepted_at is None:
                    m.approach.observe(w, now)
                    a = decide_approach(w, lw, m.approach, now)
                    if a.kind != 'near':
                        m.say('join', a)
                        if a.kind == 'fail':
                            self.drop(m, a.reason)
                        elif a.kind == 'escape':
                            m.game.fight_command(FIGHT_ESCAPE)
                        elif a.kind == 'navigate':
                            m.game.navigate(*a.arg)
                        elif a.kind == 'cancel_nav':
                            m.game.cancel_navigation()
                        if a.kind in ('escape', 'navigate', 'cancel_nav'):
                            m.approach.record(a, w, now)
                        continue
                d = decide_member(m.c.char_id, w, team, self.leader.char_id, lw, lteam, m.join, now,
                                  map_id=COAST_MAP, map_name='平静海岸2区')
                m.say('join', d)
                if d.kind == 'joined':
                    m.state = 'farming'
                    if db.alt(self.conn, m.c.char_id)['pending_action'] == ACTION_INVITE:
                        db.complete_action(self.conn, m.c.char_id, time.time())
                elif d.kind == 'fail':
                    self.drop(m, d.reason)
                elif d.kind == 'unconfirmed':
                    m.join = Join()
                    if db.record_failure(self.conn, m.c.char_id, d.reason, time.time()):
                        self.drop(m, f'连续失败 {db.MAX_RETRIES} 次，已隔离: {d.reason}')
                elif d.kind == 'invite' and now - last_invite >= INVITE_GAP:
                    db.mark_pending(self.conn, m.c.char_id, ACTION_INVITE, time.time())
                    try:
                        self.lgame.team_invite(m.c.char_id, level, invite_byte, self.leader.name)
                    except NotSent as e:
                        db.clear_pending(self.conn, m.c.char_id, time.time(), str(e))
                        raise RuntimeError(f'队长的邀请没发出: {e}') from e
                    m.join.invited_at = last_invite = time.monotonic()
                elif d.kind == 'accept':
                    try:
                        m.game.team_accept()
                    except NotSent as e:
                        self.drop(m, f'接受邀请没发出: {e}')
                        continue
                    m.join.accepted_at = time.monotonic()
            time.sleep(self.s.tick)

    # ---- 4: farming
    def counts(self):
        out = []
        for m in self.active():
            bag = read_bag(m.mem)
            if bag is not None:
                out.append((m, (item_count(bag, LEGS_ITEM), item_count(bag, RUMPS_ITEM))))
        return out

    def check_roster(self, now):
        lteam = read_team(self.lmem)
        roster = set(lteam.members) if lteam else set()
        for m in self.active():
            if m.c.char_id in roster:
                m.missing_since = None
            elif m.missing_since is None:
                m.missing_since = now
            elif now - m.missing_since >= DROP_AFTER:
                w = read_world(m.mem)
                self.drop(m, f'已不在队长的队里（地图 {w.map_id if w else "?"}），回到队列')

    def step_talent(self, m, now):
        points = read_talent_points(m.mem)
        d = decide_talent(points, m.talent, now)
        if d.kind not in ('wait', 'none'):
            m.say('talent', d)
        if d.kind == 'verified':
            m.talent = Talent()
        elif d.kind == 'unconfirmed':
            m.talent = Talent(misses=m.talent.misses + 1, last_miss=now)
        elif d.kind == 'add':
            try:
                m.game.add_constitution(d.arg)
            except NotSent as e:
                m.log.warning('加点请求没发出: %s', e)
                m.talent = Talent(misses=m.talent.misses + 1, last_miss=now)
                return
            m.talent = Talent(sent_at=now, before=points, misses=m.talent.misses)

    def farm(self):
        patrols = {'legs': self.s.coast_legs_patrol, 'rumps': self.s.coast_rumps_patrol}
        while True:
            w = self.check()
            now = time.monotonic()
            self.periodic(now, 'farming')
            self.check_roster(now)
            for m in self.active():
                self.step_talent(m, now)
            counts = self.counts()
            spot = choose_spot([c for _, c in counts]) if counts else 'done'
            if spot == 'done' and not (w and w.in_battle):
                self.leave_battle(now)
                self.log.info('本批材料齐了（%s），回集合点', ', '.join(f'{m.c.name} 腿{c[0]} 屁股{c[1]}'
                                                                for m, c in counts) or '队里没有小号了')
                return
            if spot != 'done' and spot != self.walk.spot:
                self.log.info('开始%s: %s', '刷腿' if spot == 'legs' else '刷鸡屁股', patrols[spot])
                self.walk.spot, self.walk.patrol, self.walk.last_nav = spot, 0, -1e9
            self.walk.observe(w, now)
            d = decide_farm(w, patrols[self.walk.spot], self.walk, now) if self.walk.spot else _ready(w)
            if d is None:
                time.sleep(self.s.tick)
                continue
            if d.kind == 'lost':
                self.say(d)
                self.to_coast()
                continue
            self.act(d, w, now)
            time.sleep(self.s.tick)

    # ---- 5: back and disband
    def disband(self):
        arrived_at = time.monotonic()
        while True:                              # wait for members still walking behind
            w = self.check()
            now = time.monotonic()
            late = behind(w, [read_world(m.mem) for m in self.active()]) if w else 0
            if not late or now - arrived_at >= FOLLOW_WAIT:
                break
            self.say(Decision('wait', f'等 {late} 个队员走到集合点'))
            time.sleep(self.s.tick)
        leader_left_at = members_left_at = None
        while True:
            self.check()
            now = time.monotonic()
            lteam = read_team(self.lmem)
            leader_in = bool(lteam is None or lteam.members)
            still = []
            for m in self.active():
                team = read_team(m.mem)
                if team is None or team.members:
                    still.append(m)
            d = decide_disband(leader_in, len(still), leader_left_at, members_left_at, now)
            self.say(d)
            if d.kind == 'done':
                break
            if d.kind == 'fail':
                for m in still:
                    db.record_failure(self.conn, m.c.char_id, d.reason, time.time())
                    self.drop(m, d.reason)
                if leader_in:
                    raise RuntimeError(d.reason)
                break
            if d.kind == 'leader_leave':
                try:
                    self.lgame.team_leave()
                except NotSent as e:
                    self.log.warning('队长退队请求没发出: %s', e)
                leader_left_at = now
            elif d.kind == 'members_leave':
                for m in still:
                    try:
                        m.game.team_leave()
                    except NotSent as e:
                        m.log.warning('退队请求没发出: %s', e)
                members_left_at = now
            time.sleep(self.s.tick)
        for m in self.active():
            m.state = 'done'

    def run(self):
        w = self.to_coast()
        self.record_shoe()
        self.skill_level = read_skill_level(self.lmem, self.s.leader_skill) or 0
        pet = read_fighting_pet(self.lmem)
        self.pet_level = pet.abilities.get(self.s.pet_magic, 0) if pet else 0
        self.log.info('队长技能 %d 等级 %d；出战宠物 %s', self.s.leader_skill, self.skill_level,
                      f'第 {pet.index} 只，法术 {self.s.pet_magic} 等级 {self.pet_level}，魔力 {pet.mp}' if pet else '没有')
        adopted = self.adopt()
        if adopted:
            self.log.info('队里已有 %d 个小号（上次中断），接着刷: %s', len(adopted),
                          ', '.join(self.members[c].c.name for c in adopted))
        else:
            self.goto(RENDEZVOUS, '集合点', 'to_rendezvous')
            chosen = self.choose()
            if not chosen:
                self.log.info('没有排刷怪队列的小号，本批不刷')
                return self.summary()
            for cid in chosen:
                self.add_member(cid)
            self.log.info('本批 %d 人: %s', len(chosen), ', '.join(self.members[c].c.name for c in chosen))
            self.form()
            if not self.active():
                raise RuntimeError('没有队员入队，不刷怪')
        self.farm()
        self.goto(RENDEZVOUS, '回集合点', 'returning')
        self.disband()
        return self.summary()

    def summary(self):
        roles, now = db.station_roles(self.conn), time.time()
        results = []
        for m in self.members.values():
            obs = observe(m.mem, read_world(m.mem))
            if obs is not None:
                db.save_observation(self.conn, obs, derive_phase(obs, db.ledger(self.conn, m.c.char_id), roles), now)
            ok = (m.state == 'done' and obs is not None and obs.map_id == COAST_MAP and not obs.team_leader
                  and obs.materials_done)
            results.append({'leader': self.leader.name, 'name': m.c.name, 'char_id': m.c.char_id, 'ok': ok,
                            'legs': obs.legs if obs else None, 'rumps': obs.rumps if obs else None,
                            'level': obs.level if obs else None, 'map': obs.map_id if obs else None,
                            'phase': db.alt(self.conn, m.c.char_id)['phase'], 'error': m.error})
        db.release(self.conn, self.sid(), list(self.members), now)
        db.heartbeat(self.conn, self.sid(), COAST, self.leader.char_id, 'idle', now)
        self.log.info('战斗 %d 场，技能 %d 次，普通攻击 %d 次，用时 %.1fs', self.battles, self.casts['cast'],
                      self.casts['attack'], time.monotonic() - self.started)
        db.log_event(self.conn, now, 'coast_farm', f'刷怪完成 {[r["name"] for r in results if r["ok"]]}，'
                     f'战斗 {self.battles} 场', station_id=self.sid())
        return results


def run_leader(station, leader, alts, settings):
    logger = log.for_account(leader.name)
    conn = db.connect(settings.db_path)
    try:
        with ProcessMemory(leader.session.pid, leader.session.base) as leader_mem:
            run = CoastRun(conn, station, leader, leader_mem, alts, settings, logger)
            try:
                return True, run.run()
            except Exception as e:
                logger.error('失败: %s', e, exc_info=not isinstance(e, RuntimeError))
                for m in run.members.values():
                    if m.state != 'dropped':
                        m.error = m.error or f'队长失败: {e}'
                return False, [{'leader': leader.name, 'name': leader.name, 'ok': False,
                                'error': f'{type(e).__name__}: {e}'}]
            finally:
                run.close()
    finally:
        conn.close()


def main():
    settings = load_settings(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'factory.toml')
    log_path = log.setup(ROOT / 'logs', prefix='coast')
    logger = log.for_account('main')
    logger.info('日志文件: %s', log_path)
    conn = db.connect(settings.db_path)
    stations = conn.execute('SELECT * FROM stations WHERE role=? ORDER BY station_id', (COAST,)).fetchall()
    conn.close()
    if not stations:
        logger.error('数据库里没有海岸队长；先运行 一键登录工位.cmd')
        return 2
    clients = {c.char_id: c for c in procs.discover(logger)}
    leaders = []
    for st in stations:
        c = clients.pop(st['char_id'], None)
        if c is None:
            logger.error('海岸队长 %s %s (ID=%d) 不在本工具的窗口里在线；先运行 一键登录工位.cmd', st['station_id'],
                         st['name'], st['char_id'])
        else:
            logger.info('海岸队长 %s: %s pid=%d 地图 %d 坐标=(%.0f,%.0f)', st['station_id'], c.name, c.session.pid,
                        c.map_id, c.x, c.y)
            leaders.append((st, c))
    if not leaders:
        return 2
    leader_ids = {c.char_id for _, c in leaders}
    alts = {}
    for c in clients.values():
        m = ROLE_NAME.match(c.name)
        if m and c.map_id == COAST_MAP and c.char_id not in leader_ids:
            alts[c.char_id] = (c, m.group(1), int(m.group(2)))
    logger.info('平静海岸2区的小号 %d 个: %s', len(alts), ', '.join(a[0].name for a in alts.values()))
    outcome = {}

    def work(st, c):
        outcome[st['station_id']] = run_leader(st, c, alts, settings)

    threads = [threading.Thread(target=work, args=(st, c), name=st['station_id']) for st, c in leaders]
    for t in threads:
        t.start()
        time.sleep(1.0)          # the first leader claims first; the second one takes the next alts in the queue
    for t in threads:
        t.join()
    results = [r for _, rs in outcome.values() for r in rs]
    out = ROOT / 'logs' / (log_path.stem.replace('coast_', 'coast_summary_') + '.json')
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), 'utf-8')
    logger.info('=' * 60)
    for r in results:
        logger.info('%-8s %-8s %s 腿=%s 鸡屁股=%s 地图=%s 阶段=%s %s', r['leader'], r['name'],
                    '完成' if r['ok'] else '失败', r.get('legs'), r.get('rumps'), r.get('map'), r.get('phase'),
                    r.get('error') or '')
    ok = sum(r['ok'] for r in results)
    logger.info('完成 %d/%d。汇总: %s', ok, len(results), out)
    all_ok = len(outcome) == len(stations) and all(flag for flag, _ in outcome.values())
    return 0 if all_ok and ok == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
