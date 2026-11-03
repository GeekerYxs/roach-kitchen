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
import quanshou as q
from monitor import Tap, texts
t = m.t

NEED = 5
PATROL = ((414, 4893), (106, 4467))          # tower28.py's 通天塔一区 points
COUNT = re.compile(r'(\d+)\s*[个只]\s*色妖道')
COLOR = re.compile(r'#[0-9A-Fa-f]{6}#')


class Kills:
    def __init__(self, apps):
        self.taps = {c.name: Tap(c.pid, from_end=True) for c in apps}
        for tap in self.taps.values():
            tap.ready()
        self.count = {n: 0 for n in self.taps}

    def __call__(self):
        for n, tap in self.taps.items():
            for _, d, op, body, _ in tap.poll():
                if d != 'S->C' or op != 0x46ff:
                    continue
                text = COLOR.sub('', ' '.join(texts(body)))
                if '色妖道' not in text:
                    continue
                k = COUNT.search(text)
                if k:
                    self.count[n] = max(self.count[n], int(k.group(1)))
                t.say(f'[{n}] {text}（计 {self.count[n]}/{NEED}）')
        return all(v >= NEED for v in self.count.values())


def main():
    apps = [t.Client(n) for n in m.APPRENTICES]
    if t.Client(m.LEADER).world().map_id != 280:
        subprocess.run([sys.executable, '-X', 'utf8', 'tower1_go.py', *map(str, PATROL[0])], check=True)
    m.STAGES = (dict(name='通天塔一区 色妖道', maze=280, until=None, patrol_a=PATROL[0], patrol_b=PATROL[1], legs={},
                     done_when=Kills(apps)),)
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
