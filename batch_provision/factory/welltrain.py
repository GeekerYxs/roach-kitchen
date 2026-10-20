"""Stage 4b: the well leader takes the team formed in 4a to 阴森古井, fights until every member is level 11,
spends the members' talent points on 体质 as soon as they appear, then everybody goes home.

Entry: python -m factory.welltrain [factory.toml]
The batch = registered alts in the well leader's team (stage 4a, 一键古井组队.cmd). Every tick, from what is read:
  route    village -> 夕阳草原 entrance (130: 2544,2904) -> NPC 10152 -> 651 -> patrol A <-> B (well_patrol)
  battle   leader casts 扫射 803 on the first live enemy each time its SP changes, its pet casts 烈焰爆发 1504
           (normal attack when the skill is missing, the pet is short of MP, or the same SP got no reaction)
  talent   any member with talent points left gets all of them on 体质 (request 0x0070), in battle or not
  return   once every member is 11: each member uses 飞鞋 (recorded in the village) else 回城卷 and leaves the team,
           then the leader uses a 回城卷
A member that leaves the leader's team (died, dropped) is released from the batch; the rest go on.
Restart at any point continues from the observed state. Decisions are pure (tests/test_factory_welltrain.py).
"""
import json
import math
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from provisioner import log, native, procs
from provisioner.game import FIGHT_ATTACK, Game, NotSent
from provisioner.memory import ProcessMemory
from provisioner.world import (item_count, read_bag, read_battle, read_fighting_pet, read_level, read_shoe_record,
                               read_skill_level, read_talent_points, read_team, read_world)

from . import db
from .config import ROOT, load_settings
from .observe import observe
from .phase import MEADOW_MAP, SCROLL_ITEM, TARGET_LEVEL, VILLAGE_MAP, WELL, WELL_MAP, derive_phase, return_method
from .runner import ROLE_NAME

ENTRANCE = (2544, 2904)          # 夕阳草原 spot next to the well entrance NPC (old mwxqll run 2026-10-09)
ENTRANCE_NPC = 10152
ENTRANCE_RANGE = 80
ARRIVE = 30                      # this close to a patrol point counts as there
NAV_RETRY = 2.0                  # do not re-issue navigation more often than this
STALL = 6.0                      # navigating without moving 15 px for this long -> cancel and re-issue
SETTLE = 0.4                     # stand still this long before clicking the entrance (a battle could start)
CLICK_WAIT = 8.0                 # the map must change within this long after clicking
MAX_CLICKS = 3
FOLLOW_WAIT = 15.0               # at the entrance, wait this long for members still on another map
SELECT_RETRY = 3.0
RESEND = 5.0                     # same SP this long after our command -> send again
MAX_SKILL_SENDS = 3              # the skill sent this often for one SP without effect -> normal attack instead
TALENT_WAIT = 5.0                # remaining points must drop within this long
TALENT_MISSES = 3                # unconfirmed this often in a row -> only try every TALENT_BACKOFF seconds
TALENT_BACKOFF = 60.0
RETURN_WAIT = 6.0                # map must change this long after a 飞鞋 / 回城卷 request
LEAVE_WAIT = 5.0
DROP_AFTER = 3.0                 # a member missing from the leader's roster this long is dropped
OBSERVE_EVERY = 10.0             # save observations / renew the lease / heartbeat this often
ACTION_SHOE, ACTION_SCROLL = 'shoe_return', 'scroll_return'


@dataclass(frozen=True)
class Decision:
    kind: str
    reason: str
    arg: object = None


# ---- route (leader, out of battle) ---------------------------------------------------------------------

@dataclass
class Route:
    last_nav: float = -1e9
    progress_xy: tuple | None = None
    progress_at: float = 0.0
    still_xy: tuple | None = None
    still_since: float = 0.0
    entrance_at: float | None = None
    clicked_at: float | None = None
    clicks: int = 0
    last_select: float = -1e9
    patrol: int = 0              # index into the patrol points of the point we are walking to
    map_id: int | None = None

    def observe(self, w, now):
        if w is None:
            return
        if w.map_id != self.map_id:
            self.map_id, self.entrance_at, self.clicked_at, self.last_nav = w.map_id, None, None, -1e9
            self.progress_xy, self.progress_at = (w.x, w.y), now
        if self.progress_xy is None or math.dist((w.x, w.y), self.progress_xy) > 15:
            self.progress_xy, self.progress_at = (w.x, w.y), now
        xy = (round(w.x), round(w.y))
        if xy != self.still_xy or w.moving or w.nav_active:
            self.still_xy, self.still_since = xy, now
        if w.map_id == MEADOW_MAP and self.entrance_at is None and math.dist((w.x, w.y), ENTRANCE) <= ENTRANCE_RANGE:
            self.entrance_at = now

    def record(self, d, w, now):
        if d.kind == 'navigate':
            self.last_nav, self.progress_xy, self.progress_at = now, (w.x, w.y), now
            if d.arg[3] is not None:
                self.patrol = d.arg[3]
        elif d.kind == 'cancel_nav':
            self.last_nav = -1e9
        elif d.kind == 'click':
            self.clicked_at, self.clicks = now, self.clicks + 1
        elif d.kind == 'select':
            self.last_select = now


def _walk(w, map_id, target, memo, now, why, patrol=None):
    if w.nav_active or w.moving:
        if now - memo.progress_at > STALL:
            return Decision('cancel_nav', f'{STALL:.0f}s 没有移动，重新寻路')
        return Decision('wait', f'寻路中：{why}')
    if now - memo.last_nav < NAV_RETRY:
        return Decision('wait', f'等寻路开始：{why}')
    distance = math.dist((w.x, w.y), target) if w.map_id == map_id else None
    return Decision('navigate', f'寻路{why}' + (f'（距离 {distance:.0f}）' if distance is not None else ''),
                    (map_id, *target, patrol))


def decide_route(w, member_maps, memo, now, points):
    """Leader out of battle. member_maps: current map of each member still in the batch; points: the two patrol
    points inside the well (A, B).
    'battle' | 'wait' | 'navigate' | 'cancel_nav' | 'click' | 'select' | 'fail'."""
    if w is None:
        return Decision('wait', '队长加载中')
    if w.in_battle:
        return Decision('battle', '战斗中')
    if w.verification:
        return Decision('wait', '队长验证码弹窗，等待答题')
    if w.busy:
        return Decision('wait', f'队长忙 flags={w.flags:#x}')
    if w.map_id == WELL_MAP:
        target = points[memo.patrol]
        if math.dist((w.x, w.y), target) <= ARRIVE:
            nxt = 1 - memo.patrol
            return Decision('navigate', f'到 {"AB"[memo.patrol]} 点，巡逻去 {"AB"[nxt]} 点', (WELL_MAP, *points[nxt], nxt))
        return _walk(w, WELL_MAP, target, memo, now, f'巡逻去 {"AB"[memo.patrol]} 点', memo.patrol)
    if w.map_id not in (VILLAGE_MAP, MEADOW_MAP):
        return Decision('fail', f'队长在意外的地图 {w.map_id}')
    if w.map_id == VILLAGE_MAP or math.dist((w.x, w.y), ENTRANCE) > ENTRANCE_RANGE:
        return _walk(w, MEADOW_MAP, ENTRANCE, memo, now, '去夕阳草原古井入口')
    # at the entrance
    if w.dialog:
        hits = [(i, label) for i, label in w.dialog.options if i and '古井' in label]
        others = [(i, label) for i, label in w.dialog.options if i]
        hits = hits or (others if len(others) == 1 else [])
        if len(hits) != 1:
            return Decision('fail', f'古井入口对话框选项不认识: {w.dialog.options}')
        if now - memo.last_select < SELECT_RETRY:
            return Decision('wait', '已选择进入古井，等待传送')
        return Decision('select', f'选择「{hits[0][1]}」', hits[0][0])
    if w.nav_active:
        return Decision('cancel_nav', '到古井入口，停止寻路')
    if memo.clicked_at is not None and now - memo.clicked_at < CLICK_WAIT:
        return Decision('wait', '已点古井入口，等进入古井')
    if memo.clicks >= MAX_CLICKS:
        return Decision('fail', f'点了 {memo.clicks} 次古井入口都没进去')
    if w.moving or now - memo.still_since < SETTLE:
        return Decision('wait', '在古井入口站稳')
    behind = sum(m != MEADOW_MAP for m in member_maps)
    if behind and memo.entrance_at is not None and now - memo.entrance_at < FOLLOW_WAIT:
        return Decision('wait', f'等 {behind} 个队员跟到夕阳草原')
    return Decision('click', f'点古井入口 NPC {ENTRANCE_NPC}' + (f'（{behind} 个队员还不在夕阳草原）' if behind else ''),
                    ENTRANCE_NPC)


# ---- battle (leader + its pet) -------------------------------------------------------------------------

@dataclass
class Fight:
    last_sp: int | None = None
    sent_at: float = -1e9
    sends: int = 0              # commands sent for the current SP

    def record(self, sp, now):
        self.sends = self.sends + 1 if sp == self.last_sp else 1
        self.last_sp, self.sent_at = sp, now


def decide_fighter(f, memo, now, can_cast, who):
    """One fighter (leader or pet): 'cast' | 'attack' | 'none'. Like the official auto-fight: act whenever its
    SP changes; if the same SP stays RESEND seconds after our command, send again (normal attack after
    MAX_SKILL_SENDS casts — e.g. not enough MP)."""
    if f is None:
        return Decision('none', f'{who}不在战斗名单里')
    if f.dead:
        return Decision('none', f'{who}已倒下')
    if f.sp != memo.last_sp:
        kind = 'cast' if can_cast else 'attack'
        return Decision(kind, f'{who}蓄力点 {memo.last_sp} -> {f.sp}')
    if f.sp > 0 and now - memo.sent_at >= RESEND:
        kind = 'cast' if can_cast and memo.sends < MAX_SKILL_SENDS else 'attack'
        return Decision(kind, f'{who}蓄力点 {f.sp} 已 {RESEND:.0f}s 未变，第 {memo.sends + 1} 次出招')
    return Decision('none', f'{who}等蓄力点变化')


def decide_battle(battle, me_memo, pet_memo, now, skill_ok, pet_ok):
    """[(who, Decision)] for 'me' and 'pet'; target = first live enemy (client pos 0..9)."""
    if battle is None:
        return []
    if not battle.enemies:
        return [('me', Decision('none', '没有活着的敌人')), ('pet', Decision('none', '没有活着的敌人'))]
    target = battle.enemies[0]
    out = []
    for who, f, memo, ok, name in (('me', battle.me, me_memo, skill_ok, '队长'),
                                   ('pet', battle.pet, pet_memo, pet_ok, '宠物')):
        d = decide_fighter(f, memo, now, ok, name)
        out.append((who, Decision(d.kind, d.reason, target) if d.kind != 'none' else d))
    return out


# ---- talent points (members) -----------------------------------------------------------------------------

@dataclass
class Talent:
    sent_at: float | None = None
    before: int = 0
    misses: int = 0
    last_miss: float = -1e9


def decide_talent(points, memo, now):
    """'none' | 'wait' | 'add' (arg = points) | 'verified' | 'unconfirmed'."""
    if points is None:
        return Decision('wait', '读不到天赋点')
    if memo.sent_at is not None:
        if points < memo.before:
            return Decision('verified', f'天赋点 {memo.before} -> {points}')
        if now - memo.sent_at < TALENT_WAIT:
            return Decision('wait', '等天赋点变化')
        return Decision('unconfirmed', f'加体质 {TALENT_WAIT:.0f}s 后天赋点仍是 {points}')
    if points == 0:
        return Decision('none', '没有天赋点')
    if memo.misses >= TALENT_MISSES and now - memo.last_miss < TALENT_BACKOFF:
        return Decision('wait', f'连续 {memo.misses} 次没加上，{TALENT_BACKOFF:.0f}s 后再试')
    return Decision('add', f'{points} 点天赋全部加体质', points)


# ---- going home ------------------------------------------------------------------------------------------

@dataclass
class Home:
    method: str | None = None
    sent_at: float | None = None
    tried: set = field(default_factory=set)
    left_at: float | None = None


def decide_member_return(w, team, leader_id, shoe_ok, scroll_slot, memo, now):
    """Member after everyone reached 11. 'done' | 'wait' | 'leave' | 'shoe' | 'scroll' | 'unconfirmed' | 'stuck'."""
    if w is None or team is None:
        return Decision('wait', '加载中')
    in_team = bool(team.members) and team.leader == leader_id
    if w.map_id == VILLAGE_MAP:
        if not in_team:
            return Decision('done', '已在逍遥村西区，不在队里')
        if memo.left_at is not None and now - memo.left_at < LEAVE_WAIT:
            return Decision('wait', '已退队，等名单更新')
        return Decision('leave', '已回村，退出古井队')
    if memo.sent_at is not None:
        if now - memo.sent_at < RETURN_WAIT:
            return Decision('wait', f'等{"飞鞋" if memo.method == "shoe" else "回城卷"}生效')
        return Decision('unconfirmed', f'{"飞鞋" if memo.method == "shoe" else "回城卷"} {RETURN_WAIT:.0f}s 后仍在地图 {w.map_id}')
    if w.verification:
        return Decision('wait', '验证码弹窗，等待答题')
    if w.in_battle or w.busy:
        return Decision('wait', '忙/战斗中')
    if shoe_ok and 'shoe' not in memo.tried:
        return Decision('shoe', '用飞鞋回村')
    if scroll_slot is not None and 'scroll' not in memo.tried:
        return Decision('scroll', f'用回城卷回村（背包第 {scroll_slot} 格）', scroll_slot)
    return Decision('stuck', f'飞鞋和回城卷都用不了（试过 {sorted(memo.tried)}），留在地图 {w.map_id}')


def decide_leader_return(w, scroll_slot, memo, now):
    """Leader after the members went home: 'done' | 'wait' | 'cancel_nav' | 'scroll' | 'unconfirmed' | 'fail'."""
    if w is None:
        return Decision('wait', '队长加载中')
    if w.map_id == VILLAGE_MAP:
        return Decision('done', '队长已在逍遥村西区')
    if memo.sent_at is not None:
        if now - memo.sent_at < RETURN_WAIT:
            return Decision('wait', '等回城卷生效')
        return Decision('unconfirmed', f'回城卷 {RETURN_WAIT:.0f}s 后队长仍在地图 {w.map_id}')
    if w.verification:
        return Decision('wait', '队长验证码弹窗，等待答题')
    if w.in_battle or w.busy:
        return Decision('wait', '队长忙/战斗中')
    if w.nav_active:
        return Decision('cancel_nav', '停止巡逻')
    if len(memo.tried) >= 2:
        return Decision('fail', '队长用了 2 次回城卷都没回村')
    if scroll_slot is None:
        return Decision('fail', '队长背包里没有回城卷')
    return Decision('scroll', f'队长用回城卷回村（背包第 {scroll_slot} 格）', scroll_slot)


def scroll_slot(bag):
    return next((s.slot for s in bag or () if s.item_id == SCROLL_ITEM), None)


# ---- the run ---------------------------------------------------------------------------------------------

class Member:
    def __init__(self, client, account, slot, mem):
        self.c, self.account, self.slot, self.mem = client, account, slot, mem
        self.game = Game(client.session, mem)
        self.talent, self.home = Talent(), Home()
        self.in_battle, self.me_fight, self.pet_fight = False, Fight(), Fight()
        self.state = 'training'          # training -> home | stuck | dropped
        self.missing_since = None
        self.error = None
        self.level = None
        self.reasons = {}
        self.log = log.for_account(client.name)

    def say(self, topic, d):
        if self.reasons.get(topic) != d.reason:
            self.log.info('%s', d.reason)
        self.reasons[topic] = d.reason


class WellTrainRun:
    def __init__(self, conn, station, leader, leader_mem, alts, settings, logger):
        self.conn, self.station, self.leader, self.lmem = conn, station, leader, leader_mem
        self.alts, self.s, self.log = alts, settings, logger     # alts: {char_id: (client, account, slot)}
        self.lgame = Game(leader.session, leader_mem)
        self.members, self.mems = {}, []
        self.route, self.me_fight, self.pet_fight, self.lhome = Route(), Fight(), Fight(), Home()
        self.in_battle, self.battles, self.casts = False, 0, {'cast': 0, 'attack': 0}
        self.skill_level = self.pet_level = 0
        self.last_reason = None
        self.last_observe = -1e9
        self.target = TARGET_LEVEL          # factory/storeship.py trains store roles to [ship] min_level

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

    def _alive(self):
        if not native.alive(self.leader.session.pid):
            raise RuntimeError(f'队长游戏进程 {self.leader.session.pid} 已退出')
        for m in self.active():
            if not native.alive(m.c.session.pid):
                self.drop(m, '游戏进程已退出')

    def active(self):
        return [m for m in self.members.values() if m.state not in ('dropped',)]

    def drop(self, m, error):
        m.state, m.error = 'dropped', error
        m.log.error('移出本批: %s', error)
        self.release(m)

    # The alt bookkeeping in factory.db (leases, observations, pending return actions, failures). factory/storeship.py
    # overrides these: store roles are not alts.
    def release(self, m):
        db.release(self.conn, self.station['station_id'], [m.c.char_id], time.time())

    def claim(self, cids):
        return db.claim(self.conn, self.station['station_id'], cids, self.s.well_lease, time.time())

    def bookkeep(self, wall):
        sid = self.station['station_id']
        db.renew(self.conn, sid, [m.c.char_id for m in self.active()], self.s.well_lease, wall)
        db.heartbeat(self.conn, sid, WELL, self.leader.char_id, 'training', wall)
        roles = db.station_roles(self.conn)
        for m in self.active():
            obs = observe(m.mem, read_world(m.mem))
            if obs is not None:
                db.save_observation(self.conn, obs, derive_phase(obs, db.ledger(self.conn, m.c.char_id), roles), wall)

    def shoe_ok(self, m, w, wall):
        record = read_shoe_record(m.mem)
        obs = observe(m.mem, w)
        return (obs is not None and record is not None and record[0] == VILLAGE_MAP
                and return_method(obs, db.ledger(self.conn, m.c.char_id), wall) == 'shoe')

    def note_home(self, m, wall):
        row = db.alt(self.conn, m.c.char_id)
        if row['pending_action'] == ACTION_SHOE:
            db.complete_action(self.conn, m.c.char_id, wall, shoe_used_at=row['pending_at'] or wall)
        elif row['pending_action'] == ACTION_SCROLL:
            db.complete_action(self.conn, m.c.char_id, wall)
        db.release(self.conn, self.station['station_id'], [m.c.char_id], wall)

    def note_return(self, m, action, wall):
        db.mark_pending(self.conn, m.c.char_id, action, wall)

    def note_return_failed(self, m, reason, wall):
        db.clear_pending(self.conn, m.c.char_id, wall, reason)

    def note_stuck(self, m, reason, wall):
        db.record_failure(self.conn, m.c.char_id, reason, wall)
        db.release(self.conn, self.station['station_id'], [m.c.char_id], wall)

    # ---- setup
    def setup(self):
        team = read_team(self.lmem)
        if team is None:
            raise RuntimeError('读不到队长的队伍')
        if team.members and team.leader != self.leader.char_id:
            raise RuntimeError(f'队长在别人的队里（队长 {team.leader}），请手动退队')
        strangers = [cid for cid in team.members[1:] if cid not in self.alts]
        if strangers:
            raise RuntimeError(f'队里有不认识的角色 {strangers}（不是本工具窗口里的小号），请手动处理')
        chosen = list(team.members[1:])
        if not chosen:
            return []
        got = self.claim(chosen)
        for cid in set(chosen) - set(got):
            self.log.warning('%s 被别的工位占着或已隔离，本批不管它', self.alts[cid][0].name)
        for cid in got:
            c, account, slot = self.alts[cid]
            mem = ProcessMemory(c.session.pid, c.session.base)
            self.mems.append(mem)
            self.members[cid] = Member(c, account, slot, mem)
        self.skill_level = read_skill_level(self.lmem, self.s.leader_skill) or 0
        pet = read_fighting_pet(self.lmem)
        self.pet_level = pet.abilities.get(self.s.pet_magic, 0) if pet else 0
        self.log.info('队长技能 %d 等级 %d；出战宠物 %s', self.s.leader_skill, self.skill_level,
                      f'第 {pet.index} 只，法术 {self.s.pet_magic} 等级 {self.pet_level}，魔力 {pet.mp}' if pet else '没有')
        if not self.skill_level:
            self.log.warning('队长没学技能 %d，只用普通攻击', self.s.leader_skill)
        if not self.pet_level:
            self.log.warning('出战宠物没有法术 %d，宠物只用普通攻击', self.s.pet_magic)
        return got

    # ---- per-tick pieces
    def periodic(self, now):
        if now - self.last_observe < OBSERVE_EVERY:
            return
        self.last_observe = now
        self.bookkeep(time.time())

    def check_roster(self, leader_team, now):
        roster = set(leader_team.members) if leader_team else set()
        for m in self.active():
            if m.state != 'training':
                continue
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
            self.log.info('%s → %s，目标位置 %d', d.reason, what, d.arg)
            f = battle.pet if is_pet else battle.me
            (self.pet_fight if is_pet else self.me_fight).record(f.sp, now)

    def step_member_battle(self, m, now):
        """Members (and their pets) attack the first live enemy whenever their SP changes, like the official
        auto-fight. Off by default (member_attack): live 2026-10-12 the round plays every fighter's action one
        after another (~1.4 s each), so 8 extra attackers made a battle ~25 s instead of ~14 s."""
        w = read_world(m.mem)
        if not (w and w.in_battle):
            m.in_battle = False
            return
        if not m.in_battle:
            m.in_battle, m.me_fight, m.pet_fight = True, Fight(), Fight()
        battle = read_battle(m.mem)
        for who, d in decide_battle(battle, m.me_fight, m.pet_fight, now, False, False):
            if d.kind != 'attack':
                continue
            is_pet = who == 'pet'
            m.game.fight_command(FIGHT_ATTACK, is_pet=is_pet, target=d.arg)
            m.log.debug('%s → 普通攻击，目标位置 %d', d.reason, d.arg)
            (m.pet_fight if is_pet else m.me_fight).record((battle.pet if is_pet else battle.me).sp, now)

    def leave_battle(self, now):
        if self.in_battle:
            self.in_battle = False
            self.route.last_nav = -1e9      # a battle interrupts navigation; allow re-issue at once
            self.route.progress_at = now    # standing still in battle is not a stalled walk
            levels = ', '.join(f'{m.c.name} {m.level}' for m in self.active())
            self.log.info('战斗结束（第 %d 场）。等级: %s', self.battles, levels)

    def step_route(self, lw, now):
        maps = []
        for m in self.active():
            w = read_world(m.mem)
            maps.append(w.map_id if w else None)
        if lw is not None and not lw.in_battle:
            self.leave_battle(now)          # before deciding: resets the stall timer the decision reads
        self.route.observe(lw, now)
        d = decide_route(lw, maps, self.route, now, self.s.well_patrol)
        if d.kind == 'battle':
            self.step_battle(now)
            return
        self.say(d)
        if d.kind == 'fail':
            raise RuntimeError(d.reason)
        if d.kind == 'navigate':
            self.lgame.navigate(*d.arg[:3])
        elif d.kind == 'cancel_nav':
            self.lgame.cancel_navigation()
        elif d.kind == 'click':
            self.lgame.click_npc(d.arg)
        elif d.kind == 'select':
            self.lgame.select_dialog(d.arg)
        if d.kind != 'wait':
            self.route.record(d, lw, now)

    def step_member_return(self, m, now):
        w, team = read_world(m.mem), read_team(m.mem)
        wall = time.time()
        d = decide_member_return(w, team, self.leader.char_id, self.shoe_ok(m, w, wall), scroll_slot(read_bag(m.mem)),
                                 m.home, now)
        m.say('home', d)
        if d.kind == 'done':
            m.state = 'home'
            self.note_home(m, wall)
        elif d.kind == 'leave':
            try:
                m.game.team_leave()
            except NotSent as e:
                m.log.warning('退队请求没发出: %s', e)
            m.home.left_at = now
        elif d.kind == 'unconfirmed':
            self.note_return_failed(m, d.reason, wall)
            m.home.tried.add(m.home.method)
            m.home.method = m.home.sent_at = None
        elif d.kind == 'stuck':
            m.state, m.error = 'stuck', d.reason
            m.log.error('%s', d.reason)
            self.note_stuck(m, d.reason, wall)
        elif d.kind in ('shoe', 'scroll'):
            self.note_return(m, ACTION_SHOE if d.kind == 'shoe' else ACTION_SCROLL, wall)
            try:
                m.game.shoe_return() if d.kind == 'shoe' else m.game.use_item(d.arg)
            except NotSent as e:
                self.note_return_failed(m, str(e), wall)
                m.home.tried.add(d.kind)
                return
            m.home.method, m.home.sent_at = d.kind, now

    def step_leader_return(self, lw, now):
        d = decide_leader_return(lw, scroll_slot(read_bag(self.lmem)), self.lhome, now)
        self.say(d)
        if d.kind == 'fail':
            raise RuntimeError(d.reason)
        if d.kind == 'unconfirmed':
            self.lhome.tried.add(f'scroll{len(self.lhome.tried)}')
            self.lhome.sent_at = None
        elif d.kind == 'cancel_nav':
            self.lgame.cancel_navigation()
        elif d.kind == 'scroll':
            self.lgame.use_item(d.arg)
            self.lhome.sent_at = now
        return d.kind == 'done'

    # ---- main loop
    def run(self):
        started = time.monotonic()
        chosen = self.setup()
        self.log.info('本批 %d 人: %s', len(self.members), ', '.join(m.c.name for m in self.members.values()))
        if not chosen:
            self.log.info('队长队里没有小号；直接回村')
        returning = False
        while True:
            now = time.monotonic()
            if now - started > self.s.well_train_timeout:
                raise RuntimeError(f'{self.s.well_train_timeout:.0f}s 内没有完成')
            self._alive()
            lw, leader_team = read_world(self.lmem), read_team(self.lmem)
            if lw and lw.char_id != self.leader.char_id:
                raise RuntimeError('队长角色变了')
            self.periodic(now)
            for m in self.active():
                m.level = read_level(m.mem)
                if m.state == 'training' or m.state == 'home':
                    self.step_talent(m, now)
                if m.state == 'training' and self.s.member_attack:
                    self.step_member_battle(m, now)
            if not returning:
                self.check_roster(leader_team, now)
                training = [m for m in self.active() if m.state == 'training']
                if all(m.level is not None and m.level >= self.target for m in training):
                    returning = True
                    self.log.info('全员到 %d 级（%s），开始回城', self.target,
                                  ', '.join(f'{m.c.name} {m.level}' for m in training) or '没有队员')
                else:
                    self.step_route(lw, now)
            if returning:
                if lw is not None and lw.in_battle:
                    self.step_battle(now)          # a battle that started before we stopped: finish it
                else:
                    self.leave_battle(now)
                    pending = [m for m in self.active() if m.state == 'training']
                    for m in pending:
                        self.step_member_return(m, now)
                    if not [m for m in self.active() if m.state == 'training']:
                        if self.step_leader_return(lw, now):
                            break
            time.sleep(self.s.tick)
        return self.summary(started)

    def summary(self, started):
        results = []
        for m in self.members.values():
            w = read_world(m.mem)
            results.append({'name': m.c.name, 'char_id': m.c.char_id, 'ok': m.state == 'home',
                            'level': read_level(m.mem), 'talent_left': read_talent_points(m.mem),
                            'map': w.map_id if w else None, 'error': m.error})
        self.log.info('战斗 %d 场，技能 %d 次，普通攻击 %d 次，用时 %.1fs', self.battles, self.casts['cast'],
                      self.casts['attack'], time.monotonic() - started)
        db.log_event(self.conn, time.time(), 'well_train',
                     f'带练完成 {[r["name"] for r in results if r["ok"]]}，战斗 {self.battles} 场',
                     station_id=self.station['station_id'])
        return results


def main():
    settings = load_settings(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'factory.toml')
    log_path = log.setup(ROOT / 'logs', prefix='welltrain')
    logger = log.for_account('main')
    logger.info('日志文件: %s', log_path)
    conn = db.connect(settings.db_path)
    stations = conn.execute('SELECT * FROM stations WHERE role=?', (WELL,)).fetchall()
    if len(stations) != 1:
        logger.error('数据库里的古井队长应正好 1 个，实际 %d 个；先运行 一键登录工位.cmd', len(stations))
        return 2
    station = stations[0]
    clients = {c.char_id: c for c in procs.discover(logger)}
    leader = clients.pop(station['char_id'], None)
    if leader is None:
        logger.error('古井队长 %s (ID=%d) 不在本工具的窗口里在线；先运行 一键登录工位.cmd', station['name'],
                     station['char_id'])
        return 2
    logger.info('古井队长: %s pid=%d 地图 %d 坐标=(%.0f,%.0f)', leader.name, leader.session.pid, leader.map_id,
                leader.x, leader.y)
    alts = {}
    for c in clients.values():
        m = ROLE_NAME.match(c.name)
        if m and db.alt(conn, c.char_id) is not None:
            alts[c.char_id] = (c, m.group(1), int(m.group(2)))
    results, ok_run = [], False
    with ProcessMemory(leader.session.pid, leader.session.base) as leader_mem:
        run = WellTrainRun(conn, station, leader, leader_mem, alts, settings, logger)
        try:
            results = run.run()
            ok_run = True
        except Exception as e:
            logger.error('失败: %s', e, exc_info=not isinstance(e, RuntimeError))
            results = [{'name': leader.name, 'ok': False, 'error': f'{type(e).__name__}: {e}'}]
        finally:
            run.close()
    conn.close()
    out = ROOT / 'logs' / (log_path.stem.replace('welltrain_', 'welltrain_summary_') + '.json')
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), 'utf-8')
    logger.info('=' * 60)
    for r in results:
        logger.info('%-8s %s 等级=%s 剩余天赋=%s 地图=%s %s', r['name'], '回村' if r['ok'] else '失败',
                    r.get('level'), r.get('talent_left'), r.get('map'), r.get('error') or '')
    ok = sum(r['ok'] for r in results)
    logger.info('回村 %d/%d。汇总: %s', ok, len(results), out)
    return 0 if ok_run and ok == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
