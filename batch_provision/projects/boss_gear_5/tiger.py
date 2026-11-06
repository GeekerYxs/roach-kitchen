"""玩死虎力仙 (quest 1185, lv62, 10 a day like the eagle): constants and helpers shared by the tiger scripts.

Quest steps (ResLib SubTask 1185): 0 蛟龙之柱 4089, 1 兀鹫之柱 4090, 2 血蝠之柱 4091, 3 邪蛇之柱 4092, 4 虎力仙 1168,
5 report to 银狐王勇 (NPC 2603, 荒芜之地2区 map 181). Pillars and the tiger are in 禁锢之地 (map 1200).

Live 2026-11-06 (伏地魔1 + four 70s):
- A team member WITHOUT the quest blocks the leader: picking「★玩死虎力仙［进行中］」just closed the dialog. With that
  member out of the team, the same pick gave「领取奖励」; the four in the team handed in at once and were offered
  the quest again (接受任务 -> all four took it). The member took it alone (standing ~200 px off, out of the team):
  ☆玩死虎力仙(62）-> 继续 -> 接受任务, then was invited back.
- The tiger beaten after only 2 pillars (4092, 4089) marked ALL five steps 0-4 done for all five members.
"""
import time

import trial_run as t
from provisioner import world as w

QUEST = 1185
DESERT_2, JINGU = 181, 1200
WANGYONG, WANGYONG_XY = 2603, (750, 1665)
TIGER, TIGER_XY = 1168, (3666, 3459)
TIGER_STEP, REPORT_STEP, DONE = 4, 5, 2
# npc -> (quest step, name, ResLib xy)
PILLARS = {4089: (0, '蛟龙之柱', (3402, 4191)), 4090: (1, '兀鹫之柱', (2730, 3885)),
           4091: (2, '血蝠之柱', (4494, 3087)), 4092: (3, '邪蛇之柱', (4830, 3513))}


def steps(c):
    q = w.read_quest(c.mem, QUEST)
    return q.steps if q and q.active else ()


def has_quest(c):
    return bool(steps(c))


def step_done(c, i):
    s = steps(c)
    return len(s) > i and s[i] == DONE


def beaten(c):
    return step_done(c, TIGER_STEP)


def ready(c):                                  # beat the tiger, not reported yet
    s = steps(c)
    return len(s) > REPORT_STEP and s[TIGER_STEP] == DONE and s[REPORT_STEP] != DONE


def close(c):
    for _ in range(3):
        if c.dialog() is None:
            return
        c.game.select_dialog(0)
        time.sleep(0.5)


def open_npc(c, npc, what):
    """Raw 0x50 click (no walking: a role alone out of the team must not wander off), the NPC's first page."""
    from eagle_cage import click
    close(c)
    for attempt in range(3):
        click(c, npc)
        try:
            return t.wait(lambda: c.dialog(), 5, f'{what}的对话框')
        except t.Stop:
            if c.world().in_battle:               # an encounter swallowed the click
                from lunhui15 import fight_out
                fight_out(c, 300)
    raise t.Stop(f'[{c.name}] 点了 3 次{what}都没有对话框')


def regroup(cs):
    """Invite back every role that is out of the leader's team (research/jingu/turnin.invite; map 181)."""
    import sys
    from _bootstrap import BATCH
    sys.path.insert(0, str(BATCH / 'research' / 'jingu'))
    import turnin
    lead = cs[0]
    for c in cs:                               # live 2026-11-06: an open dialog on the leader blocks the invite
        close(c)
    for c in cs[1:]:
        if c.char_id not in lead.team():
            turnin.invite(lead, c)
