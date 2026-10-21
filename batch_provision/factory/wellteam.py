"""Stage 4a: the well leader forms its team at the village spawn and every member eats one 地瓜.

Entry: python -m factory.wellteam [factory.toml]
The well leader is the station registered with role 'well' (一键登录工位.cmd). One batch per run:
  1. leader walks to the spawn point (1266,1174) and stands still
  2. alts on map 1 whose derived phase is queue_well (level < 11, meat eaten, shoe recorded, no team) are
     claimed (lease in factory.db), oldest first, up to 4; alts already in the leader's team are kept
  3. invite (leader, request 0x30) -> accept (alt, client function 0x21f590) -> both rosters agree
  4. each member eats one 地瓜 32004 unless it ate one less than 55 min ago (phase.should_eat_potato)
Stage 4b (walk to the well, train to 11, return) picks the team up from here.

An alt that fails 3 times (invite/accept/eat not confirmed) is quarantined and dropped from the batch;
the others go on. Invitations that reach nobody at all are the leader's fault, not the alts' (Heard). The decisions are pure (tests/test_factory_wellteam.py).
"""
import json
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from provisioner import log, native, procs
from provisioner.game import Game, NotSent
from provisioner.memory import ProcessMemory
from provisioner.world import item_count, read_bag, read_invite_byte, read_level, read_team, read_world

from . import db
from .config import ROOT, load_settings
from .observe import observe
from .phase import POTATO_ITEM, QUEUE_WELL, VILLAGE_MAP, WELL, derive_phase, should_eat_potato
from .runner import ROLE_NAME

SPAWN = (1266, 1174)        # 逍遥村西区 arrival point = the well team's rendezvous
RENDEZVOUS_RADIUS = 120     # leader within this of SPAWN counts as there
INVITE_RANGE = 300          # alt <-> leader; the official friend script allows 400
SETTLE = 0.5                # leader standing still this long before inviting (old 'obstacle' rejections)
ACCEPT_DELAY = 0.5          # [team+0xA8] may still hold an older invite from the same leader
INVITE_WAIT = 6.0           # the invitation must show on the alt within this long
JOIN_WAIT = 6.0             # after accepting, both rosters must agree within this long
INVITE_GAP = 0.3            # between two invitations sent by the leader
UNHEARD_ROUNDS = 2          # rounds of invitations that reached nobody before the leader, not the alts, is blamed
CONFIRM_WAIT = 5.0          # 地瓜 count must drop within this long
ACTION_INVITE, ACTION_POTATO = 'well_invite', 'potato'


@dataclass(frozen=True)
class Decision:
    kind: str
    reason: str
    arg: object = None


def _idle(w):
    return not (w.in_battle or w.busy or w.nav_active or w.moving or w.verification)


# ---- leader ------------------------------------------------------------------------------------------

def decide_leader(world, team, leader_id, known_alts, still_for):
    """Leader at the rendezvous and free to invite? known_alts: char_ids of our registered alts.
    'walk' | 'wait' | 'fail' | 'ready'."""
    if world is None or team is None:
        return Decision('wait', '队长加载中')
    if world.map_id != VILLAGE_MAP:
        return Decision('fail', f'队长不在逍遥村西区（地图 {world.map_id}）')
    if team.members and team.leader != leader_id:
        return Decision('fail', f'队长在别人的队里（队长 {team.leader}），请手动退队')
    strangers = [m for m in team.members if m != leader_id and m not in known_alts]
    if strangers:
        return Decision('fail', f'队长队里有不认识的角色 {strangers}，请手动处理')
    if world.verification:
        return Decision('wait', '队长验证码弹窗，等待答题')
    if world.in_battle or world.busy:
        return Decision('wait', '队长忙/战斗中')
    distance = math.dist((world.x, world.y), SPAWN)
    if distance > RENDEZVOUS_RADIUS:
        if world.nav_active or world.moving:
            return Decision('wait', f'队长走向出生点（还差 {distance:.0f}）')
        return Decision('walk', f'队长离出生点 {distance:.0f}，走过去')
    if world.nav_active or world.moving or still_for < SETTLE:
        return Decision('wait', '队长站稳后再邀请')
    return Decision('ready', f'队长在出生点（距离 {distance:.0f}），队里已有 {len(team.members)} 人')


def pick(waiting_ids, adopted, size):
    """Which queued alts to claim: keep the ones already in the team, fill up to `size` oldest first."""
    room = max(0, size - len(adopted))
    return [cid for cid in waiting_ids if cid not in adopted][:room]


# ---- one member joining --------------------------------------------------------------------------------

@dataclass
class Join:
    invited_at: float | None = None
    accepted_at: float | None = None


class LeaderUnheard(RuntimeError):
    """The leader's invitations reach none of the batch: its client is broken, the alts are not."""


@dataclass
class Heard:
    """One per batch: did any invitation from this leader show on an alt? Until one does, an invitation that never
    arrives is not the alt's failure. Live 2026-10-21: well3's client stayed alive but stopped delivering invitations
    at 05:55; 3 misses per alt quarantined every alt it claimed, 178 by the morning."""
    heard: bool = False
    misses: int = 0

    def missed(self, joining):
        """An invitation timed out; joining = members still joining. 'alt' (count it against the alt) |
        'retry' (invite again, nobody is blamed yet) | 'leader' (stop the batch: LeaderUnheard)."""
        if self.heard:
            return 'alt'
        self.misses += 1
        return 'leader' if self.misses >= UNHEARD_ROUNDS * max(1, joining) else 'retry'

    def reason(self):
        return f'队长的邀请连续 {self.misses} 次谁都没收到：队长客户端异常，小号不算失败'


def decide_member(alt_id, world, team, leader_id, leader_world, leader_team, memo, now, map_id=VILLAGE_MAP,
                  map_name='逍遥村西区'):
    """'joined' | 'invite' | 'accept' | 'wait' | 'unconfirmed' | 'fail'. map_id: where the team forms."""
    if world is None or team is None or leader_team is None:
        return Decision('wait', '加载中')
    if team.leader == leader_id and alt_id in leader_team.members:
        return Decision('joined', f'已在队里（队伍 {len(leader_team.members)} 人）')
    if team.members and team.leader != leader_id:
        return Decision('fail', f'在别的队伍里（队长 {team.leader}）')
    if memo.accepted_at is not None:
        if now - memo.accepted_at < JOIN_WAIT:
            return Decision('wait', '已接受邀请，等队伍名单更新')
        return Decision('unconfirmed', f'接受邀请 {JOIN_WAIT:.0f}s 后仍不在队里')
    if memo.invited_at is not None:
        if team.inviter == leader_id and now - memo.invited_at >= ACCEPT_DELAY:
            return Decision('accept', '收到队长邀请，接受')
        if now - memo.invited_at < INVITE_WAIT:
            return Decision('wait', '等邀请到达')
        return Decision('unconfirmed', f'邀请 {INVITE_WAIT:.0f}s 内没有到达（邀请人 {team.inviter}）', 'invite')
    if world.map_id != map_id:
        return Decision('fail', f'不在{map_name}（地图 {world.map_id}）')
    distance = math.dist((world.x, world.y), (leader_world.x, leader_world.y))
    if distance > INVITE_RANGE:
        return Decision('fail', f'离队长太远 ({distance:.0f} > {INVITE_RANGE})')
    if not _idle(world):
        return Decision('wait', '小号忙/战斗/移动/验证中')
    return Decision('invite', f'邀请入队（距离 {distance:.0f}）')


# ---- 地瓜 -----------------------------------------------------------------------------------------------

@dataclass
class Eat:
    sent_at: float | None = None
    count_before: int | None = None


def decide_potato(obs, world, bag, ledger, pending_action, memo, now, wall_now):
    """'done' | 'skip' | 'use' | 'wait' | 'verified' | 'unconfirmed' | 'fail'. `now` is monotonic, `wall_now`
    is time.time() (the ledger's clock)."""
    if obs is None or world is None or bag is None:
        return Decision('wait', '加载中')
    count = item_count(bag, POTATO_ITEM)
    if memo.sent_at is not None:
        if count < memo.count_before:
            return Decision('verified', f'地瓜 {memo.count_before} -> {count}')
        if now - memo.sent_at < CONFIRM_WAIT:
            return Decision('wait', '等背包数量变化')
        return Decision('unconfirmed', f'{CONFIRM_WAIT:.0f}s 内地瓜数量没变（{count}）')
    if pending_action == ACTION_POTATO:
        return Decision('verified', '上次已发出吃地瓜请求（程序中断过），按已吃处理')
    if not should_eat_potato(obs, ledger, wall_now):
        if ledger.potato_at is not None:
            return Decision('done', f'{(wall_now - ledger.potato_at) / 60:.0f} 分钟前吃过地瓜，还有效')
        return Decision('skip', f'不吃地瓜（{obs.level} 级，地瓜 {obs.potatoes} 个）')
    if world.verification:
        return Decision('wait', '验证码弹窗，等待答题')
    if world.in_battle or world.busy:
        return Decision('wait', '忙/战斗中')
    slot = next(s for s in bag if s.item_id == POTATO_ITEM)
    return Decision('use', f'吃地瓜（背包第 {slot.slot} 格，{slot.quantity} 个）', slot)


# ---- the run ---------------------------------------------------------------------------------------------

class Member:
    def __init__(self, client, account, slot, mem):
        self.c, self.account, self.slot, self.mem = client, account, slot, mem
        self.game = Game(client.session, mem)
        self.join, self.eat = Join(), Eat()
        self.state = 'joining'          # joining -> eating -> ready | dropped
        self.error = None
        self.last_reason = None
        self.log = log.for_account(client.name)

    def say(self, d):
        if d.reason != self.last_reason:
            self.log.info('%s', d.reason)
        self.last_reason = d.reason


class WellTeamRun:
    def __init__(self, conn, station, leader, leader_mem, alts, settings, logger):
        self.conn, self.station, self.leader, self.lmem = conn, station, leader, leader_mem
        self.alts, self.s, self.log = alts, settings, logger     # alts: {char_id: (client, account, slot)}
        self.lgame = Game(leader.session, leader_mem)
        self.members, self.mems = {}, []

    def close(self):
        for m in self.members.values():
            m.game.close()
        self.lgame.close()
        for mem in self.mems:
            mem.close()

    def _alive(self):
        for pid in [self.leader.session.pid] + [m.c.session.pid for m in self.members.values()]:
            if not native.alive(pid):
                raise RuntimeError(f'游戏进程 {pid} 已退出')

    def to_rendezvous(self, deadline):
        still_xy, still_since, last = None, time.monotonic(), None
        while True:
            now = time.monotonic()
            if now > deadline:
                raise RuntimeError('队长没能在时限内到达出生点')
            self._alive()
            world, team = read_world(self.lmem), read_team(self.lmem)
            xy = (round(world.x), round(world.y)) if world else None
            if xy != still_xy or (world and world.moving):
                still_xy, still_since = xy, now
            d = decide_leader(world, team, self.leader.char_id, set(self.alts), now - still_since)
            if d.reason != last:
                self.log.info('%s', d.reason)
            last = d.reason
            if d.kind == 'fail':
                raise RuntimeError(d.reason)
            if d.kind == 'ready':
                return team
            if d.kind == 'walk':
                self.lgame.navigate(VILLAGE_MAP, *SPAWN)
                time.sleep(0.5)
            time.sleep(self.s.tick)

    def choose(self, leader_team):
        """Observe every village alt, save its phase, claim the batch. Returns the members' char_ids."""
        roles = db.station_roles(self.conn)
        for cid, (c, account, slot) in self.alts.items():
            db.register_alt(self.conn, cid, account, slot, c.name, time.time())
            try:
                with ProcessMemory(c.session.pid, c.session.base) as mem:
                    obs = observe(mem, read_world(mem))
            except OSError:
                obs = None      # the window closed meanwhile (live 2026-10-13 04:19: WinError 87 stopped the well leader)
            if obs is None:
                self.log.info('%s 读不到状态，这次不选', c.name)
                continue
            ledger = db.ledger(self.conn, cid)
            plan = derive_phase(obs, ledger, roles)
            db.save_observation(self.conn, obs, plan, time.time())
            self.log.info('%s: %d 级 阶段=%s（%s）', c.name, obs.level, plan.phase, plan.reason)
        adopted = [m for m in leader_team.members if m in self.alts]
        now = time.time()
        waiting = [r['char_id'] for r in db.waiting(self.conn, QUEUE_WELL, now) if r['char_id'] in self.alts]
        wanted = pick(waiting, adopted, self.s.well_team_size)
        got = db.claim(self.conn, self.station['station_id'], adopted + wanted, self.s.well_lease, now)
        lost = set(adopted + wanted) - set(got)
        if lost:
            self.log.warning('这些小号被别的工位占着，没认领到: %s', sorted(lost))
        return [cid for cid in adopted + wanted if cid in got]

    def drop(self, m, error):
        m.state, m.error = 'dropped', error
        m.log.error('移出本批: %s', error)
        db.release(self.conn, self.station['station_id'], [m.c.char_id], time.time())

    def failure(self, m, reason, memo_reset):
        memo_reset()
        if db.record_failure(self.conn, m.c.char_id, reason, time.time()):
            self.drop(m, f'连续失败 {db.MAX_RETRIES} 次，已隔离: {reason}')

    def run(self):
        started = time.monotonic()
        deadline = started + self.s.well_form_timeout
        leader_team = self.to_rendezvous(deadline)
        chosen = self.choose(leader_team)
        if not chosen:
            self.log.info('没有排古井队列的小号，本批不组队')
            return []
        for cid in chosen:
            c, account, slot = self.alts[cid]
            mem = ProcessMemory(c.session.pid, c.session.base)
            self.mems.append(mem)
            self.members[cid] = Member(c, account, slot, mem)
        self.log.info('本批 %d 人: %s', len(chosen), ', '.join(self.members[c].c.name for c in chosen))
        leader_level, invite_byte = read_level(self.lmem), read_invite_byte(self.lmem)
        last_invite, heard = 0.0, Heard()
        while True:
            now = time.monotonic()
            if now > deadline:
                for m in self.members.values():
                    if m.state in ('joining', 'eating'):
                        self.drop(m, f'{self.s.well_form_timeout:.0f}s 内没有完成')
                break
            self._alive()
            db.renew(self.conn, self.station['station_id'], [m.c.char_id for m in self.members.values()
                                                             if m.state != 'dropped'], self.s.well_lease, time.time())
            leader_world, leader_team = read_world(self.lmem), read_team(self.lmem)
            for m in self.members.values():
                if m.state == 'joining':
                    world, team = read_world(m.mem), read_team(m.mem)
                    if world and world.char_id != m.c.char_id:
                        raise RuntimeError(f'{m.c.name} 角色变了')
                    d = decide_member(m.c.char_id, world, team, self.leader.char_id, leader_world, leader_team,
                                      m.join, now)
                    m.say(d)
                    if d.kind == 'joined':
                        m.state = 'eating'
                        if db.alt(self.conn, m.c.char_id)['pending_action'] == ACTION_INVITE:
                            db.complete_action(self.conn, m.c.char_id, time.time())
                    elif d.kind == 'fail':
                        self.drop(m, d.reason)
                    elif d.kind == 'unconfirmed' and d.arg == 'invite' and (
                            blame := heard.missed(sum(x.state == 'joining' for x in self.members.values()))) != 'alt':
                        m.join = Join()
                        if blame == 'leader':
                            raise LeaderUnheard(heard.reason())
                    elif d.kind == 'unconfirmed':
                        self.failure(m, d.reason, lambda m=m: setattr(m, 'join', Join()))
                    elif d.kind == 'invite' and now - last_invite >= INVITE_GAP:
                        db.mark_pending(self.conn, m.c.char_id, ACTION_INVITE, time.time())
                        try:
                            self.lgame.team_invite(m.c.char_id, leader_level, invite_byte, self.leader.name)
                        except NotSent as e:
                            db.clear_pending(self.conn, m.c.char_id, time.time(), str(e))
                            raise RuntimeError(f'队长的邀请没发出: {e}') from e
                        m.join.invited_at = last_invite = time.monotonic()
                    elif d.kind == 'accept':
                        heard.heard = True
                        try:
                            m.game.team_accept()
                        except NotSent as e:
                            self.drop(m, f'接受邀请没发出: {e}')
                            continue
                        m.join.accepted_at = time.monotonic()
                elif m.state == 'eating':
                    self.step_potato(m, now)
            if all(m.state in ('ready', 'dropped') for m in self.members.values()):
                break
            time.sleep(self.s.tick)
        return self.summary(started)

    def step_potato(self, m, now):
        world, bag = read_world(m.mem), read_bag(m.mem)
        obs = observe(m.mem, world)
        row = db.alt(self.conn, m.c.char_id)
        if row['quarantined']:
            self.drop(m, f'已隔离: {row["last_error"]}')
            return
        d = decide_potato(obs, world, bag, db.ledger(self.conn, m.c.char_id), row['pending_action'], m.eat, now,
                          time.time())
        m.say(d)
        if d.kind in ('done', 'skip'):
            m.state = 'ready'
        elif d.kind == 'verified':
            db.complete_action(self.conn, m.c.char_id, time.time(), potato_at=time.time())
            m.state = 'ready'
        elif d.kind == 'fail':
            self.drop(m, d.reason)
        elif d.kind == 'unconfirmed':
            self.failure(m, d.reason, lambda: setattr(m, 'eat', Eat()))
        elif d.kind == 'use':
            db.mark_pending(self.conn, m.c.char_id, ACTION_POTATO, time.time())
            try:
                m.game.use_item(d.arg.slot)
            except NotSent as e:
                db.clear_pending(self.conn, m.c.char_id, time.time(), str(e))
                self.drop(m, f'吃地瓜请求没发出: {e}')
                return
            m.eat = Eat(sent_at=time.monotonic(), count_before=item_count(bag, POTATO_ITEM))

    def summary(self, started):
        leader_team = read_team(self.lmem)
        results = []
        for m in self.members.values():
            team = read_team(m.mem)
            results.append({'name': m.c.name, 'char_id': m.c.char_id, 'ok': m.state == 'ready',
                            'team_leader': team.leader if team else None, 'error': m.error,
                            'potato_at': db.alt(self.conn, m.c.char_id)['potato_at']})
        self.log.info('队长名单: %s，用时 %.1fs', list(leader_team.members) if leader_team else None,
                      time.monotonic() - started)
        db.log_event(self.conn, time.time(), 'well_team',
                     f'组队完成 {[r["name"] for r in results if r["ok"]]}', station_id=self.station['station_id'])
        return results


def main():
    settings = load_settings(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'factory.toml')
    log_path = log.setup(ROOT / 'logs', prefix='wellteam')
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
    logger.info('古井队长: %s pid=%d 坐标=(%.0f,%.0f)', leader.name, leader.session.pid, leader.x, leader.y)
    alts = {}
    for c in clients.values():
        m = ROLE_NAME.match(c.name)
        if m and c.map_id == VILLAGE_MAP:
            alts[c.char_id] = (c, m.group(1), int(m.group(2)))
        else:
            logger.info('%s 不是在逍遥村西区的小号，跳过', c.name)
    results = []
    with ProcessMemory(leader.session.pid, leader.session.base) as leader_mem:
        run = WellTeamRun(conn, station, leader, leader_mem, alts, settings, logger)
        try:
            results = run.run()
        except Exception as e:
            logger.error('失败: %s', e, exc_info=not isinstance(e, RuntimeError))
            results = [{'name': leader.name, 'ok': False, 'error': f'{type(e).__name__}: {e}'}]
        finally:
            run.close()
    conn.close()
    out = ROOT / 'logs' / (log_path.stem.replace('wellteam_', 'wellteam_summary_') + '.json')
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), 'utf-8')
    logger.info('=' * 60)
    for r in results:
        logger.info('%-8s %s %s', r['name'], '就绪' if r['ok'] else '失败', r.get('error') or '')
    ok = sum(r['ok'] for r in results)
    logger.info('就绪 %d/%d。汇总: %s', ok, len(results), out)
    return 0 if results and ok == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
