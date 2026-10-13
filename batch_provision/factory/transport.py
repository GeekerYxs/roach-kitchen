"""Stage 5: the dispatcher takes level-11 alts from the village to 平静海岸2区 (map 81) through PP鸡.

Entry: python -m factory.transport [factory.toml]
The dispatcher is the station registered with role 'dispatcher' (一键登录工位.cmd). One batch per run:
  1. dispatcher walks to the village spawn (1266,1174), the rendezvous (same rule as stage 4a)
  2. alts on map 1 whose derived phase is queue_transport are claimed, oldest first, up to 4; alts already in
     the dispatcher's team are kept
  3. members below the top-up floor get gold first (stage 3 trade; each member pays its own 190 fee)
  4. invite -> accept -> rosters agree (stage 4a calls)
  5. dispatcher walks to 传送操作员3号 (NPC 11, map 1 (342,315)), the team follows; once the members caught up:
     click the NPC -> 「传送服务」 -> 「平静海岸2区 ...」 -> the dispatcher lands on map 81
  6. the dispatcher uses a 回城卷: that disbands the team (user-verified), the members stay at the coast without a
     team (quest 78 needs none); only if one still shows the team after 5 s does the dispatcher leave it once
A member that did not arrive is left in the village without a team and is queued again by its phase. Restart at any
point continues from the observed state (dispatcher on map 81 -> straight to step 6).
Decisions are pure (tests/test_factory_transport.py).

PP鸡 facts: NPC id, position, the two menu labels and the 190 fee come from the old Codex runs
(pp_runtime/data.json, mwxqll pipeline stage 11); re-checked live by this stage.
"""
import json
import math
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from provisioner import log, native, procs
from provisioner.game import Game, NotSent
from provisioner.memory import ProcessMemory
from provisioner.world import read_bag, read_gold, read_invite_byte, read_level, read_team, read_world

from . import db
from .config import ROOT, load_settings
from .gold import GoldJob
from .observe import observe
from .phase import COAST_MAP, DISPATCHER, QUEUE_TRANSPORT, TELEPORT_FEE, VILLAGE_MAP, derive_phase
from .runner import ROLE_NAME
from .welltrain import Home, decide_leader_return, scroll_slot
from .wellteam import ACTION_INVITE, SPAWN, Join, decide_leader, decide_member, pick

PP_NPC = 11                     # 传送操作员3号
PP_POINT = (342, 315)           # where the old runs stood to click it (map 1)
PP_RANGE = 150                  # dispatcher this close to PP_POINT counts as there (old guard: 175)
SERVICE_LABEL = '传送服务'
COAST_LABEL = re.compile(r'平静海岸(2|二)区')
FOLLOW_RANGE = 250              # member this close to the dispatcher counts as caught up
FOLLOW_WAIT = 20.0              # at the NPC, wait this long for members still walking
NAV_RETRY = 2.0
STALL = 6.0
SETTLE = 0.4
CLICK_WAIT = 5.0                # the menu must open within this long after clicking
MAX_CLICKS = 3
SELECT_RETRY = 3.0              # same menu still open this long after selecting -> select again
TELEPORT_WAIT = 10.0            # map must change this long after choosing the destination
LEAVE_WAIT = 5.0
INVITE_GAP = 0.3


@dataclass(frozen=True)
class Decision:
    kind: str
    reason: str
    arg: object = None


# ---- the trip to the PP鸡 (dispatcher) -------------------------------------------------------------------

@dataclass
class Trip:
    last_nav: float = -1e9
    progress_xy: tuple | None = None
    progress_at: float = 0.0
    at_npc_since: float | None = None
    clicked_at: float | None = None
    clicks: int = 0
    last_select: float = -1e9
    dest_at: float | None = None     # destination chosen (fee paid if the server accepted it)

    def observe(self, w, now):
        if w is None:
            return
        if self.progress_xy is None or math.dist((w.x, w.y), self.progress_xy) > 15:
            self.progress_xy, self.progress_at = (w.x, w.y), now
        near = w.map_id == VILLAGE_MAP and math.dist((w.x, w.y), PP_POINT) <= PP_RANGE
        if near and self.at_npc_since is None:
            self.at_npc_since = now
        elif not near:
            self.at_npc_since = None

    def record(self, d, w, now):
        if d.kind == 'navigate':
            self.last_nav, self.progress_xy, self.progress_at = now, (w.x, w.y), now
        elif d.kind == 'cancel_nav':
            self.last_nav = -1e9
        elif d.kind == 'click':
            self.clicked_at, self.clicks = now, self.clicks + 1
        elif d.kind == 'select':
            self.last_select = now
        elif d.kind == 'destination':
            self.last_select = self.dest_at = now


def behind(w, member_worlds):
    """Members not yet next to the dispatcher on the same map (None = unreadable counts as behind)."""
    return sum(1 for m in member_worlds
               if m is None or m.map_id != w.map_id or math.dist((m.x, m.y), (w.x, w.y)) > FOLLOW_RANGE)


def decide_trip(w, member_worlds, memo, now):
    """Dispatcher in the village with its team. 'arrived' | 'wait' | 'navigate' | 'cancel_nav' | 'click' |
    'select' (menu 1) | 'destination' (menu 2, pays the fee) | 'fail'."""
    if w is None:
        return Decision('wait', '调度员加载中')
    if w.map_id == COAST_MAP:
        return Decision('arrived', '调度员已到平静海岸2区')
    if w.map_id != VILLAGE_MAP:
        return Decision('fail', f'调度员在意外的地图 {w.map_id}')
    if memo.dest_at is not None and now - memo.dest_at >= TELEPORT_WAIT and not w.dialog:
        return Decision('fail', f'选了平静海岸2区 {TELEPORT_WAIT:.0f}s 后仍在逍遥村西区')
    if w.verification:
        return Decision('wait', '调度员验证码弹窗，等待答题')
    if w.in_battle or w.busy:
        return Decision('wait', f'调度员忙/战斗中 flags={w.flags:#x}')
    if w.dialog:
        options = [(i, label) for i, label in w.dialog.options if i]
        coast = [(i, label) for i, label in options if COAST_LABEL.search(label)]
        service = [(i, label) for i, label in options if SERVICE_LABEL in label]
        if len(coast) == 1:
            if memo.dest_at is not None:
                if now - memo.dest_at < SELECT_RETRY:
                    return Decision('wait', '已选平静海岸2区，等传送')
                return Decision('fail', f'选了平静海岸2区后菜单还在: {w.dialog.options}')
            return Decision('destination', f'选择「{coast[0][1]}」', coast[0][0])
        if len(service) == 1:
            if now - memo.last_select < SELECT_RETRY:
                return Decision('wait', '已选传送服务，等第二层菜单')
            return Decision('select', f'选择「{service[0][1]}」', service[0][0])
        return Decision('fail', f'PP 鸡对话框选项不认识: {w.dialog.options}')
    if memo.dest_at is not None:
        return Decision('wait', '已选平静海岸2区，等传送')
    distance = math.dist((w.x, w.y), PP_POINT)
    if distance > PP_RANGE:
        if w.nav_active or w.moving:
            if now - memo.progress_at > STALL:
                return Decision('cancel_nav', f'{STALL:.0f}s 没有移动，重新寻路')
            return Decision('wait', '走向 PP 鸡')
        if now - memo.last_nav < NAV_RETRY:
            return Decision('wait', '等寻路开始')
        return Decision('navigate', f'寻路去 PP 鸡（距离 {distance:.0f}）', (VILLAGE_MAP, *PP_POINT))
    if w.nav_active:
        return Decision('cancel_nav', '到 PP 鸡旁边，停止寻路')
    if memo.clicked_at is not None and now - memo.clicked_at < CLICK_WAIT:
        return Decision('wait', '已点 PP 鸡，等菜单')
    if memo.clicks >= MAX_CLICKS:
        return Decision('fail', f'点了 {memo.clicks} 次 PP 鸡都没出菜单')
    if w.moving or w.still_for < SETTLE:
        return Decision('wait', '在 PP 鸡旁站稳')
    late = behind(w, member_worlds)
    if late and memo.at_npc_since is not None and now - memo.at_npc_since < FOLLOW_WAIT:
        return Decision('wait', f'等 {late} 个队员跟上')
    return Decision('click', f'点 PP 鸡 NPC {PP_NPC}' + (f'（{late} 个队员没跟上）' if late else ''), PP_NPC)


# ---- after the teleport (members) -------------------------------------------------------------------------

def decide_disband(still_in, home_at, leave_at, now):
    """After the dispatcher's 回城卷 (which disbands the team, user-verified): members still showing the
    dispatcher as their leader. 'done' | 'wait' | 'leave' (the dispatcher leaves/disbands, once) | 'fail'."""
    if not still_in:
        return Decision('done', '队伍已解散')
    if leave_at is None:
        if now - home_at < LEAVE_WAIT:
            return Decision('wait', f'回城后等队伍解散（还有 {still_in} 人）')
        return Decision('leave', f'回城 {LEAVE_WAIT:.0f}s 后还有 {still_in} 人在队里，调度员退队')
    if now - leave_at < LEAVE_WAIT:
        return Decision('wait', f'调度员已退队，等名单更新（还有 {still_in} 人）')
    return Decision('fail', f'调度员回城并退队后还有 {still_in} 人在队里')


# ---- the run -----------------------------------------------------------------------------------------------

class Member:
    def __init__(self, client, account, slot, mem):
        self.c, self.account, self.slot, self.mem = client, account, slot, mem
        self.game = Game(client.session, mem)
        self.join = Join()
        self.state = 'joining'          # joining -> ready -> done | dropped
        self.error = None
        self.last_reason = None
        self.log = log.for_account(client.name)

    def say(self, d):
        if d.reason != self.last_reason:
            self.log.info('%s', d.reason)
        self.last_reason = d.reason


class TransportRun:
    def __init__(self, conn, station, disp, disp_mem, alts, settings, logger):
        self.conn, self.station, self.disp, self.dmem = conn, station, disp, disp_mem
        self.alts, self.s, self.log = alts, settings, logger     # alts: {char_id: (client, account, slot)}
        self.dgame = Game(disp.session, disp_mem)
        self.members, self.mems = {}, []
        self.trip, self.home = Trip(), Home()
        self.last_reason = None
        self.started = time.monotonic()

    def close(self):
        for m in self.members.values():
            m.game.close()
        self.dgame.close()
        for mem in self.mems:
            mem.close()

    def say(self, d):
        if d.reason != self.last_reason:
            self.log.info('%s', d.reason)
        self.last_reason = d.reason

    def sid(self):
        return self.station['station_id']

    def check(self):
        if time.monotonic() - self.started > self.s.transport_timeout:
            raise RuntimeError(f'{self.s.transport_timeout:.0f}s 内没有完成')
        if not native.alive(self.disp.session.pid):
            raise RuntimeError(f'调度员游戏进程 {self.disp.session.pid} 已退出')
        for m in self.active():
            if not native.alive(m.c.session.pid):
                self.drop(m, '游戏进程已退出')
        db.renew(self.conn, self.sid(), self.s.transport_lease, time.time())

    def active(self):
        return [m for m in self.members.values() if m.state != 'dropped']

    def drop(self, m, error):
        m.state, m.error = 'dropped', error
        m.log.error('移出本批: %s', error)
        db.release(self.conn, self.sid(), [m.c.char_id], time.time())

    def add_members(self, cids):
        for cid in cids:
            c, account, slot = self.alts[cid]
            mem = ProcessMemory(c.session.pid, c.session.base)
            self.mems.append(mem)
            self.members[cid] = Member(c, account, slot, mem)

    def claim(self, cids):
        got = db.claim(self.conn, self.sid(), cids, self.s.transport_lease, time.time())
        for cid in set(cids) - set(got):
            self.log.warning('%s 被别的工位占着或已隔离，本批不管它', self.alts[cid][0].name)
        return [cid for cid in cids if cid in got]

    # ---- 1-2: rendezvous and choosing
    def to_rendezvous(self):
        last = None
        while True:
            self.check()
            world, team = read_world(self.dmem), read_team(self.dmem)
            d = decide_leader(world, team, self.disp.char_id, set(self.alts), world.still_for if world else 0)
            if d.reason != last:
                self.log.info('%s', d.reason.replace('队长', '调度员'))
            last = d.reason
            if d.kind == 'fail':
                raise RuntimeError(d.reason.replace('队长', '调度员'))
            if d.kind == 'ready':
                return team
            if d.kind == 'walk':
                self.dgame.navigate(VILLAGE_MAP, *SPAWN)
                time.sleep(0.5)
            time.sleep(self.s.tick)

    def choose(self, team):
        roles = db.station_roles(self.conn)
        now = time.time()
        for cid, (c, account, slot) in self.alts.items():
            db.register_alt(self.conn, cid, account, slot, c.name, now)
            try:
                with ProcessMemory(c.session.pid, c.session.base) as mem:
                    obs = observe(mem, read_world(mem))
            except OSError:
                obs = None      # the window closed meanwhile (live 2026-10-13 04:19: WinError 87 stopped the well leader)
            if obs is None:
                self.log.info('%s 读不到状态，这次不选', c.name)
                continue
            plan = derive_phase(obs, db.ledger(self.conn, cid), roles)
            db.save_observation(self.conn, obs, plan, now)
            self.log.info('%s: %d 级 金币 %s 阶段=%s（%s）', c.name, obs.level, obs.gold, plan.phase, plan.reason)
        adopted = [cid for cid in team.members if cid in self.alts]
        waiting = [r['char_id'] for r in db.waiting(self.conn, QUEUE_TRANSPORT, time.time()) if r['char_id'] in self.alts]
        return self.claim(adopted + pick(waiting, adopted, self.s.transport_team_size))

    # ---- 3: gold
    def fund(self):
        for m in self.active():
            gold = read_gold(m.mem)
            if gold is not None and gold >= self.s.gold_topup_below:
                continue
            m.log.info('金币 %s 低于 %d，先补金币', gold, self.s.gold_topup_below)
            r = GoldJob(self.conn, self.disp, self.dmem, self.dgame, m.c, m.account, m.slot, self.s, m.log).run()
            gold = read_gold(m.mem)
            if gold is None or gold < TELEPORT_FEE:
                self.drop(m, f'补金币失败（{r.get("error")}），金币 {gold} 不够传送费 {TELEPORT_FEE}')
            self.check()

    # ---- 4: team
    def form(self):
        level, invite_byte = read_level(self.dmem), read_invite_byte(self.dmem)
        last_invite = 0.0
        while any(m.state == 'joining' for m in self.active()):
            self.check()
            now = time.monotonic()
            dw, dteam = read_world(self.dmem), read_team(self.dmem)
            for m in self.active():
                if m.state != 'joining':
                    continue
                world, team = read_world(m.mem), read_team(m.mem)
                if world and world.char_id != m.c.char_id:
                    raise RuntimeError(f'{m.c.name} 角色变了')
                d = decide_member(m.c.char_id, world, team, self.disp.char_id, dw, dteam, m.join, now)
                m.say(d)
                if d.kind == 'joined':
                    m.state = 'ready'
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
                        self.dgame.team_invite(m.c.char_id, level, invite_byte, self.disp.name)
                    except NotSent as e:
                        db.clear_pending(self.conn, m.c.char_id, time.time(), str(e))
                        raise RuntimeError(f'调度员的邀请没发出: {e}') from e
                    m.join.invited_at = last_invite = time.monotonic()
                elif d.kind == 'accept':
                    try:
                        m.game.team_accept()
                    except NotSent as e:
                        self.drop(m, f'接受邀请没发出: {e}')
                        continue
                    m.join.accepted_at = time.monotonic()
            time.sleep(self.s.tick)

    # ---- 5: PP鸡
    def travel(self):
        while True:
            self.check()
            now = time.monotonic()
            w = read_world(self.dmem)
            self.trip.observe(w, now)
            d = decide_trip(w, [read_world(m.mem) for m in self.active()], self.trip, now)
            self.say(d)
            if d.kind == 'arrived':
                return
            if d.kind == 'fail':
                raise RuntimeError(d.reason)
            if d.kind == 'navigate':
                self.dgame.navigate(*d.arg)
            elif d.kind == 'cancel_nav':
                self.dgame.cancel_navigation()
            elif d.kind == 'click':
                self.dgame.click_npc(d.arg)
            elif d.kind in ('select', 'destination'):
                if d.kind == 'destination':
                    db.log_event(self.conn, time.time(), 'teleport', d.reason, station_id=self.sid())
                self.dgame.select_dialog(d.arg)
            if d.kind != 'wait':
                self.trip.record(d, w, now)
            time.sleep(self.s.tick)

    # ---- 6: members leave, dispatcher goes home
    def disband_and_return(self):
        """The dispatcher's 回城卷 disbands the team (members stay where they are); no member requests.
        Fallback only if someone still shows the dispatcher as leader: the dispatcher leaves the team once."""
        while True:
            self.check()
            now = time.monotonic()
            d = decide_leader_return(read_world(self.dmem), scroll_slot(read_bag(self.dmem)), self.home, now)
            self.say(Decision(d.kind, d.reason.replace('队长', '调度员')))
            if d.kind == 'done':
                break
            if d.kind == 'fail':
                raise RuntimeError(d.reason.replace('队长', '调度员'))
            if d.kind == 'unconfirmed':
                self.home.tried.add(f'scroll{len(self.home.tried)}')
                self.home.sent_at = None
            elif d.kind == 'cancel_nav':
                self.dgame.cancel_navigation()
            elif d.kind == 'scroll':
                self.dgame.use_item(d.arg)
                self.home.sent_at = now
            time.sleep(self.s.tick)
        home_at, leave_at = time.monotonic(), None
        while True:
            self.check()
            now = time.monotonic()
            still = []
            for m in self.active():
                team = read_team(m.mem)
                if team is None or (team.members and team.leader == self.disp.char_id):
                    still.append(m)
                elif m.state != 'done':
                    m.state = 'done'
                    w = read_world(m.mem)
                    m.say(Decision('done', '已在平静海岸2区，队伍已解散' if w and w.map_id == COAST_MAP
                                   else f'没传过去（地图 {w.map_id if w else "?"}），队伍已解散'))
            d = decide_disband(len(still), home_at, leave_at, now)
            self.say(d)
            if d.kind == 'done':
                return
            if d.kind == 'fail':
                for m in still:
                    self.drop(m, d.reason)
                return
            if d.kind == 'leave':
                try:
                    self.dgame.team_leave()
                except NotSent as e:
                    self.log.warning('调度员退队请求没发出: %s', e)
                leave_at = now
            time.sleep(self.s.tick)

    def run(self):
        w, team = read_world(self.dmem), read_team(self.dmem)
        if w is None or team is None:
            raise RuntimeError('读不到调度员的状态')
        if w.map_id == COAST_MAP:
            self.log.info('调度员已在平静海岸2区（上次中断），直接回城（队伍随之解散）')
            self.add_members(self.claim([cid for cid in team.members if cid in self.alts]))
        else:
            team = self.to_rendezvous()
            self.add_members(self.choose(team))
            if not self.members:
                self.log.info('没有排传送队列的小号，本批不传送')
                return []
            self.log.info('本批 %d 人: %s', len(self.members), ', '.join(m.c.name for m in self.members.values()))
            self.fund()
            self.form()
            if not [m for m in self.active() if m.state == 'ready']:
                raise RuntimeError('没有队员入队，不传送')
            self.travel()
        self.disband_and_return()
        return self.summary()

    def summary(self):
        roles, now = db.station_roles(self.conn), time.time()
        results = []
        for m in self.members.values():
            obs = observe(m.mem, read_world(m.mem))
            if obs is not None:
                db.save_observation(self.conn, obs, derive_phase(obs, db.ledger(self.conn, m.c.char_id), roles), now)
            ok = m.state == 'done' and obs is not None and obs.map_id == COAST_MAP and not obs.team_leader
            results.append({'name': m.c.name, 'char_id': m.c.char_id, 'ok': ok,
                            'map': obs.map_id if obs else None, 'gold': obs.gold if obs else None,
                            'phase': db.alt(self.conn, m.c.char_id)['phase'], 'error': m.error})
        db.release(self.conn, self.sid(), list(self.members), now)
        self.log.info('调度员金币 %s，用时 %.1fs', read_gold(self.dmem), time.monotonic() - self.started)
        db.log_event(self.conn, now, 'transport', f'传送完成 {[r["name"] for r in results if r["ok"]]}',
                     station_id=self.sid())
        return results


def main():
    settings = load_settings(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'factory.toml')
    log_path = log.setup(ROOT / 'logs', prefix='transport')
    logger = log.for_account('main')
    logger.info('日志文件: %s', log_path)
    conn = db.connect(settings.db_path)
    stations = conn.execute('SELECT * FROM stations WHERE role=?', (DISPATCHER,)).fetchall()
    if len(stations) != 1:
        logger.error('数据库里的调度员应正好 1 个，实际 %d 个；先运行 一键登录工位.cmd', len(stations))
        return 2
    station = stations[0]
    clients = {c.char_id: c for c in procs.discover(logger)}
    disp = clients.pop(station['char_id'], None)
    if disp is None:
        logger.error('调度员 %s (ID=%d) 不在本工具的窗口里在线；先运行 一键登录工位.cmd', station['name'],
                     station['char_id'])
        return 2
    logger.info('调度员: %s pid=%d 地图 %d 坐标=(%.0f,%.0f)', disp.name, disp.session.pid, disp.map_id, disp.x, disp.y)
    alts = {}
    for c in clients.values():
        m = ROLE_NAME.match(c.name)
        if m and c.map_id in (VILLAGE_MAP, COAST_MAP):
            alts[c.char_id] = (c, m.group(1), int(m.group(2)))
        else:
            logger.info('%s 不是在逍遥村西区/平静海岸2区的小号，跳过', c.name)
    results, ok_run = [], False
    with ProcessMemory(disp.session.pid, disp.session.base) as disp_mem:
        run = TransportRun(conn, station, disp, disp_mem, alts, settings, logger)
        try:
            results = run.run()
            ok_run = True
        except Exception as e:
            logger.error('失败: %s', e, exc_info=not isinstance(e, RuntimeError))
            results = [{'name': disp.name, 'ok': False, 'error': f'{type(e).__name__}: {e}'}]
        finally:
            run.close()
    conn.close()
    out = ROOT / 'logs' / (log_path.stem.replace('transport_', 'transport_summary_') + '.json')
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), 'utf-8')
    logger.info('=' * 60)
    for r in results:
        logger.info('%-8s %s 地图=%s 金币=%s 阶段=%s %s', r['name'], '到达' if r['ok'] else '失败', r.get('map'),
                    r.get('gold'), r.get('phase'), r.get('error') or '')
    ok = sum(r['ok'] for r in results)
    logger.info('到达 %d/%d。汇总: %s', ok, len(results), out)
    return 0 if ok_run and ok == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
