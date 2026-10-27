"""Take every 宝箱邮件 attachment and sell what it gave, in batches so the bag never overflows (user 18:4x, after doing
千万5 by hand while monitor.py recorded it).

    python -X utf8 research/shitu/mail_sell.py [--batch 12] 千万2 千万3 ...

Mail ids: the server sends one S->C 0x4411 per mail at login (<I char><I -1><B 0><I mail id><I 0><8×0><I template>
<…><date>), recorded on the role's tap; a mail is done once S->C 0x4416 <I char><I mail id>… came back.
Per mail, as the client did (18:36): C->S 0x01e5 <I char><I mail><I 0><I template> (select, answer 0x4412),
0x01e2 <I char><I mail><12×0><I template><H 1> (open, answer 0x4415), 0x01e3 <I char><I mail><I 0> (take, answer 0x4416
+ 0x4020 bag update). After each batch the role walks to 宠物商人小美 (NPC 329) and sells the tradable items the mails
added (factory.supply.ShopClient, 2.100 sell format). 千万5 by hand: 24 mails, 24 slots sold for 10,728 gold.
"""
import struct
import sys
import time
from collections import Counter

import trial_run as t
from factory.items import load_items
from factory.supply import PETSHOP, ShopClient
from monitor import Tap
from provisioner import log, world as w
from zhuanzhi_finish import walk

OP_SELECT, OP_OPEN, OP_TAKE = 0x01E5, 0x01E2, 0x01E3


def pending(c):
    mails, done = {}, set()
    for _, d, op, b, _ in Tap(c.pid, from_end=False).poll():
        if op == 0x4411 and len(b) >= 29:
            mails[struct.unpack_from('<I', b, 9)[0]] = struct.unpack_from('<I', b, 25)[0]
        elif op == 0x4416 and len(b) >= 8:
            done.add(struct.unpack_from('<I', b, 4)[0])
    return [(m, tpl) for m, tpl in mails.items() if m not in done]


def counts(c):
    k = Counter()
    for s in w.read_bag(c.mem):
        k[s.item_id] += s.quantity
    return k


def take(c, tap, mail, tpl):
    cid = c.char_id
    c.game.send(OP_SELECT, struct.pack('<IIII', cid, mail, 0, tpl))
    time.sleep(0.2)
    c.game.send(OP_OPEN, struct.pack('<II12sIH', cid, mail, bytes(12), tpl, 1))
    time.sleep(0.2)
    c.game.send(OP_TAKE, struct.pack('<III', cid, mail, 0))
    end = time.monotonic() + 5
    while time.monotonic() < end:
        for _, d, op, b, _ in tap.poll():
            if op == 0x4416 and len(b) >= 8 and struct.unpack_from('<I', b, 4)[0] == mail:
                return True
        time.sleep(0.1)
    return False


def sell_new(c, before, items):
    gained = counts(c) - before
    slots = [s for s in w.read_bag(c.mem) if gained[s.item_id] > 0 and s.item_id in items and items[s.item_id].tradable]
    if not slots:
        return 0, 0
    walk(c, 1, (1338, 1155), '宠物商人小美')
    gold = w.read_gold(c.mem)
    shop = ShopClient(c.game, c.mem, log.for_account(c.name))
    sold = shop.sell(PETSHOP, slots)
    shop.close()
    return sold, w.read_gold(c.mem) - gold


def run(name, batch, items):
    c = t.Client(name)
    todo = pending(c)
    t.say(f'[{name}] 待提取 {len(todo)} 封，背包 {len(w.read_bag(c.mem))}/{w.read_bag_capacity(c.mem)}，金币 {w.read_gold(c.mem)}')
    total_gold, taken, failed = 0, 0, []
    rnd = 0
    while todo:
        free = w.read_bag_capacity(c.mem) - len(w.read_bag(c.mem))
        part, todo = todo[:min(batch, free - 1)], todo[min(batch, free - 1):] if free > 1 else todo
        if not part:
            t.say(f'[{name}] 背包只剩 {free} 格，停（还剩 {len(todo)} 封）')
            break
        rnd += 1
        before = counts(c)
        tap = Tap(c.pid, from_end=True)
        tap.ready()
        for mail, tpl in part:
            if take(c, tap, mail, tpl):
                taken += 1
            else:
                failed.append(mail)
            time.sleep(0.2)
        got = counts(c) - before
        sold, gold = sell_new(c, before, items)
        total_gold += gold
        t.say(f'[{name}] 第 {rnd} 批 {len(part)} 封：拿到 {dict((items[k].name if k in items else k, v) for k, v in got.items())}；'
              f'卖 {sold} 格 +{gold}')
    t.say(f'[{name}] 共提取 {taken} 封' + (f'，失败 {failed}' if failed else '') + f'，卖得 {total_gold}，金币 {w.read_gold(c.mem)}，'
          f'背包 {len(w.read_bag(c.mem))}/{w.read_bag_capacity(c.mem)}，还剩 {len(pending(c))} 封')


if __name__ == '__main__':
    args = sys.argv[1:]
    batch = 12
    if args[:1] == ['--batch']:
        batch, args = int(args[1]), args[2:]
    log.setup(t.HERE / 'logs', prefix='mail_sell')
    table = load_items()
    for n in args:
        run(n, batch, table)
