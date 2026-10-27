"""Walk each named role to an NPC and click through its dialog for task 181 (round 3, 战士的试炼 chain).

    python -X utf8 research/shitu/talk_chain.py MAP X Y NPC WORD 千万1 千万2 ...

Each role leaves its team, walks (pp_chain.walk, own thread = own window), clicks NPC, picks the option holding WORD,
then takes the single non-离开 option while there is exactly one; stops on 0 or 2+ options and prints them.
"""
import sys
import threading
import time

import trial_run as t
from pp_chain import walk
from provisioner import world as w
from take224 import talk

QID = int(__import__('os').environ.get('SHITU_QID', '181'))


def run(name, map_id, xy, npc, word):
    c = t.Client(name)
    if c.team():
        c.game.team_leave()
        t.wait(lambda: not c.team(), 5, f'{name} 离队')
    walk(c, map_id, xy, f'NPC {npc}')
    before = w.read_quest(c.mem, QID)
    d = talk(c, npc, [word])
    seen = []
    for _ in range(10):
        opts = [(o, t.plain(l)) for o, l in d.options if o != 0]
        if len(opts) != 1:
            t.say(f'[{name}] 停在多选/无选项: {t.body(d)[:120]} {opts}')
            break
        o, l = opts[0]
        seen.append(l)
        prev = d.text
        c.game.select_dialog(o)
        time.sleep(0.8)
        d = c.dialog()
        if not d or d.text == prev:
            break
        t.say(f'[{name}] {t.body(d)[:150]}')
    t.say(f'[{name}] 选了 {seen}；{QID} {before.steps} -> {w.read_quest(c.mem, QID)}')


if __name__ == '__main__':
    m, x, y, npc, word, *names = sys.argv[1:]
    ths = [threading.Thread(target=run, args=(n, int(m), (int(x), int(y)), int(npc), word)) for n in names]
    [th.start() for th in ths]
    [th.join() for th in ths]
