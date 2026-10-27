"""师徒 leveling, 1 -> 10 in 阴森古井 (651): the apprentice 十万1 leads 十万2, 十万3, 伏地魔1, 伏地魔2.

    python -X utf8 research/shitu/well10.py [target level, default 10]

User's orders (2026-10-27): 十万1 = leader with the other four in its team; on arrival in the well every apprentice
eats both (御)加钙地瓜 32004, one (御)小酒池 30187 and one (御)小肉林 30188; all talent points go to 体质 at every
level; stop (in the well) once every apprentice is at the target level and wait for the next order.
Every tick decides from what is read, so a restart continues:
  team     十万1 invites whoever is not in its team yet (0x30), they accept
  route    factory.welltrain.decide_route: village -> 夕阳草原 entrance -> NPC 10152 -> 651 -> patrol A <-> B
  battle   every member normal-attacks the first live enemy whenever its SP changes (welltrain.decide_fighter);
           pets are left alone
  talent   welltrain.decide_talent -> 0x0070 all points on 体质 (apprentices only)
  eat      in 651, out of battle, one item at a time; done items go to state.json (the bag count is the proof)
No UI clicks (game functions via DLL command 106).
"""
import math
import sys
import time

import trial_run as t
from bai_shi import done, mark
from factory.phase import WELL_MAP
from factory.welltrain import Fight, Route, Talent, decide_fighter, decide_route, decide_talent
from provisioner.game import FIGHT_ATTACK
from provisioner import world as w

from common import APPRENTICES, MASTERS  # noqa: E402
LEADER = APPRENTICES[0]
HELPERS = MASTERS
PATROL = ((2214, 1653), (1000, 260))           # factory.toml well_patrol
EAT = ((32004, '加钙地瓜', 2), (30187, '小酒池', 1), (30188, '小肉林', 1))
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


def form_team(lead, others):
    """Leader invites every one not yet in its team; returns True when all are in."""
    team = lead.team()
    if team and team[0] != lead.char_id:
        raise t.Stop(f'{lead.name} 在别人的队里 {team}')
    for c in others:
        if c.char_id in lead.team():
            continue
        if c.team():
            t.say(f'[{c.name}] 先离开现在的队伍 {c.team()}')
            c.game.team_leave()
            t.wait(lambda: not c.team(), 5, f'{c.name} 离队')
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
                time.sleep(0.15)
            t.wait(lambda: not c.world().in_battle, 120, f'{c.name} 战斗结束')
        t.say(f'[{lead.name}] 邀请 {c.name} 入队')
        lead.game.team_invite(c.char_id, w.read_level(lead.mem), w.read_invite_byte(lead.mem), lead.name)
        t.wait(lambda: w.read_team(c.mem).inviter == lead.char_id, 5, f'{c.name} 收到邀请')
        # the inviter field keeps the LAST inviter, so it can already read lead before this invite arrives
        # (live 2026-10-27 00:51: 0x31 went out 47 ms before the 0x4704 invite and was lost): wait, then retry
        for attempt in range(3):
            time.sleep(0.5)
            c.game.team_accept()
            try:
                t.wait(lambda: c.char_id in lead.team(), 2, f'{c.name} 入队')
                break
            except t.Stop:
                t.say(f'[{c.name}] 第 {attempt + 1} 次接受后还没进队')
        else:
            raise t.Stop(f'{c.name} 接受 3 次邀请都没进队')
    t.say(f'[{lead.name}] 队伍 {lead.team()}')


def main(target):
    cs = {n: t.Client(n) for n in APPRENTICES + HELPERS}
    lead = cs[LEADER]
    for n, c in cs.items():
        t.say(f'[{n}] pid {c.pid} char {c.char_id} 等级 {w.read_level(c.mem)} 天赋 {w.read_talent_points(c.mem)}')
    form_team(lead, [cs[n] for n in APPRENTICES + HELPERS if n != LEADER])
    route, fights = Route(), {n: Fight() for n in cs}
    talents, eaters = {n: Talent() for n in APPRENTICES}, {n: Eater(cs[n]) for n in APPRENTICES}
    battles, in_battle, last_reason, last_levels = 0, False, None, None
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
            t.say(f'等级 {levels}，战斗 {battles} 场')
            last_levels = levels
        # talent (in battle too, like welltrain)
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
        for e in eaters.values():
            e.tick(sts[e.c.name], now)
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
        # battle: every member, normal attack
        for n, c in cs.items():
            if not sts[n].in_battle:
                fights[n] = Fight()
                continue
            b = w.read_battle(c.mem)
            if not b or not b.enemies:
                continue
            d = decide_fighter(b.me, fights[n], now, False, n)
            if d.kind == 'attack':
                c.game.fight_command(FIGHT_ATTACK, target=b.enemies[0])
                fights[n].record(b.me.sp, now)
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
        time.sleep(TICK)


if __name__ == '__main__':
    try:
        main(int(sys.argv[1]) if len(sys.argv) > 1 else 10)
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
