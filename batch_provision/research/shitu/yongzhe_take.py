"""成为勇者 at 龙格尔男爵 (NPC 631, 龙之都外城 20 (3174,1251)), user 17:1x after task 181.

    python -X utf8 research/shitu/yongzhe_take.py 千万1 千万2 ...

Dialog (live 千万1 17:13): 「进行战士转职考验」->「成为勇者」(vs 成为格斗家 / 再考虑考虑) ->「什么事呢？」->「好啊。」->
「接受任务」(vs 取消): deliver 紧急物资 to 营长孙大胜 at the 苦无沙漠1区 camp. Prints the new quest id(s) per role.
"""
import struct
import sys
import time

import trial_run as t
from provisioner import world as w
from take224 import talk

PATH = ['进行战士转职考验', '成为勇者', '什么事呢', '好啊', '接受任务']


def active(c):
    p = w._player_data(c.mem)
    head = c.mem.u32(p + w.QUEST_ACTIVE)
    return {struct.unpack_from('<I', r, 0xC)[0] >> 16 for r in w._tree_nodes(c.mem, head, w.QUEST_ACTIVE_NODE, w.QUEST_ACTIVE_NIL)}


def take(name):
    c = t.Client(name)
    before = active(c)
    d = c.dialog()
    if d and any('接受任务' in t.plain(l) for _, l in d.options):      # 千万1: probed up to here by hand
        steps = ['接受任务']
    else:
        if d:
            c.game.select_dialog(0)
            time.sleep(0.4)
        steps = PATH
    if steps is PATH:
        talk(c, 631, steps)
    else:
        c.game.select_dialog(next(o for o, l in d.options if '接受任务' in t.plain(l)))
    time.sleep(1.0)
    new = active(c) - before
    t.say(f'[{name}] 新任务 {sorted(new)} ' + ' '.join(f'{q}{w.read_quest(c.mem, q).steps}' for q in new)
          + f'；对话 {t.body(c.dialog())[:60] if c.dialog() else None}')


if __name__ == '__main__':
    for n in sys.argv[1:]:
        take(n)
