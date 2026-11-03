"""元素使的考验 189 step 6: make the 第五元素 in 通天塔3号房 (map 297), each apprentice for itself, all at once.

    python -X utf8 research/shitu/fifth.py 元素使02 元素使03 ...         (default: SHITU_APPRENTICES)

Recorded live 2026-11-03 09:06-09:13 (元素使01, the user led the way: 通天塔一区 (756,2186) -> 1号房 295, the
quest holder leading the team clicks 石像 1088「传送至2号房」-> 291, 石像 1089「传送至3号房」-> 297 (582,759); the
master gets no teleport option from the 石像):
  地板 994 (498,633)「释放出元素精髓」-> 0x46ff「你已召唤出了魔法器皿…3分钟后就可能会消失」
  魔法器皿 995 「注入火之烈焰和水之精华」, then every ~1 min (never more than 3) the next vessel id answers:
  996「注入土之微尘和水之精华」, 997「注入风之气息和水之精华」, 998「注入水之精华」, 999「注入水之精华」
  (5 水 / 1 火 / 1 土 / 1 风 in all) -> the server spawns NPC 1134「第五元素」(0x40a0) for 3 minutes:
  「抓住她」-> 第五元素 10732 in the bag,「将第五元素带回交给龙之都的奥里雷西亚女士」.
Only a team's leader can talk to NPCs, so the role takes the lead first (take_lead). The floor serves one role at a
time, so the roles go one after another (09:14 three at once: only the first got the floor).
"""
import sys
import time

import trial_run as t
from common import APPRENTICES, MASTERS
from provisioner import world as w

FLOOR, VESSELS, FIFTH = 994, (995, 996, 997, 998, 999), 1134
ITEM = 10732
DEADLINE = 600                       # s for the whole sequence of one role
FLOOR_WAIT, FLOOR_RETRY = 360, 20


def click_any(c, npcs, wait=2.0):
    """Click each NPC id in turn; -> (npc, dialog) of the first that answers, or None."""
    for npc in npcs:
        if c.dialog():
            c.game.select_dialog(0)
            time.sleep(0.3)
        c.game.click_npc(npc)
        try:
            return npc, t.wait(lambda: c.dialog(), wait, f'{c.name} NPC {npc}')
        except t.Stop:
            pass
    return None


def take_lead(c):
    """In a team only the leader can talk to NPCs (user 2026-11-03: 元素使03 as a member got no floor dialog), so the
    role doing the 第五元素 becomes the leader: the current leader hands over with 0x35 <I 0><I char id> (chushi.py)."""
    import struct
    team = c.team()
    if not team or team[0] == c.char_id:
        return
    lead = next(x for x in (t.Client(n) for n in APPRENTICES + MASTERS) if x.char_id == team[0])
    lead.game.send(0x35, struct.pack('<II', 0, c.char_id))
    t.wait(lambda: (tm := c.team()) and tm[0] == c.char_id, 5, f'{lead.name} 把队长交给 {c.name}')
    t.say(f'[{c.name}] 当队长（{lead.name} 交过来）')


def one(name):
    c = t.Client(name)
    if w.item_count(w.read_bag(c.mem), ITEM):
        t.say(f'[{name}] 已经有第五元素')
        return
    take_lead(c)
    if c.world().map_id != 297:
        raise t.Stop(f'{name} 不在通天塔3号房（map {c.world().map_id}）')
    # the floor serves one role at a time: right after another role's vessel / 第五元素 it gives no dialog
    # (09:14-09:18 元素使03 / 04), so it is tried every FLOOR_RETRY s for up to FLOOR_WAIT s
    until = time.monotonic() + FLOOR_WAIT
    while True:
        hit = click_any(c, (FLOOR,), 4)
        if hit and '释放' in str(hit[1].options):
            break
        if time.monotonic() > until:
            raise t.Stop(f'{name} 地板 {FLOOR_WAIT}s 都没有「释放出元素精髓」: {hit and hit[1].options}')
        time.sleep(FLOOR_RETRY)
    c.game.select_dialog(1)
    t.say(f'[{name}] 释放出元素精髓，召唤魔法器皿')
    end, done = time.monotonic() + DEADLINE, set()
    while time.monotonic() < end:
        if w.item_count(w.read_bag(c.mem), ITEM):
            t.say(f'[{name}] 拿到第五元素')
            return
        time.sleep(3)
        hit = click_any(c, (FIFTH,) + VESSELS)
        if not hit:
            continue
        npc, d = hit
        opts = [(o, t.plain(l)) for o, l in d.options if o]
        if len(opts) != 1:
            continue                     # 「…大约1分钟」pages only offer 离开
        o, label = opts[0]
        if (npc, label) in done and npc != FIFTH:
            continue
        c.game.select_dialog(o)
        done.add((npc, label))
        t.say(f'[{name}] NPC {npc}「{label}」')
    raise t.Stop(f'{name} {DEADLINE}s 内没拿到第五元素')


if __name__ == '__main__':
    try:
        t.each(sys.argv[1:] or list(APPRENTICES), one)
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
