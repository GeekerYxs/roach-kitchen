"""禁锢 team: sell the sell_list.py items at 钱德勒 (NPC 2609, map 181 (354,1725), 不坑里坑谁杂货店; options
1 购买杂货 / 2 出售物品, live 2026-10-29). Run where each role already stands next to him (the leader walked the
team over; no role walks here).

    python -X utf8 research/jingu/sell.py 自由三号 ...
"""
import logging
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'shitu'))

import trial_run as t                       # noqa: E402  (puts batch_provision/ on sys.path)
from factory import items as fi             # noqa: E402
from factory.supply import ShopClient       # noqa: E402
from provisioner import world as w          # noqa: E402
from sell_list import to_sell               # noqa: E402

SHOP = SimpleNamespace(npc=2609, name='钱德勒', sell_option=2, buy_option=1)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', datefmt='%H:%M:%S')


def sell(name, table):
    c = t.Client(name)
    shop = ShopClient(c.game, c.mem, logging.getLogger(name))
    plan = to_sell(w.read_bag(c.mem), table)
    gold = w.read_gold(c.mem)
    if plan:
        try:
            n = shop.sell(SHOP, [s for s, _ in plan])
        finally:
            shop.close()
    else:
        n = 0
    left = to_sell(w.read_bag(c.mem), table)
    t.say(f'[{name}] 卖了 {n}/{len(plan)} 格，金币 +{w.read_gold(c.mem) - gold}，还剩 '
          f'{[(table[s.item_id].name, s.quantity) for s, _ in left]}')


if __name__ == '__main__':
    table = fi.load_items()
    for name in sys.argv[1:]:
        sell(name, table)
        time.sleep(1)
