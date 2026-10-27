"""战士的试炼 task 181: kill 40 100Kg级拳手 in 无尽平原3区 (142) around (690,231) (SubTask.csv), team per SHITU_MASTERS.

    python -X utf8 research/shitu/quan100.py

User round 3 15:0x: team up and patrol there until the system message says the kills are enough. maze_train's loop
(leader casts, talent -> 体质) walks 龙之都外城 20 -> 142, patrols (690,231) <-> a probed point, and stops once every
apprentice's tap showed 0x46ff 「...杀死了40个100Kg级拳手」 (quanshou.Kills, other monster / count). Stays there, in team.
"""
import re

import maze_train as m
import quanshou

N = 40
quanshou.KILLS = re.compile(r'杀[死掉]了(\d+)个100Kg级拳手', re.I)

m.STAGES = (
    dict(name='无尽平原3区 100Kg级拳手', maze=142, until=None, patrol_a=(690, 231), patrol_b=None,
         legs={20: ('walk', 142, (690, 231))}),          # 龙之都外城 -> 无尽平原3区 西北
)


class Kills(quanshou.Kills):
    def __call__(self):
        super().__call__()
        return all(v >= N for v in self.count.values())


if __name__ == '__main__':
    try:
        m.STAGES[0]['done_when'] = Kills([m.t.Client(n) for n in m.APPRENTICES])
        m.main()
        m.t.say(f'40 个拳手都够了: {m.STAGES[0]["done_when"].count}')
    except m.t.Stop as e:
        m.t.say(f'停止: {e}')
        raise SystemExit(1)
