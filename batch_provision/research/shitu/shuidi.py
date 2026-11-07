"""术士 转职 task 25 step (0,0,1): 3 本《看我七十二变》(item 10549) from 水滴精灵 in 夕阳草原 (130) around (318,1023).

    python -X utf8 research/shitu/shuidi.py

The 术士 twin of quanshou.py (task 24's 拳手): same team, same maze_train loop (伏地魔1 leader, talent -> SHITU_STAT),
but the books are drops, so the stage ends once every apprentice holds 3 of them in its bag (the quest tree stays
(0,0,1) like 24's). Then everybody uses a 回城卷 and the apprentices walk to 留一手 (NPC 305) for the hand-in.
Recorded 2026-11-02 元素使01: 0x46ff「接受了任务：悟性的考验 去夕阳草原水滴精灵身上抢回魔法书《看我七十二变》」.
"""
import maze_train as m
import progress
import quanshou as q
from provisioner import world as w
from zhuanzhi_take import go
t = m.t

BOOK, NEED, QUEST = 10549, 3, 25
STAGES = (
    dict(name='夕阳草原 水滴精灵', maze=130, until=None, patrol_a=(318, 1023), patrol_b=None,
         legs={1: ('walk', 130, (318, 1023))}),
)


def handed_in(c):
    """Task 25 already past the books (the hand-in took them): 2026-11-07 r4ys25 奥德赛25 handed in, 奥德赛27 dropped,
    the rerun waited for 奥德赛25's books for ever. By the step count only (progress.py: relogs garble the bytes)."""
    return progress.past(w.read_quest(c.mem, QUEST), progress.CLASS_ITEMS + 1)


class Books:
    """done_when of the stage: every apprentice has NEED books or has handed them in (logged when that changes)."""
    def __init__(self, apps):
        self.apps, self.last = apps, {}

    def __call__(self):
        for c in self.apps:
            n = 'in' if handed_in(c) else w.item_count(w.read_bag(c.mem), BOOK)
            if n != self.last.get(c.name):
                t.say(f'[{c.name}] 《看我七十二变》' + ('已交，不用再刷' if n == 'in' else f'{n}/{NEED}'))
                self.last[c.name] = n
        return all(v == 'in' or v >= NEED for v in (self.last[c.name] for c in self.apps))


def main():
    m.STAGES = STAGES
    apps = [t.Client(n) for n in m.APPRENTICES]
    books = Books(apps)
    if books():          # a rerun after the hand-in (2026-11-07 r4ys25): no farming, straight to 留一手
        t.say('每个徒弟都已有 3 本书或已交书，不用再刷水滴精灵')
    else:
        for c in apps:
            if c.world().map_id not in (1, 130):
                if c.team():
                    c.game.team_leave()
                q.scroll(c)
        m.STAGES[0]['done_when'] = books
        m.main()
    allc = [t.Client(n) for n in (m.LEADER,) + m.HELPERS] + apps
    for c in allc:
        if c.team():
            c.game.team_leave()
    for c in allc:
        t.wait(lambda: not c.team(), 5, f'{c.name} 离队')
        if c.world().map_id not in (1, 8):           # 8 = 就职所 (a rerun may start there)
            q.scroll(c)
    for c in apps:
        if handed_in(c):
            continue
        go(c)
        s = c.world()
        t.say(f'[{c.name}] 在留一手旁 map {s.map_id} ({s.x:.0f},{s.y:.0f})，任务 25 {w.read_quest(c.mem, 25)}')


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
