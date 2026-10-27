"""转职 task 24 step 3: kill 5 75kg级拳手 in 夕阳草原 (130) around (234,2583) (SubTask.csv) with the 5-man team.

    python -X utf8 research/shitu/quanshou.py

Apprentices scroll home first if they are not on map 1 / 130; then maze_train's loop (伏地魔1 leader, 扫射 + 烈焰爆发,
talent -> 体质) walks map 1 -> 130, patrols (234,2583) <-> a probed reachable point, and stops once every apprentice got the 0x46ff
「已经杀死了5个75Kg级拳手…」 (the quest tree stays (0,0,1) after the kills, 2026-10-27 02:00; round 2 reads the text). Then everybody uses a 回城卷 and the apprentices walk to 禁军教头 (NPC 304).
"""
import re

import maze_train as m
from monitor import Tap, texts
from factory.phase import SCROLL_ITEM
from provisioner import world as w
from zhuanzhi_take import go
t = m.t

m.STAGES = (
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
        self.count = {n: 0 for n in self.taps}

    def __call__(self):
        for n, tap in self.taps.items():
            for _, d, op, body, _ in tap.poll():
                if d == 'S->C' and op == 0x46ff:
                    text = COLOR.sub('', ' '.join(texts(body)))
                    k = KILLS.search(text)
                    if k:
                        self.count[n] = max(self.count[n], int(k.group(1)))
                        t.say(f'[{n}] {text}')
        return all(v >= 5 for v in self.count.values())


def scroll(c):
    st = c.world()
    slot = next((s.slot for s in w.read_bag(c.mem) if s.item_id == SCROLL_ITEM), None)
    if slot is None:
        raise t.Stop(f'{c.name} 没有回城卷')
    c.game.use_item(slot)
    t.wait(lambda: (s := c.world()) and s.map_id != st.map_id, 10, f'{c.name} 回城')
    s = c.world()
    t.say(f'[{c.name}] 回城卷 map {st.map_id} -> {s.map_id} ({s.x:.0f},{s.y:.0f})')


def main():
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
