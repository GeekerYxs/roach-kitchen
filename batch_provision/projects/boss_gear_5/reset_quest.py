"""5-man boss-gear line: abandon this boss's quest on every role that has it, so the leader takes it fresh (user 2026-11-07).

    python -X utf8 reset_quest.py QUEST [QUEST ...]        (e.g. reset_quest.py 518; chainsaw: 1852 1853)

Why (user 2026-11-07, gemini's run that day): the 5th role still had (2,1) from an old round that was beaten but not
handed in, the other four had (1,). round_*.py skipped the fight because *someone* was ready, handin_* stopped
because the leader was not; handing the old one in from inside the team does not work (members clicking an NPC get
no dialog), and at the boss the server sees mixed progress and offers only 离开. The user: rewards do not matter,
the boss's gear drops do, and the quest is only needed to start the fight - so before a day's run every role drops
the quest and the leader takes it again (take_*.py already gets a role that missed it to take it alone).

The abandon request: client 2.101 SendCancelTaskPacket (RVA 0x16ECF0, the script binding at 0xFB0C, the same call
the task window's give-up button and the built-in task_abandon command at 0x3421F0 use) sends opcode 0xA0 with the
8-byte body <I 0><I main task id> through RVA_SEND. Only the quests passed in are touched (never 475 葵花宝典 or story
quests: user 2026-11-07).

Live 2026-11-07 13:4x (伏地魔1-4 + 伏地魔, 迷惑森林3区): 0xA0 drops the quest in 0.1 s, alone or inside the team, with no
dialog open; the leader dropping it does NOT drop it for the members (each role sends its own). Abandoning leaves the
quest items in the bag: 伏地魔1-4 kept 老树根 from the old round and leaf_fight then took the team for one already
past the follower and stopped. So the reset also drops this boss's own quest items (0x48, only the ids passed in).
"""
import struct
import sys
import time

from _bootstrap import ROLES

import trial_run as t
from provisioner import world as w
from r4_util import close_dialogs

OP_CANCEL_TASK = 0xA0          # docs/GAME_UPDATE.md table B
OP_DROP = 0x48                 # <IBBH>(0, 0, slot, quantity), same as r4_util.space_one
GONE_WITHIN = 5.0              # s for the quest to leave the client's active tree after the request


def cancel_body(quest):
    return struct.pack('<II', 0, quest)


def steps(c, quest):
    q = w.read_quest(c.mem, quest)
    return q.steps if q and q.active else ()


def same_progress(cs, quest):
    """True when every role is at the same point of `quest` (all without it counts as the same)."""
    return len({steps(c, quest) for c in cs}) == 1


def describe(cs, quest):
    return '，'.join(f'{c.name} {steps(c, quest) or "无"}' for c in cs)


def abandon(c, quest):
    """Drop one quest on one role. -> True when it was there and is gone now."""
    if not steps(c, quest):
        return False
    c.game.send(OP_CANCEL_TASK, cancel_body(quest))
    t.wait(lambda: not steps(c, quest), GONE_WITHIN, f'{c.name} 放弃任务 {quest}')
    return True


def held(c, items):
    return [b for b in w.read_bag(c.mem) or () if b.item_id in items]


def drop_items(c, items):
    """Drop every stack of these item ids (this boss's quest items left from an old round). -> names dropped."""
    out = []
    for b in held(c, items):
        c.game.send(OP_DROP, struct.pack('<IBBH', 0, 0, b.slot, b.quantity))
        out.append(f'{items[b.item_id]}x{b.quantity}')
        time.sleep(0.6)
    if out:
        t.wait(lambda: not held(c, items), GONE_WITHIN, f'{c.name} 丢掉 {"、".join(out)}')
    return out


def reset(cs, quests, items=None):
    """Every role in cs drops every quest in `quests` it has, and (items = {id: name}) those items. Team and
    position stay as they are."""
    close_dialogs(cs)
    time.sleep(0.3)
    dropped = []
    for c in cs:
        for q in quests:
            had = steps(c, q)
            if abandon(c, q):
                dropped.append(f'{c.name} {q}{had}')
        for name in drop_items(c, items or {}):
            dropped.append(f'{c.name} 丢 {name}')
    t.say('放弃了: ' + '，'.join(dropped) if dropped else f'没有人身上有任务 {"/".join(map(str, quests))}')
    return dropped


def start_of_run(quests, what, items=None):
    """Called once before round 1 of round_*.py. SHITU_BOSS_RESET=0 skips it (resume a stopped run as before)."""
    import os
    if os.environ.get('SHITU_BOSS_RESET', '1') == '0':
        t.say('SHITU_BOSS_RESET=0：不做开跑初始化，接着上次的进度')
        return
    cs = [t.Client(r) for r in ROLES]
    t.say(f'开跑初始化：全员放弃「{what}」（{describe(cs, quests[0])}），再由队长重新接')
    reset(cs, quests, items)


def check_same(cs, quests, what, items=None):
    """Inside a round: mixed progress on the main quest -> drop it on everyone (the round then re-takes it)."""
    if same_progress(cs, quests[0]):
        return False
    t.say(f'「{what}」全队进度不一样（{describe(cs, quests[0])}），全员放弃后重新接')
    reset(cs, quests, items)
    return True


if __name__ == '__main__':
    try:
        qs = tuple(int(a) for a in sys.argv[1:])
        if not qs:
            raise t.Stop('用法: reset_quest.py 任务号 [任务号 ...]')
        reset([t.Client(r) for r in ROLES], qs)
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
