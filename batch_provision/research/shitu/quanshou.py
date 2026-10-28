"""转职 task 24 step 3: kill 5 75kg级拳手 in 夕阳草原 (130) around (234,2583) (SubTask.csv) with the 5-man team.

    python -X utf8 research/shitu/quanshou.py

Apprentices scroll home first if they are not on map 1 / 130; then maze_train's loop (伏地魔1 leader, 扫射 + 烈焰爆发,
talent -> 体质) walks map 1 -> 130, patrols (234,2583) <-> a probed reachable point, and stops once every apprentice got the 0x46ff
「已经杀死了5个75Kg级拳手…」 (the quest tree stays (0,0,1) after the kills, 2026-10-27 02:00; round 2 reads the text). Then everybody uses a 回城卷 and the apprentices walk to 禁军教头 (NPC 304).
"""
import re
import time

import maze_train as m
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
    def __init__(self, apps):
        self.taps = {c.name: Tap(c.pid, from_end=True) for c in apps}
        for tap in self.taps.values():
            tap.ready()
        self.count = {n: 5 if done(n, 'kills5') else 0 for n in self.taps}

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


def borrow(c, k=5):
    """c (a master) has no 回城卷: take k from an apprentice of its team on the same map (2026-10-28 伏地魔2 ran out in
    the 古迹; every home() costs each member one). -> True when it got them."""
    import math
    import supply_go
    from common import APPRENTICES, MASTERS
    if c.name not in MASTERS:
        return False
    st = c.world()
    for n in APPRENTICES:
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


def scroll(c):
    st = c.world()
    slot = next((s.slot for s in w.read_bag(c.mem) if s.item_id == SCROLL_ITEM), None)
    if slot is None and borrow(c):
        slot = next((s.slot for s in w.read_bag(c.mem) if s.item_id == SCROLL_ITEM), None)
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
