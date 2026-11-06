"""5-man boss-gear line, step 2: the leader takes 让鹰王倒下 (quest 1130, lv58) from 莫吉 in 荒芜之地1区.

    python -X utf8 take_eagle.py

Live 2026-11-06 12:5x: from the PP鸡 landing (1916,870) the leader clicks 莫吉 (NPC 2503 at (1914,921), ResLib
NPCDirection) without walking. Menu: ☆让鹰王倒下(58）-> 也许吧，请指教。-> riddle「你该怎么对付这样的对手？」: the right
answer is「打败他，让他生不如死。」-> 不错，哈哈 -> 没问题。-> 好的，等着我的好消息吧！ The leader accepting gave quest 1130
to all five team members at once (user 2026-11-06 said so; read_quest on all five confirmed it).
Next: 独眼鹰王 hides in a 琉璃瓶 in 陷阱囚牢; 大风 / 荒土 / 烈火 结晶 from the right bottles (3 / 4 / 3 of each kind).
"""
import struct
import time

from _bootstrap import LEADER, ROLES

import trial_run as t
from provisioner import world as w
from r4_util import close_dialogs
from take224 import talk

QUEST = 1130
MOJI = 2503
DESERT_1 = 180
STEPS = ['让鹰王倒下', '请指教', '生不如死', '跟我想的差不多', '没问题', '好消息']
# tap_281960.jsonl 2026-11-06 (the hand-clicked accept): 0x50 <I 0><I 2503> then 0x51 <I 0><I opt><I 0> with
# opt 5 (☆让鹰王倒下) 2 (请指教) 1 (生不如死) 1 1 1 — the same requests factory/supply.ShopClient sends for a shop
OP_CLICK_NPC, OP_DIALOG = 0x50, 0x51
PACKET_OPTS = (5, 2, 1, 1, 1, 1)
PACKET_GAP = 0.3


def by_packet(lead):
    lead.game.send(OP_CLICK_NPC, struct.pack('<II', 0, MOJI))
    for opt in PACKET_OPTS:
        time.sleep(PACKET_GAP)
        lead.game.send(OP_DIALOG, struct.pack('<III', 0, opt, 0))


def missing(cs):
    return [c.name for c in cs if not (q := w.read_quest(c.mem, QUEST)) or not q.active]


def main():
    cs = [t.Client(n) for n in ROLES]
    lead = cs[0]
    if not missing(cs):
        t.say('五人都已经接了「让鹰王倒下」，跳过')
        return
    if lead.world().map_id != DESERT_1:
        raise t.Stop(f'{LEADER} 不在荒芜之地1区（map {lead.world().map_id}），先跑 go_desert1.py')
    if set(lead.team()) != {c.char_id for c in cs}:
        raise t.Stop(f'队伍不完整: {lead.team()}，先跑 go_desert1.py')
    close_dialogs([lead])
    by_packet(lead)
    try:
        t.wait(lambda: not missing(cs), 3, '五人接到任务 1130（发包）')
    except t.Stop:
        t.say(f'发包后还没接到: {missing(cs)}，改用看着菜单一页页选')
        close_dialogs([lead])
        time.sleep(1)
        talk(lead, MOJI, STEPS)
        t.wait(lambda: not missing(cs), 5, '五人接到任务 1130')
    t.say('五人都接到了「让鹰王倒下」（任务 1130）')


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
