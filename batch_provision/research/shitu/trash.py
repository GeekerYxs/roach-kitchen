"""What the apprentices never keep (user 2026-11-05), dropped out of battle, and their weapons sold at home.

  trash   碧玉葫芦 / 黄玉葫芦 / 紫金红葫芦 (辅助品 31801-31803), 特赦令 (32068, marked important in ItemLib: if the
          server refuses the drop it is logged), every 整人道具 (types 0x802 / 0x803, drop_prank.py)
  when    every TRASH_EVERY s in the leveling / walking loops (Trasher: well10, lunhui15, maze_train and all its
          walkers), right after each opened pack (open_packs), and at every home() (at_home)
  weapons the 勇者 line's apprentices own none (sell_tradable --weapons): at every home() the ones in the bag are sold
          at 宠物商人小美, where the 回城卷 lands (SHITU_JOB 战士 only; never a master)

Only for the 师徒 line: plan.Batch.env sets SHITU_TRASH=1. Other users of these shared scripts (projects/fullcrit_mage
_leveling_70 calls r4_util.home and maze_train with its own team) keep their bags and weapons as before.

Drop = 0x0048 <I 0><B 0><B bag slot><H quantity> (drop_prank.py). A drop sent in a battle is ignored (2026-10-28
亿万14), so nothing is dropped while the role is in one.
"""
import os
import struct
import time

import trial_run as t
from provisioner import world as w

OP_DROP = 0x48
PRANK = (0x802, 0x803)
NAMES = ('碧玉葫芦', '黄玉葫芦', '紫金红葫芦', '特赦令')
TRASH_EVERY = 1200.0            # s: user 2026-11-05「暂定每20分钟检查一次」
WEAPON = 0x103

_items = None


def enabled():
    return os.environ.get('SHITU_TRASH') == '1'


def items():
    global _items
    if _items is None:
        from factory.items import load_items
        _items = load_items()
    return _items


def is_trash(it):
    return it is not None and (it.type in PRANK or any(n in it.name for n in NAMES))


def drop(c, table=None, check=True):
    """Drop every trash stack c holds, unless c is in a battle. check: look again 1 s later and log what stayed.
    -> the names sent."""
    table = table or items()
    st = c.world()
    if st is None or st.in_battle:
        return []
    sent = []
    for s in w.read_bag(c.mem):
        it = table.get(s.item_id)
        if is_trash(it):
            c.game.send(OP_DROP, struct.pack('<IBBH', 0, 0, s.slot, s.quantity))
            sent.append((s, it.name))
    if not sent:
        return []
    if check:
        time.sleep(1.0)
        left = {(x.slot, x.item_id) for x in w.read_bag(c.mem)}
        stuck = [n for s, n in sent if (s.slot, s.item_id) in left]
        t.say(f'[{c.name}] 丢掉 {[n for _, n in sent]}' + (f'；丢不掉: {stuck}' if stuck else ''))
    else:
        t.say(f'[{c.name}] 丢掉 {[n for _, n in sent]}')
    return [n for _, n in sent]


class Trasher:
    """In a loop: each apprentice drops its trash every TRASH_EVERY s, out of battle (no wait, no extra reads when it
    is not due)."""
    def __init__(self, cs, every=TRASH_EVERY):
        self.cs, self.every = list(cs), every
        self.due = {c.name: 0.0 for c in self.cs}

    def tick(self, sts, now):
        if not enabled():
            return
        for c in self.cs:
            st = sts.get(c.name)
            if st is None or st.in_battle or now < self.due[c.name]:
                continue
            self.due[c.name] = now + self.every
            try:
                drop(c, check=False)
            except Exception as e:          # never break the leveling for the trash
                t.say(f'[{c.name}] 丢东西出错: {e!r}')


def at_home(cs, masters=()):
    """home(): every apprentice in 逍遥村 drops its trash and (勇者 line) sells the weapons in its bag, all at once."""
    if not enabled():
        return
    brave = os.environ.get('SHITU_JOB', '战士') == '战士'

    def one(c):
        if c.name in masters or c.world().map_id != 1:
            return
        drop(c)
        if brave:
            sell_weapons(c)
    t.each([c.name for c in cs], lambda n: one(next(c for c in cs if c.name == n)))


def sell_weapons(c):
    """The weapons in c's bag (tradable, type 0x103) sold at 小美, the worn one taken off first; nothing when none."""
    import sell_tradable as st
    table = items()
    nm = lambda i: table[i].name if i in table else str(i)        # noqa: E731
    worn = [e for e in (w.read_equipment(c.mem) or ()) if e.slot == st.WEAPON_SLOT]
    bag = [s for s in w.read_bag(c.mem) if (it := table.get(s.item_id)) and it.type == WEAPON and it.tradable]
    if not worn and not bag:
        return
    if worn:
        st.unequip_weapon(c, nm)
        bag = [s for s in w.read_bag(c.mem) if (it := table.get(s.item_id)) and it.type == WEAPON and it.tradable]
    if not bag:
        return
    st.walk(c, 1, (1338, 1155), '宠物商人小美')
    shop = st.ShopClient(c.game, c.mem, st.log.for_account(c.name))
    sold = shop.sell(st.PETSHOP, bag)
    shop.close()
    t.say(f'[{c.name}] 回城卖武器 {sold}/{len(bag)}: {[nm(s.item_id) for s in bag]}')
