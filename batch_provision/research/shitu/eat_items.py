"""Use (eat) every bag item whose name contains one of the words, one use_item at a time, each checked by the count.

    python -X utf8 research/shitu/eat_items.py --name 幸运丸 --name 小酒池 ... 千万1 千万2 ...

User, round 3 (12:2x): eat all 幸运丸 / 酒池肉林 / 加钙地瓜 / 地沟果奶 / 心脏起搏器. A use that does not lower the count
within WAIT seconds is logged and that item is skipped (no retry loop).
"""
import sys
import time

import trial_run as t
from factory.items import load_items
from monitor import Tap, texts
from provisioner import world as w

WAIT, GAP = 4.0, 0.6


def run(name, items, words):
    c = t.Client(name)
    tap = Tap(c.pid, from_end=True)
    tap.ready()
    tap.poll()
    eaten, skipped = {}, set()
    while True:
        bag = w.read_bag(c.mem)
        todo = [s for s in bag if s.item_id in items and s.item_id not in skipped
                and any(x in items[s.item_id].name for x in words)]
        if not todo:
            break
        s = todo[0]
        nm, before = items[s.item_id].name, w.item_count(bag, s.item_id)
        c.game.use_item(s.slot)
        try:
            t.wait(lambda: w.item_count(w.read_bag(c.mem), s.item_id) < before, WAIT, f'{name} 吃 {nm}')
            eaten[nm] = eaten.get(nm, 0) + 1
        except t.Stop:
            msgs = [' '.join(texts(b)) for _, d, op, b, _ in tap.poll() if d == 'S->C' and op == 0x46ff]
            t.say(f'[{name}] {nm} 吃不下（还剩 {before}），服务器: {msgs[-3:]}')
            skipped.add(s.item_id)
        time.sleep(GAP)
    t.say(f'[{name}] 吃了 {eaten}；没吃掉 {[items[i].name for i in skipped]}；背包 {len(w.read_bag(c.mem))}/40')


if __name__ == '__main__':
    table = load_items()
    args, words = sys.argv[1:], []
    while '--name' in args:
        i = args.index('--name')
        words.append(args[i + 1])
        del args[i:i + 2]
    try:
        for n in args:
            run(n, table, tuple(words))
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
