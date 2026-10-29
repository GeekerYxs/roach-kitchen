"""Read-only drop log for the 禁锢 team: every INTERVAL s read each role's bag; while the role is in the farm map, any
item whose total count went up is a drop. Decreases (hand-ins, sales, potions drunk) are ignored. Appends to
research/jingu/logs/drops.csv and prints a summary (item, total, per hour) every SUMMARY s and at the end.

    python -X utf8 research/jingu/drops.py [hours=8] 波大臀圆 曾经不曾 自由一号 自由二号 自由三号
"""
import csv
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from expwatch.__main__ import find_pids, module_base      # noqa: E402
from factory import items as fi                            # noqa: E402
from provisioner import world                              # noqa: E402
from provisioner.memory import ProcessMemory               # noqa: E402

FARM_MAP = 1202
INTERVAL, SUMMARY = 30, 1800
OUT = Path(__file__).resolve().parent / 'logs' / 'drops.csv'


def totals(bag):
    c = Counter()
    for s in bag:
        c[s.item_id] += s.quantity
    return c


def gains(before, after):
    """{item: +n} for the items whose count rose."""
    return {i: n - before.get(i, 0) for i, n in after.items() if n > before.get(i, 0)}


def main(hours, roles):
    table = fi.load_items()
    pids = find_pids(roles)
    mems = {r: ProcessMemory(p, module_base(p)) for r, p in pids.items()}
    last, farm_secs, got = {}, Counter(), Counter()
    OUT.parent.mkdir(exist_ok=True)
    end, next_sum = time.time() + hours * 3600, time.time() + SUMMARY
    with open(OUT, 'a', newline='', encoding='utf-8') as f:
        out = csv.writer(f)
        while time.time() < end:
            t = time.time()
            for r, mem in mems.items():
                try:
                    w, bag = world.read_world(mem), world.read_bag(mem)
                except Exception as e:                  # window closed / relogging
                    print(f'{r}: 读不到 {e}', flush=True)
                    last.pop(r, None)
                    continue
                if w is None or bag is None or w.map_id != FARM_MAP:
                    last.pop(r, None)                   # outside the farm: the next reading starts fresh
                    continue
                now = totals(bag)
                if r in last:
                    farm_secs[r] += t - last[r][0]
                    for item, n in gains(last[r][1], now).items():
                        name = table[item].name if item in table else str(item)
                        out.writerow([round(t), r, item, name, n])
                        got[(item, name)] += n
                last[r] = (t, now)
            f.flush()
            if time.time() >= next_sum:
                summary(got, farm_secs)
                next_sum += SUMMARY
            time.sleep(max(0.0, INTERVAL - (time.time() - t)))
    summary(got, farm_secs)


def summary(got, farm_secs):
    hours = sum(farm_secs.values()) / 3600      # role-hours in the farm map
    print(f'--- {time.strftime("%H:%M")} 在图里共 {hours:.2f} 号·小时', flush=True)
    for (item, name), n in got.most_common():
        print(f'  {item} {name}: {n}（每号每小时 {n / hours:.1f}）' if hours else f'  {item} {name}: {n}', flush=True)


if __name__ == '__main__':
    a = sys.argv[1:]
    hrs = float(a.pop(0)) if a and a[0].replace('.', '').isdigit() else 8
    main(hrs, a)
