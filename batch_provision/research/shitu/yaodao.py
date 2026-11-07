"""术士的试炼 187 step (2,2,2,2,1): kill 5 色妖道 in 通天塔一区 (280) with the team, within 2 hours of 虫洞法师's order
(that earns a second 优秀术士证书).

    python -X utf8 research/shitu/yaodao.py

Live 2026-11-03 00:45 (元素使01, 虫洞法师 203): 「你要对付的是一群杀人不眨眼的色妖道，他们就躲在通天塔内…两个小时内完成…」.
色妖道 = 33 级, 通天塔一区 (logs/battlelog/report.md). The team goes in like tower1 (tower1_go.py from 逍遥村) and patrols
tower28's two points until every apprentice's 0x46ff count of 色妖道 reaches 5 (the 拳手 of task 24 were counted the
same way: the quest tree does not show kills). Every 0x46ff naming 色妖道 is logged (the exact wording was unknown).
Then everybody scrolls home.
"""
import re
import subprocess
import sys

import maze_train as m
import progress
import quanshou as q
from bai_shi import done, mark
from monitor import Tap, texts
from provisioner import world as w
t = m.t

NEED = 5
QUEST, PAST = 187, 6         # 虫洞法师 took the kills: 187 has 6 steps (route y_yaodao's `U need 187 6`)
PATROL = ((414, 4893), (106, 4467))          # tower28.py's 通天塔一区 points
# only the kill report「你已经杀死了N个色妖道，需要5个」/「…可以回去找虫洞法师了」(logs 2026-11-03 / 11-07). 2026-11-07
# r4ys29: the looser (\d+)[个只]色妖道 also matched the order's「…5只色妖道…」in the tap history (c19f839 reads it), so
# all four were marked yaodao5 23 s after taking the order, never went to the tower and 虫洞法师 refused every rerun
COUNT = re.compile(r'杀死了\s*(\d+)\s*个\s*色妖道')
COLOR = re.compile(r'#[0-9A-Fa-f]{6}#')


def kill_count(text):
    """色妖道 count in one 0x46ff text (colour codes stripped), or None."""
    k = COUNT.search(text) if '色妖道' in text else None
    return int(k.group(1)) if k else None


class Kills:
    """done_when: every apprentice saw 5 色妖道 kills, or is past them. 2026-11-07 (the r4ys25 books loop, same
    pattern as quanshou.Kills): the kill text comes once, so a rerun counts (a) 187 already handed in at 虫洞法师
    (`U need 187 6`), (b) the state mark yaodao5, (c) the kill texts already in this login's tap file."""
    def __init__(self, apps):
        self.taps = {c.name: Tap(c.pid, from_end=True) for c in apps}
        for tap in self.taps.values():
            tap.ready()
        self.count = {n: 0 for n in self.taps}
        for c in apps:
            if progress.past(w.read_quest(c.mem, QUEST), PAST) or done(c.name, 'yaodao5'):
                self.count[c.name] = NEED
                continue
            old = Tap(c.pid, from_end=False)
            old.ready()
            for _, d, op, body, _ in old.poll():
                if d == 'S->C' and op == 0x46ff:
                    k = kill_count(COLOR.sub('', ' '.join(texts(body))))
                    if k:
                        self.count[c.name] = max(self.count[c.name], k)
            if self.count[c.name]:
                t.say(f'[{c.name}] 这次登录已经杀了 {self.count[c.name]} 个色妖道（之前的消息）')
            if self.count[c.name] >= NEED:
                mark(c.name, 'yaodao5')

    def __call__(self):
        for n, tap in self.taps.items():
            for _, d, op, body, _ in tap.poll():
                if d != 'S->C' or op != 0x46ff:
                    continue
                text = COLOR.sub('', ' '.join(texts(body)))
                if '色妖道' not in text:
                    continue
                k = kill_count(text)
                if k:
                    self.count[n] = max(self.count[n], k)
                    if self.count[n] >= NEED and not done(n, 'yaodao5'):
                        mark(n, 'yaodao5')       # a rerun must not wait for kills that never come again
                t.say(f'[{n}] {text}（计 {self.count[n]}/{NEED}）')
        return all(v >= NEED for v in self.count.values())


def main():
    apps = [t.Client(n) for n in m.APPRENTICES]
    kills = Kills(apps)
    if kills():          # a rerun after the kills / the 虫洞法师 hand-in: no trip to the tower
        t.say(f'每个徒弟都已杀够 {NEED} 个色妖道或已交，不用再打: {kills.count}')
    else:
        if t.Client(m.LEADER).world().map_id != 280:
            subprocess.run([sys.executable, '-X', 'utf8', 'tower1_go.py', *map(str, PATROL[0])], check=True)
        m.STAGES = (dict(name='通天塔一区 色妖道', maze=280, until=None, patrol_a=PATROL[0], patrol_b=PATROL[1],
                         legs={}, done_when=kills),)
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
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
