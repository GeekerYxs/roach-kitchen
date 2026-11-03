"""Look at an NPC's dialog: walk one role there, click, follow the given words, print every page (body + options).

    python -X utf8 research/shitu/npc_peek.py ROLE MAP X Y NPC [WORD ...]

For probing a quest chain nobody recorded yet (2026-11-02 术士 / 元素使): nothing is picked beyond the words given,
so the last page printed is where a human (or the next run, with one more word) decides. Quests 25 / 187 / 189 and
SHITU_QID are printed before and after.
"""
import os
import sys

import teamwalk
import trial_run as t
from pp_chain import walk
from provisioner import world as w
from take224 import talk

QIDS = (25, 187, 189, int(os.environ.get('SHITU_QID', '25')))


def page(c, d):
    t.say(f'[{c.name}] 对话: {t.body(d)[:300]}')
    t.say(f'[{c.name}] 选项: {[(o, t.plain(l)) for o, l in d.options]}')


def quests(c):
    return ' '.join(f'{q}{tuple(w.read_quest(c.mem, q).steps) or "-"}' for q in dict.fromkeys(QIDS))


def main(name, map_id, x, y, npc, *words):
    c = t.Client(name)
    xy = (int(x), int(y))
    if c.team():
        c.game.team_leave()
        t.wait(lambda: not c.team(), 5, f'{name} 离队')
    t.say(f'[{name}] 之前 {quests(c)}')
    # the client keeps the last page in memory after a click (2026-11-02 留一手: a page with no 离开 stayed, the
    # click's new main menu came later), so wait for a page that differs from it
    old = c.dialog()
    old = old.text if old else None
    s = c.world()
    if s.map_id != int(map_id) or not teamwalk.math.dist((s.x, s.y), xy) <= teamwalk.TRY_NEAR:
        walk(c, int(map_id), xy, f'NPC {npc}')
    c.game.click_npc(int(npc))
    try:
        d = t.wait(lambda: (x := c.dialog()) and x.text != old and x, 3, f'NPC {npc} 的新对话框')
    except t.Stop:
        d = t.wait(lambda: c.dialog(), 3, f'NPC {npc} 的对话框')
    page(c, d)
    for word in words:
        d = talk(c, int(npc), [word], d=d)
        if not d:
            t.say(f'[{name}] 选「{word}」后对话框关了')
            break
        page(c, d)
    t.say(f'[{name}] 之后 {quests(c)}')


if __name__ == '__main__':
    try:
        main(*sys.argv[1:])
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
