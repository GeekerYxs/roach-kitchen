"""Farm a quest drop with the team until every apprentice holds NEED of ITEM (2026-11-03, 元素使 team's 187 / 189).

    python -X utf8 research/shitu/farm.py [--stay] MAP X Y ITEM NEED [GO_SCRIPT ARG ...]

  MAP X Y      patrol around (X, Y) on map MAP (maze_train: the master leads, casts, revives; points probed around it)
  ITEM NEED    stop once every apprentice's bag holds NEED of item ITEM (logged whenever a count changes)
  GO_SCRIPT    run first when the leader is not on MAP yet, e.g. desert_go.py 1062 1221 / guji_entrance.py
Afterwards everybody leaves the team and scrolls home (--stay: the team stays where it is, e.g. 189's 仙人掌果肉 go
to 火蜥蜴 on the same map). The same pattern as shuidi.py (books) and stones.py (魔法石);
the drops seen so far were team-wide (every member got each one).

e.g. 187 step 6, 10 神仙姐姐的画像 (10716) from 猥琐教打杂的 opposite the 苦无沙漠1区 camp:
    python -X utf8 research/shitu/farm.py 170 1062 1221 10716 10 desert_go.py 1062 1221
"""
import subprocess
import sys

import maze_train as m
import quanshou as q
from factory.items import load_items
from provisioner import world as w
t = m.t


MIN_FREE = 4         # free bag slots kept while farming (a full bag silently loses the drop: 2026-11-03 毛皮 0 in 15 min)


def junk(it):
    """User 2026-11-03: the apprentices just drop 技能石, the three 葫芦 and every 杂物."""
    return it is not None and ('技能石' in it.name or '葫芦' in it.name or it.type == 0x1000)


def make_room(c, items):
    """Drop junk until MIN_FREE slots are free (only called out of battle: drops in battle are ignored)."""
    import struct
    bag = w.read_bag(c.mem)
    free = w.read_bag_capacity(c.mem) - len(bag)
    for s in [s for s in bag if junk(items.get(s.item_id))]:
        if free >= MIN_FREE:
            break
        c.game.send(0x48, struct.pack('<IBBH', 0, 0, s.slot, s.quantity))
        try:
            t.wait(lambda: not any(b.slot == s.slot and b.item_id == s.item_id for b in w.read_bag(c.mem)), 4,
                   f'{c.name} 丢 {items[s.item_id].name}')
            free += 1
        except t.Stop:
            pass
    if free < MIN_FREE:
        t.say(f'[{c.name}] 背包只剩 {free} 格，没有可丢的杂物了')


class Count:
    def __init__(self, apps, item, need, name):
        self.apps, self.item, self.need, self.name, self.last = apps, item, need, name, {}
        self.items = load_items()

    def __call__(self):
        for c in self.apps:
            if w.read_bag_capacity(c.mem) - len(w.read_bag(c.mem)) < MIN_FREE:
                make_room(c, self.items)
            n = w.item_count(w.read_bag(c.mem), self.item)
            if n != self.last.get(c.name):
                t.say(f'[{c.name}] {self.name} {n}/{self.need}')
                self.last[c.name] = n
        return all(self.last[c.name] >= self.need for c in self.apps)


def main(map_id, xy, item, need, go, stay=False):
    name = load_items().get(item)
    name = name.name if name else str(item)
    apps = [t.Client(n) for n in m.APPRENTICES]
    if go and t.Client(m.LEADER).world().map_id != map_id:
        subprocess.run([sys.executable, '-X', 'utf8', *go], check=True)
    m.STAGES = (dict(name=f'地图 {map_id} 刷 {name}', maze=map_id, until=None, patrol_a=xy, patrol_b=None, legs={},
                     done_when=Count(apps, item, need, name)),)
    m.main()
    if stay:
        return
    allc = [t.Client(n) for n in (m.LEADER,) + m.HELPERS] + apps
    for c in allc:
        if c.team():
            c.game.team_leave()
    for c in allc:
        t.wait(lambda: not c.team(), 5, f'{c.name} 离队')
        if c.world().map_id != 1:
            q.scroll(c)


if __name__ == '__main__':
    a = sys.argv[1:]
    stay = '--stay' in a
    a = [x for x in a if x != '--stay']
    try:
        main(int(a[0]), (int(a[1]), int(a[2])), int(a[3]), int(a[4]), a[5:], stay)
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
