"""转职 task 24 step 3: kill 5 75kg级拳手 in 夕阳草原 (130) around (234,2583) (SubTask.csv) with the 5-man team.

    python -X utf8 research/shitu/quanshou.py

Apprentices scroll home first if they are not on map 1 / 130; then maze_train's loop (伏地魔1 leader, 扫射 + 烈焰爆发,
talent -> 体质) walks map 1 -> 130, patrols (234,2583) <-> a probed reachable point, and stops once every apprentice got the 0x46ff
「已经杀死了5个75Kg级拳手…」 (the quest tree stays (0,0,1) after the kills, 2026-10-27 02:00; round 2 reads the text). Then everybody uses a 回城卷 and the apprentices walk to 禁军教头 (NPC 304).
"""
import re
import time

import maze_train as m
import progress
from bai_shi import done, mark
from monitor import Tap, texts
from factory.phase import SCROLL_ITEM
from provisioner import world as w
from zhuanzhi_take import go
t = m.t

# set on maze_train only by main(): r4_util / teamwalk / tower1_go import scroll / flee from here, and an import-time
# m.STAGES = ... sent go_cave.py to 夕阳草原 (2026-10-28 C batch 2: 「在意外的地图 20」)
STAGES = (
    dict(name='夕阳草原 75kg级拳手', maze=130, until=None, patrol_a=(234, 2583), patrol_b=None,
         legs={1: ('walk', 130, (234, 2583))}),
)
KILLS = re.compile(r'杀死了(\d+)个75Kg级拳手', re.I)
COLOR = re.compile(r'#[0-9A-Fa-f]{6}#')


class Kills:
    """done_when of the stage: every apprentice's tap showed 「已经杀死了5个75Kg级拳手」 (colour codes stripped)."""
    PAST = (24, progress.CLASS_ITEMS + 1, 5)     # (quest, step count after the hand-in, the full count)

    def __init__(self, apps):
        self.taps = {c.name: Tap(c.pid, from_end=True) for c in apps}
        for tap in self.taps.values():
            tap.ready()
        self.count = {n: 5 if done(n, 'kills5') else 0 for n in self.taps}
        # 2026-11-07 (r4ys25 books, same pattern): an apprentice whose task is already past this step (handed in)
        # never gets the kill text again; without a kills5 mark (state lost / another machine) it would block the team
        qid, n_past, full = self.PAST
        for c in apps:
            if progress.past(w.read_quest(c.mem, qid), n_past):
                self.count[c.name] = max(self.count[c.name], full)
        # 2026-11-01 w6: the line was restarted seconds after the 5th kill, before the mark; the rerun waited 25 min
        # for a text that never comes again. The tap file holds this login's packets: read the kills already there
        for c in apps:
            if self.count[c.name] < 5:
                self.count[c.name] = max(self.count[c.name], self.seen(Tap(c.pid, from_end=False), c.name))

    @staticmethod
    def seen(tap, name):
        """Highest kill count in the 0x46ff texts already in the tap file (marks kills5 at 5)."""
        best = 0
        tap.ready()
        for _, d, op, body, _ in tap.poll():
            if d == 'S->C' and op == 0x46ff:
                k = KILLS.search(COLOR.sub('', ' '.join(texts(body))))
                if k:
                    best = max(best, int(k.group(1)))
        if best >= 5 and not done(name, 'kills5'):
            t.say(f'[{name}] 这次登录已经杀够 {best} 个 75Kg级拳手（之前的消息）')
            mark(name, 'kills5')
        return best

    def __call__(self):
        for n, tap in self.taps.items():
            for _, d, op, body, _ in tap.poll():
                if d == 'S->C' and op == 0x46ff:
                    text = COLOR.sub('', ' '.join(texts(body)))
                    k = KILLS.search(text)
                    if k:
                        self.count[n] = max(self.count[n], int(k.group(1)))
                        t.say(f'[{n}] {text}')
                        if self.count[n] >= 5 and not done(n, 'kills5'):
                            mark(n, 'kills5')        # a rerun must not wait for kills that never come again
        return all(v >= 5 for v in self.count.values())


def lenders(name, masters, apprentices):
    """Who may lend c 回城卷: a master asks its apprentices (2026-10-28), an apprentice asks the masters (2026-10-30
    Opus55A5-8: a well rerun had them scroll to the master in 逍遥村, the novices' only scrolls, so 转职's trip home
    stopped on「没有回城卷」five times; the master stood next to them with 98)."""
    if name in masters:
        return list(apprentices)
    if name in apprentices:
        return list(masters)
    return []


def borrow(c, k=5):
    """c has no 回城卷: take k from a lender (see lenders) on the same map within 600 px. -> True when it got them."""
    import math
    import supply_go
    from common import APPRENTICES, MASTERS
    st = c.world()
    for n in lenders(c.name, MASTERS, APPRENTICES):
        a = t.Client(n)
        s = a.world()
        bag = [x for x in w.read_bag(a.mem) if x.item_id == SCROLL_ITEM]
        if s.map_id != st.map_id or math.dist((s.x, s.y), (st.x, st.y)) > 600 or sum(x.quantity for x in bag) < k + 3:
            continue
        x = max(bag, key=lambda x: x.quantity)
        k = min(k, x.quantity)
        t.say(f'[{c.name}] 没有回城卷，向 {n} 借 {k} 张')
        try:
            supply_go.trade_until(a, c, (a.game.trade_offer_item, (x.slot, k)),
                                  lambda: supply_go.scrolls(c) >= k, f'{c.name} 回城卷 +{k}')
            return True
        except t.Stop as e:
            t.say(f'[{c.name}] 借回城卷没成: {e}')
    return False


def flee(c, timeout=120):
    """Out of a battle by running away (fight action 8), not by waiting: 2026-10-28 亿万12 sat alone in a 苦无沙漠
    battle while home() waited for it to end."""
    import teamwalk
    if not c.world().in_battle:
        return
    if c.team() and c.team()[0] != c.char_id:    # a team member: the leader's battle, its escape ends it for all
        t.wait(lambda: not c.world().in_battle, timeout, f'{c.name} 战斗结束')
        return
    e, end = teamwalk.Escaper(c), time.monotonic() + timeout
    while c.world().in_battle:
        if time.monotonic() > end:
            raise t.Stop(f'{c.name} {timeout}s 没逃出战斗')
        e.tick(time.monotonic())
        time.sleep(0.2)
    t.say(f'[{c.name}] 逃出战斗')


FETCH_NEAR, FETCH_WAIT = 150, 180      # px the master walks up to; s it may take (battles on the way included)
import threading                       # noqa: E402
_FETCH = threading.Lock()              # one master: one apprentice fetched at a time (home() runs them at once)


def _master_walks_to(c, mc):
    """Same map: the master walks over to c, casting in battles on the way. -> True when it got within FETCH_NEAR."""
    import math
    from lunhui15 import Caster          # lazy: lunhui15 imports this module's neighbours
    if mc.team():
        mc.game.team_leave()
    caster, end, last = Caster(mc), time.monotonic() + FETCH_WAIT, 0.0
    while time.monotonic() < end:
        s, cs = mc.world(), c.world()
        if s is None or cs is None or s.map_id != cs.map_id:
            return False
        if s.in_battle:
            caster.tick(time.monotonic())
        elif math.dist((s.x, s.y), (cs.x, cs.y)) <= FETCH_NEAR and not s.moving:
            return True
        elif time.monotonic() - last > 3 and not s.moving:
            caster.reset()
            mc.game.navigate(cs.map_id, round(cs.x), round(cs.y))
            last = time.monotonic()
        time.sleep(0.03 if s.in_battle else 0.2)  # lunhui15.BATTLE_TICK while fighting (user 2026-11-05)
    return False


def _fly(x):
    """x returns to its 飞鞋 record. -> True when it got there (marked as used for the hour)."""
    import math
    import shoe_point
    rec = w.read_shoe_record(x.mem)
    flee(x)
    if x.team():
        x.game.team_leave()
        t.wait(lambda: not x.team(), 5, f'{x.name} 离队')
    x.game.shoe_return()
    try:
        t.wait(lambda: (s := x.world()) and s.map_id == rec[0] and math.dist((s.x, s.y), rec[1:]) <= shoe_point.ARRIVE,
               6, f'{x.name} 飞到 {rec}')
    except t.Stop:
        return False
    shoe_point.mark_used(x.name, rec)
    t.say(f'[{x.name}] 飞鞋到了 {rec}')
    return True


def fetch(c):
    """User 2026-11-05: c has no 回城卷 and nobody within reach lends one. The master comes: on the same map it walks
    over; else c flies to its 飞鞋 record when the master is on that map or can fly to the same spot (the line
    records the whole team together), and the master walks / flies there. Then borrow. -> True when c has scrolls;
    False with the reason said (the caller stops)."""
    from common import MASTERS
    if not MASTERS or c.name in MASTERS:
        return False
    with _FETCH:
        mc = t.Client(MASTERS[0])
        start = mc.world().map_id
        got = _fetch(c, mc)
        if got and mc.world().map_id != start and start == 1:
            scroll(mc)                 # it was home already (home() sends the master last): back again
        return got


def _fetch(c, mc):
    import math
    import shoe_point
    cs, ms = c.world(), mc.world()
    if cs.map_id != ms.map_id:
        now = time.time()
        rec, mrec = w.read_shoe_record(c.mem), w.read_shoe_record(mc.mem)
        c_left = shoe_point.cooldown_left(shoe_point.used_at(c.name), now)
        m_left = shoe_point.cooldown_left(shoe_point.used_at(mc.name), now)
        m_there = rec and ms.map_id == rec[0]
        m_can = rec and mrec and mrec[0] == rec[0] and math.dist(mrec[1:], rec[1:]) <= shoe_point.NEAR and not m_left
        if not rec or c_left or not (m_there or m_can):
            t.say(f'[{c.name}] 没有回城卷，在地图 {cs.map_id} ({cs.x:.0f},{cs.y:.0f})；师傅在地图 {ms.map_id}；'
                  f'飞鞋记录 {rec}（冷却 {c_left // 60} 分），师傅记录 {mrec}（冷却 {m_left // 60} 分）：师傅接不到')
            return False
        t.say(f'[{c.name}] 没有回城卷，飞鞋到记录点 {rec}，师傅过去接')
        if not _fly(c):
            return False
        if not m_there and not _fly(mc):
            return False
    if not _master_walks_to(c, mc):
        t.say(f'[{c.name}] 师傅 {FETCH_WAIT}s 没走到身边')
        return False
    return borrow(c)


def scroll(c):
    st = c.world()
    slot = next((s.slot for s in w.read_bag(c.mem) if s.item_id == SCROLL_ITEM), None)
    if slot is None and (borrow(c) or fetch(c)):
        slot = next((s.slot for s in w.read_bag(c.mem) if s.item_id == SCROLL_ITEM), None)
        st = c.world()                    # fetch may have flown it elsewhere
    if slot is None:
        raise t.Stop(f'{c.name} 没有回城卷')
    for attempt in range(3):                  # round 4: a battle starting right then swallows the scroll
        flee(c)
        c.game.use_item(slot)
        try:
            t.wait(lambda: (s := c.world()) and s.map_id != st.map_id, 10, f'{c.name} 回城')
            break
        except t.Stop:
            if attempt == 2:
                raise
            slot = next((s.slot for s in w.read_bag(c.mem) if s.item_id == SCROLL_ITEM), slot)
    s = c.world()
    t.say(f'[{c.name}] 回城卷 map {st.map_id} -> {s.map_id} ({s.x:.0f},{s.y:.0f})')


def main():
    m.STAGES = STAGES
    apps = [t.Client(n) for n in m.APPRENTICES]
    for c in apps:
        if c.world().map_id not in (1, 130):
            if c.team():
                c.game.team_leave()
            scroll(c)
    m.STAGES[0]['done_when'] = Kills(apps)
    m.main()
    allc = [t.Client(n) for n in (m.LEADER,) + m.HELPERS] + apps
    for c in allc:
        if c.team():
            c.game.team_leave()
    for c in allc:
        t.wait(lambda: not c.team(), 5, f'{c.name} 离队')
        if c.world().map_id != 1:
            scroll(c)
    for c in apps:
        go(c)
        s = c.world()
        t.say(f'[{c.name}] 在禁军教头旁 map {s.map_id} ({s.x:.0f},{s.y:.0f})，任务 24 {w.read_quest(c.mem, 24)}')


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
