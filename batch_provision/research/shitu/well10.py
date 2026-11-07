"""师徒 leveling, 1 -> 10 in 阴森古井 (651): the apprentice 十万1 leads 十万2, 十万3, 伏地魔1, 伏地魔2.

    python -X utf8 research/shitu/well10.py [target level, default 10]

User's orders (2026-10-27): 十万1 = leader with the other four in its team; on arrival in the well every apprentice
eats both (御)加钙地瓜 32004, one (御)小酒池 30187 and one (御)小肉林 30188; all talent points go to 体质 at every
level; stop (in the well) once every apprentice is at the target level and wait for the next order.
Every tick decides from what is read, so a restart continues:
  team     十万1 invites whoever is not in its team yet (0x30), they accept
  route    factory.welltrain.decide_route: village -> 夕阳草原 entrance -> NPC 10152 -> 651 -> patrol A <-> B
  battle   the masters cast like lunhui15 (pet 烈焰爆发, 2026-10-30: the client's 战斗辅助 is off after a relog);
           the apprentices send nothing (user 2026-11-05: they had normal-attacked here since 10-27 and, unequipped
           with the fastest charge, acted first; every other map already leaves them out); their pets are left alone
  talent   welltrain.decide_talent -> 0x0070 all points on 体质 (apprentices only)
  eat      in 651, out of battle, one item at a time; done items go to state.json (the bag count is the proof)
No UI clicks (game functions via DLL command 106).
"""
import math
import os
import sys
import time

import trial_run as t
from bai_shi import done, mark
from factory.phase import WELL_MAP
from factory.welltrain import Route, Talent, decide_route, decide_talent
from provisioner import world as w

from common import APPRENTICES, MASTERS, TALENT_STAT  # noqa: E402
LEADER = APPRENTICES[0]
HELPERS = MASTERS
PATROL = ((2214, 1653), (1000, 260))           # factory.toml well_patrol
EAT = ((32004, '加钙地瓜', 2), (30187, '小酒池', 1), (30188, '小肉林', 1))
if os.environ.get('SHITU_STATE', '').startswith('state_r4'):     # user 2026-10-28: no 地瓜 at the start; 3 小时 at
    EAT = EAT[1:]                                                 # 散福老人 right after the 10 级 转职 instead
EAT_WAIT = 5.0
TICK = 0.15
INVITE_RANGE = 150      # px; ~150 worked, ~270 refused


class Eater:
    """One apprentice's eating list: [(item, name, n-th)] still to eat; a request is confirmed by the bag count."""

    def __init__(self, c):
        self.c, self.sent = c, None
        self.todo = [(i, n, k) for i, n, cnt in EAT for k in range(1, cnt + 1) if not done(c.name, f'eat_{i}_{k}')]

    def tick(self, st, now):
        if not self.todo or st.map_id != WELL_MAP or st.in_battle or st.busy or st.verification:
            return
        item, name, k = self.todo[0]
        bag = w.read_bag(self.c.mem) or ()
        count = w.item_count(bag, item)
        if self.sent:
            if count < self.sent[1]:
                t.say(f'[{self.c.name}] 吃了第 {k} 个{name}（{self.sent[1]} -> {count}）')
                mark(self.c.name, f'eat_{item}_{k}', item=item)
                self.todo.pop(0)
                self.sent = None
            elif now - self.sent[0] > EAT_WAIT:
                raise t.Stop(f'{self.c.name} 吃{name} {EAT_WAIT:.0f}s 后数量没变（{count}）')
            return
        slot = next((s.slot for s in bag if s.item_id == item), None)
        if slot is None:
            raise t.Stop(f'{self.c.name} 背包里没有{name}，还要吃第 {k} 个')
        t.say(f'[{self.c.name}] 吃{name}（背包第 {slot} 格，现有 {count}）')
        self.c.game.use_item(slot)
        self.sent = (now, count)


def invite_near(lead, others):
    """Every member already next to the leader (same map, within INVITE_RANGE) is invited at once, then all accept
    (user 2026-11-01: a leader can have 4 invites out at the same time); one at a time cost ~1.5-2 s apiece. Whoever
    is not in after this goes through form_team's one-by-one path as before."""
    ls = lead.world()
    near = []
    for c in others:
        if c.char_id in lead.team() or c.team():
            continue
        s = c.world()
        if s and s.map_id == ls.map_id and math.dist((ls.x, ls.y), (s.x, s.y)) <= INVITE_RANGE and not s.in_battle:
            near.append(c)
    if len(near) < 2:
        return
    for c in near:
        lead.game.team_invite(c.char_id, w.read_level(lead.mem), w.read_invite_byte(lead.mem), lead.name)
    for c in near:
        try:
            t.wait(lambda: w.read_team(c.mem).inviter == lead.char_id, 5, f'{c.name} 收到邀请')
        except t.Stop:
            pass
    time.sleep(1.5)                    # the inviter field can be stale (see form_team): the invite must land first;
                                       # teamwalk.regroup waits 1.5 s for the same reason (round 3), once for all here
    for c in near:
        c.game.team_accept()
    try:
        t.wait(lambda: all(c.char_id in lead.team() for c in near), 3, '同时邀请的人入队')
    except t.Stop:
        pass
    t.say(f'[{lead.name}] 同时邀请 {[c.name for c in near]}，进队 '
          f'{[c.name for c in near if c.char_id in lead.team()]}')


def form_team(lead, others):
    """Leader invites every one not yet in its team; returns True when all are in."""
    team = lead.team()
    if team and team[0] != lead.char_id:
        raise t.Stop(f'{lead.name} 在别人的队里 {team}')
    invite_near(lead, others)
    for c in others:
        if c.char_id in lead.team():
            continue
        if c.team():
            t.say(f'[{c.name}] 先离开现在的队伍 {c.team()}')
            c.game.team_leave()
            t.wait(lambda: not c.team(), 5, f'{c.name} 离队')
        ls, cst = lead.world(), c.world()
        if ls.map_id != cst.map_id:
            # 2026-10-28 (user): apprentices left at an NPC on another map walked back one by one after 3 lost
            # accepts each (~40 s apiece); a 回城卷 puts them on the leader in 逍遥村 at once
            if ls.map_id == 1:
                from quanshou import scroll
                t.say(f'[{c.name}] 在地图 {cst.map_id}，师傅在逍遥村：直接用回城卷')
                scroll(c)
            else:
                import teamwalk
                t.say(f'[{c.name}] 在地图 {cst.map_id}，师傅在地图 {ls.map_id}：走到师傅脚下再邀请')
                teamwalk.MAP = ls.map_id
                teamwalk.regroup(lead, [c])
                continue
            ls, cst = lead.world(), c.world()
        if ls.map_id == cst.map_id and math.dist((ls.x, ls.y), (cst.x, cst.y)) > INVITE_RANGE:
            # live 2026-10-27 01:39 at ~270 px: 0x46ff「你所邀请的对象与你距离太远，无法接受你的邀请」
            # round 3 13:09: an apprentice walking alone in 通天塔二区 met monsters and died -> the LEADER walks over
            t.say(f'[{lead.name}] 离 {c.name} {math.dist((ls.x, ls.y), (cst.x, cst.y)):.0f} px，师傅走过去')
            from lunhui15 import Caster                # lazy: lunhui15 imports this module
            caster, end = Caster(lead), time.monotonic() + 180
            lead.game.navigate(cst.map_id, round(cst.x), round(cst.y))
            while True:                                # a battle on the way (13:11): the leader fights it, then walks on
                s = lead.world()
                if s.in_battle:
                    caster.tick(time.monotonic())
                elif math.dist((s.x, s.y), (cst.x, cst.y)) <= INVITE_RANGE - 30 and not s.moving:
                    break
                elif not s.nav_active and not s.moving:
                    caster.reset()
                    lead.game.navigate(cst.map_id, round(cst.x), round(cst.y))
                if time.monotonic() > end:
                    raise t.Stop(f'{lead.name} 180s 没走到 {c.name} 旁')
                time.sleep(0.03 if s.in_battle else 0.15)  # lunhui15.BATTLE_TICK while fighting (user 2026-11-05)
            t.wait(lambda: not c.world().in_battle, 120, f'{c.name} 战斗结束')
        t.say(f'[{lead.name}] 邀请 {c.name} 入队')
        lead.game.team_invite(c.char_id, w.read_level(lead.mem), w.read_invite_byte(lead.mem), lead.name)
        t.wait(lambda: w.read_team(c.mem).inviter == lead.char_id, 5, f'{c.name} 收到邀请')
        # the inviter field keeps the LAST inviter, so it can already read lead before this invite arrives
        # (live 2026-10-27 00:51: 0x31 went out 47 ms before the 0x4704 invite and was lost): wait, then retry
        for attempt in range(1):       # round 4 logs: 96 first accepts failed, the 2nd / 3rd never once helped
            time.sleep(0.5)
            c.game.team_accept()
            try:
                t.wait(lambda: c.char_id in lead.team(), 2, f'{c.name} 入队')
                break
            except t.Stop:
                t.say(f'[{c.name}] 第 {attempt + 1} 次接受后还没进队')
        else:
            # round 4 00:3x (4 teams at 无尽2路口): 3 accepts lost; teamwalk.regroup = the apprentice walks onto the
            # leader, a fresh invite, accept 1.5 s later (the round-3 cure for「旧邀请人」/ obstacles)
            t.say(f'[{c.name}] 接受后没进队，改用 regroup（走到师傅脚下再邀请）')
            import teamwalk
            teamwalk.MAP = lead.world().map_id
            teamwalk.regroup(lead, [c])
    t.say(f'[{lead.name}] 队伍 {lead.team()}')


WRENCH, WEAPON_SLOT, UNARM_LEVEL = 118, 2, 2     # 专打屁屁扳手 (every new role wears it), world.py equipment row 2


class Unarm:
    """User 2026-11-04: from level 2 the apprentices fight bare-handed (no gear = a much shorter 蓄力), so the 专打屁屁扳手
    every new role starts with comes off into a free bag slot, out of battle, once. Checked on the worn list; tried
    again after RETRY s, given up after TRIES (logged, the well goes on)."""
    RETRY, TRIES = 5.0, 3

    def __init__(self, c):
        self.c, self.done, self.tries, self.sent_at = c, False, 0, None

    def tick(self, st, level, now):
        if self.done or level < UNARM_LEVEL or st.in_battle:
            return
        worn = w.read_equipment(self.c.mem) or ()
        if not any(e.slot == WEAPON_SLOT and e.item_id == WRENCH for e in worn):
            if self.sent_at is not None:
                t.say(f'[{self.c.name}] {level} 级，脱下专打屁屁扳手')
            self.done = True
            return
        if self.sent_at is not None and now - self.sent_at < self.RETRY:
            return
        if self.tries >= self.TRIES:
            t.say(f'[{self.c.name}] 脱专打屁屁扳手 {self.TRIES} 次都没成，先不管')
            self.done = True
            return
        used = {s.slot for s in w.read_bag(self.c.mem)}
        free = next((i for i in range(w.read_bag_capacity(self.c.mem)) if i not in used), None)
        if free is None:
            t.say(f'[{self.c.name}] 背包没有空格，脱不下专打屁屁扳手')
            self.done = True
            return
        self.c.game.unequip(WEAPON_SLOT, free)
        self.sent_at, self.tries = now, self.tries + 1


def main(target):
    cs = {n: t.Client(n) for n in APPRENTICES + HELPERS}
    lead = cs[LEADER]
    for n, c in cs.items():
        t.say(f'[{n}] pid {c.pid} char {c.char_id} 等级 {w.read_level(c.mem)} 天赋 {w.read_talent_points(c.mem)}')
    form_team(lead, [cs[n] for n in APPRENTICES + HELPERS if n != LEADER])
    route = Route()
    # 2026-10-30 user: in the well the masters' pets did not cast 烈焰爆发 unless the client's own 战斗辅助 was ticked
    # (a relogged client has it off). The masters now fight like in every other leveling step: lunhui15.Caster
    # (pet 1504, skill 803 if learned, else normal attack); the apprentices keep the plain attack.
    from lunhui15 import Caster                # lazy: lunhui15 imports this module
    casters = {n: Caster(cs[n]) for n in HELPERS}
    talents, eaters = {n: Talent() for n in APPRENTICES}, {n: Eater(cs[n]) for n in APPRENTICES}
    unarms = {n: Unarm(cs[n]) for n in APPRENTICES}
    battles, in_battle, last_reason, last_levels = 0, False, None, None
    gone = t.Gone()                      # a dropped client: fail after 30 s, not the 15-min watchdog (2026-11-05)
    stuck = t.StuckBattle(cs, LEADER)    # a client frozen in an old battle: close it, Stop (2026-11-07)
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
        stuck.tick(sts, battles)
        levels = {n: w.read_level(cs[n].mem) for n in APPRENTICES}
        if levels != last_levels:
            t.say(f'等级 {levels}，战斗 {battles} 场')
            last_levels = levels
        # talent (in battle too, like welltrain)
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
        for e in eaters.values():
            e.tick(sts[e.c.name], now)
        for n, u in unarms.items():
            u.tick(sts[n], levels[n], now)
        lw = sts[LEADER]
        if lw.in_battle != in_battle:
            in_battle = lw.in_battle
            battles += in_battle
        if not lw.in_battle and all(v >= target for v in levels.values()) \
                and not any(e.todo for e in eaters.values()):
            if lw.nav_active:
                lead.game.cancel_navigation()
            t.say(f'全部到 {target} 级 {levels}，共 {battles} 场；停在地图 {lw.map_id} ({lw.x:.0f},{lw.y:.0f})，等下一步')
            return
        # battle: the masters only (user 2026-11-05: the apprentices send nothing, as on every other map)
        for n in casters:
            if sts[n].in_battle:
                casters[n].tick(now)
            else:
                casters[n].reset()
        # route (leader)
        member_maps = [sts[n].map_id for n in cs if n != LEADER]
        route.observe(lw, now)
        d = decide_route(lw, member_maps, route, now, PATROL)
        if d.reason != last_reason and d.kind not in ('battle',):
            t.say(f'[{LEADER}] {d.reason}')
        last_reason = d.reason
        if d.kind == 'fail':
            raise t.Stop(d.reason)
        if d.kind == 'navigate':
            lead.game.navigate(*d.arg[:3])
        elif d.kind == 'cancel_nav':
            lead.game.cancel_navigation()
        elif d.kind == 'click':
            lead.game.click_npc(d.arg)
        elif d.kind == 'select':
            lead.game.select_dialog(d.arg)
        if d.kind in ('navigate', 'cancel_nav', 'click', 'select'):
            route.record(d, lw, now)
        time.sleep(0.03 if any(x.in_battle for x in sts.values()) else TICK)  # lunhui15.BATTLE_TICK (user 2026-11-05)


if __name__ == '__main__':
    try:
        main(int(sys.argv[1]) if len(sys.argv) > 1 else 10)
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
