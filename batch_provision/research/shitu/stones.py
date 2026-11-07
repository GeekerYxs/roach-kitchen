"""术士的试炼 187 step (2,1): 10 魔法石 each from the 精灵巫师 in 逍遥古迹 (650), for 清明长老's 能量石.

    python -X utf8 research/shitu/stones.py [X Y]          patrol around X Y on 650 (default: the 黑色水晶 spot)

Live 2026-11-03 00:34 (元素使01, 留一手): 「在夕阳草原的逍遥古迹中有一群精灵巫师，他们身上都带有一颗魔法石，集合10颗…
龙之都的清明长老就能为你合成一颗能量石」; 10 完美的魔法石 (10712) -> 完美无暇的能量石 = 优秀 (more 奖学金), any 10
(有瑕疵的 10713 counts too) = pass. Like shuidi.py: the team (master leads, casts, revives) patrols until every
apprentice holds 10 stones of either kind; the counts are logged whenever they change (drop rate, team-wide or not).
Getting in: guji_entrance.py (team to 650, the 二层 door); the patrol point is the 181 crystal spot unless given.
"""
import subprocess
import sys

import maze_train as m
import progress
import quanshou as q
from provisioner import world as w
t = m.t

PERFECT, FLAWED, NEED = 10712, 10713, 10
QUEST, PAST = 187, 3
SPOT = (2542, 3442)


def handed_in(c):
    """187 past the stones: 清明长老 took them for the 能量石, (2,1) -> (2,2,1) (YUANSU_NOTES.md 187 live 2026-11-03).
    2026-11-07 (the r4ys25 books loop): a rerun of y_stone after one apprentice's 清明长老 must not wait for its stones."""
    return progress.past(w.read_quest(c.mem, QUEST), PAST)


class Stones:
    def __init__(self, apps):
        self.apps, self.last = apps, {}

    def __call__(self):
        for c in self.apps:
            if handed_in(c):
                n = 'in'
            else:
                bag = w.read_bag(c.mem)
                n = (w.item_count(bag, PERFECT), w.item_count(bag, FLAWED))
            if n != self.last.get(c.name):
                t.say(f'[{c.name}] 魔法石 ' + ('已交清明长老，不用再刷' if n == 'in' else f'完美 {n[0]}/{NEED}，有瑕疵 {n[1]}'))
                self.last[c.name] = n
        # every battle so far gave each apprentice 1 完美 + 1 有瑕疵 (00:38-00:39, team-wide like the 水滴精灵 books), so
        # 10 完美 (优秀, 完美无暇的能量石) costs ~5 battles more than 10 of either: wait for 10 完美
        return all(v == 'in' or v[0] >= NEED for v in (self.last[c.name] for c in self.apps))


def main(spot):
    apps = [t.Client(n) for n in m.APPRENTICES]
    stones = Stones(apps)
    if stones():         # a rerun after 清明长老 (2026-11-07): no farming, only the trip home below
        t.say('每个徒弟都已有 10 颗完美魔法石或已交清明长老，不用再刷')
    else:
        if t.Client(m.LEADER).world().map_id != 650:
            subprocess.run([sys.executable, '-X', 'utf8', 'guji_entrance.py'], check=True)
        m.STAGES = (dict(name='逍遥古迹 精灵巫师', maze=650, until=None, patrol_a=spot, patrol_b=None,
                         legs={650: ('walk', 650, spot)}, done_when=stones),)
        m.main()
    allc = [t.Client(n) for n in (m.LEADER,) + m.HELPERS] + apps
    for c in allc:
        if c.team():
            c.game.team_leave()
    for c in allc:
        t.wait(lambda: not c.team(), 5, f'{c.name} 离队')
        if c.world().map_id != 1:
            q.scroll(c)


if __name__ == '__main__':
    try:
        main(tuple(map(int, sys.argv[1:3])) if len(sys.argv) >= 3 else SPOT)
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
