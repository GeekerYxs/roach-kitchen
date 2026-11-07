"""What the apprentices never keep (user 2026-11-05), dropped out of battle, and their weapons sold at home.

  trash   every name in data/drop_names.txt (user 2026-11-07: a file the user adds names to, e.g. 锁住的藏宝盒), matched
          EXACTLY (the old substring match took 超级特赦令 / 特赦令牌 along with 特赦令), plus every 整人道具 (types
          0x802 / 0x803, drop_prank.py). A name not in ItemLib, or one that is protected (important, 任务品, 任务触发道具,
          宠物卡片, equipment, the line's supplies) is skipped with a warning unless written as !name.
  check   python -X utf8 research/shitu/trash.py --list            the name file as read (warnings), no game
          python -X utf8 research/shitu/trash.py --check A B ...   what would be dropped from A, B, nothing sent
  log     every drop sent: logs/drop_log.tsv (time, role, map, slot, item id, name, qty, result)
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
from pathlib import Path

import keep_items
import trial_run as t
from provisioner import world as w

OP_DROP = 0x48
PRANK = (0x802, 0x803)
HERE = Path(__file__).resolve().parent
NAMES_FILE = HERE / 'data' / 'drop_names.txt'
DROP_LOG = HERE / 'logs' / 'drop_log.tsv'
GUARD_TYPES = {0x2000: '任务品', 0x824: '任务触发道具', 0x820: '宠物卡片'}
EQUIP = range(0x101, 0x119)                  # factory.items.EQUIP_TYPES
SUPPLY = {9801, 8454, 8404, 8573}            # 回城卷, 健康果汁, 心情便当, 甜点 (master_supply)
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


def parse(text):
    """[(name, forced)] from the name file: one name a line, # comments, !name = protected but dropped anyway."""
    out = []
    for line in text.splitlines():
        line = line.split('#', 1)[0].strip()
        if line:
            out.append((line[1:].strip(), True) if line.startswith('!') else (line, False))
    return out


def guard(item_id, it):
    """Why this item is protected from a name drop, or None."""
    if getattr(it, 'important', False):
        return '重要物品'
    if it.type in GUARD_TYPES:
        return GUARD_TYPES[it.type]
    if it.type in EQUIP:
        return '装备'
    if item_id in SUPPLY:
        return '补给品'
    if keep_items.kept(it):
        return '通关钥匙 / 温泉消费券'
    return None


STONE_TYPE = 2081                 # ItemLib type of the 技能石-xx系-yyyN级 stones (499 of them; 混沌技能石 is another type)
RECIPE_TYPE = 0x823                # 配方: 848 of them, named like gear (影·猛袭头罩 ...), so matched by TYPE only
KINDS = {'@技能石': '所有技能石（技能石-开头，不含标了重要的）', '@配方': '所有配方（物品类型 配方，不含标了重要的）'}


def is_stone(it):
    """A skill stone by type + name prefix, not an important one (user 2026-11-07: write @技能石 to drop all)."""
    return it.type == STONE_TYPE and it.name.startswith('技能石-') and not getattr(it, 'important', False)


def is_recipe(it):
    """A recipe item by type (user 2026-11-07: write @配方 to drop all), not an important one."""
    return it.type == RECIPE_TYPE and not getattr(it, 'important', False)


def check_names(entries, table):
    """(names to drop, warnings): exact ItemLib names only; protected ones only when forced. @kind lines = a whole kind."""
    by_name = {}
    for i, it in table.items():
        by_name.setdefault(it.name, []).append((i, it))
    names, warn = set(), []
    for name, forced in entries:
        if name.startswith('@'):
            if name in KINDS:
                names.add(name)
            else:
                warn.append(f'「{name}」不认识；可用的整类写法: {sorted(KINDS)}')
            continue
        hits = by_name.get(name)
        if not hits:
            warn.append(f'「{name}」物品表里没有（错别字？），不丢')
            continue
        why = [g for i, it in hits if (g := guard(i, it))]
        if why and not forced:
            warn.append(f'「{name}」是{why[0]}，不丢；确定要丢就写成 !{name}')
            continue
        names.add(name)
    return names, warn


_names = (None, frozenset())                 # (file mtime, names): re-read when the user edits the file


def names(path=None, say=None):
    """The validated drop names, re-read whenever the file changed (warnings logged then)."""
    global _names
    path = Path(path or NAMES_FILE)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return frozenset()
    if _names[0] != mtime:
        got, warn = check_names(parse(path.read_text(encoding='utf-8')), items())
        for m in warn:
            (say or t.say)(f'丢弃名单报警：{m}')
        _names = (mtime, frozenset(got))
    return _names[1]


def is_named(it):
    """In data/drop_names.txt (junk_watch.py: every role, no 整人道具 by type)."""
    if it is None:
        return False
    got = names()
    return it.name in got or ('@技能石' in got and is_stone(it)) or ('@配方' in got and is_recipe(it))


def is_trash(it):
    return it is not None and (it.type in PRANK or is_named(it))


def log_drops(role, map_id, rows, path=None):
    """rows: (slot, item id, name, qty, result) appended to logs/drop_log.tsv."""
    path = Path(path or DROP_LOG)
    path.parent.mkdir(exist_ok=True)
    new = not path.exists()
    stamp = time.strftime('%Y-%m-%d %H:%M:%S')
    with path.open('a', encoding='utf-8') as f:
        if new:
            f.write('时间\t角色\t地图\t格\t物品号\t物品\t数量\t结果\n')
        for slot, item_id, name, qty, result in rows:
            f.write(f'{stamp}\t{role}\t{map_id}\t{slot}\t{item_id}\t{name}\t{qty}\t{result}\n')


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
    left = set()
    if check:
        time.sleep(1.0)
        left = {(x.slot, x.item_id) for x in w.read_bag(c.mem)}
        stuck = [n for s, n in sent if (s.slot, s.item_id) in left]
        t.say(f'[{c.name}] 丢掉 {[n for _, n in sent]}' + (f'；丢不掉: {stuck}' if stuck else ''))
    else:
        t.say(f'[{c.name}] 丢掉 {[n for _, n in sent]}')
    result = (lambda s: '丢不掉' if (s.slot, s.item_id) in left else '已丢') if check else (lambda s: '已发')
    try:
        log_drops(c.name, getattr(st, 'map_id', ''), [(s.slot, s.item_id, n, s.quantity, result(s)) for s, n in sent])
    except OSError as e:
        t.say(f'[{c.name}] 丢弃记录写不进去: {e!r}')
    return [n for _, n in sent]


def preview(c, table=None):
    """What drop(c) would send now, nothing sent: [(slot, name, qty)]."""
    table = table or items()
    return [(s.slot, table[s.item_id].name, s.quantity) for s in w.read_bag(c.mem) if is_trash(table.get(s.item_id))]


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


def main(argv):
    if argv[:1] == ['--list']:
        got = names(say=print)
        print(f'名单 {NAMES_FILE}：会丢 {sorted(got)}；另外整人道具按类型丢')
    elif argv[:1] == ['--check'] and argv[1:]:
        got = names()
        for n in argv[1:]:
            rows = preview(t.Client(n))
            t.say(f'[{n}] 试运行（不丢）：' + ('；'.join(f'第 {a} 格 {b}x{q}' for a, b, q in rows) if rows else '没有要丢的'))
        t.say(f'名单：{sorted(got)} + 整人道具')
    else:
        raise SystemExit(__doc__)


if __name__ == '__main__':
    import sys
    try:
        main(sys.argv[1:])
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
