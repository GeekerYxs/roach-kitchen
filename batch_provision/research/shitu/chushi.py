"""出师任务 + 正式出师 for each apprentice of one master, one after the other (round 3, 18:1x).

    python -X utf8 research/shitu/chushi.py MASTER 千万2 千万3 ...

Recorded 18:07-18:09 (user by hand, 伏地魔1 + 千万1; logs/mem_*.jsonl, net_*.jsonl):
  1. two-man team, the APPRENTICE leading, the master member («师徒任务必须两人组队，徒弟当队长»);
  2. apprentice at 糊涂博士 (NPC 341, map 1 (1398,1329)): 师徒任务 -> 出师任务 -> 我已经完成考验了 -> reward list
     (9 weapons + 等会再来; user took opt 2「狂暴之球棒(战系短兵器)」 64309) ->「你现在可以让师傅带着你正式出师了」;
  3. apprentice hands the lead to the master: C->S 0x35 <I 0><I master char id> (S->C 0x4708);
  4. master at 341: 正式出师 -> 正式让徒弟出师 (master +583 道德; apprentice +20万 exp / +20万 gold / +40万 潜能);
  5. apprentice leaves the team (0x33).
Needs one free bag slot for the weapon (the dialog warns).
"""
import struct
import sys
import time

import teamwalk as d
import trial_run as t
from pp_chain import walk
from provisioner import world as w
from take224 import talk

NPC, XY, WEAPON = 341, (1398, 1329), '狂暴之球棒'
OP_TEAM_LEAD = 0x35


def leave(c):
    if c.team():
        c.game.team_leave()
        t.wait(lambda: not c.team(), 5, f'{c.name} 离队')


def one(master, app):
    m, a = t.Client(master), t.Client(app)
    for c in (m, a):
        if c.dialog():
            c.game.select_dialog(0)
        leave(c)
        walk(c, 1, XY, '糊涂博士')
    gold, level = w.read_gold(a.mem), w.read_level(a.mem)
    d.MAP = 1
    d.regroup(a, [m])                                   # apprentice leads
    dlg = talk(a, NPC, ['师徒任务', '出师任务', '我已经完成考验了'])
    opts = [(o, t.plain(l)) for o, l in dlg.options if o]
    pick = next((o for o, l in opts if WEAPON in l), None)
    if pick is None:
        a.game.select_dialog(0)
        raise t.Stop(f'{app} 奖励列表里没有 {WEAPON}: {t.body(dlg)[:60]} {opts}')
    a.game.select_dialog(pick)
    t.wait(lambda: any(s.item_id == 64309 for s in w.read_bag(a.mem)), 5, f'{app} 拿到 {WEAPON}')
    a.game.send(OP_TEAM_LEAD, struct.pack('<II', 0, m.char_id))
    t.wait(lambda: (m.team() or (0,))[0] == m.char_id, 5, f'{master} 当队长')
    talk(m, NPC, ['正式出师', '正式让徒弟出师'])
    t.wait(lambda: w.read_level(a.mem) > level or w.read_gold(a.mem) >= gold + 200000, 5, f'{app} 出师奖励')
    time.sleep(0.5)
    if m.dialog():
        m.game.select_dialog(0)
    leave(a)
    t.say(f'[{app}] 出师：等级 {level} -> {w.read_level(a.mem)}，金币 {gold} -> {w.read_gold(a.mem)}，'
          f'{WEAPON} {w.item_count(w.read_bag(a.mem), 64309)}')


if __name__ == '__main__':
    master, *apps = sys.argv[1:]
    try:
        for n in apps:
            one(master, n)
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
