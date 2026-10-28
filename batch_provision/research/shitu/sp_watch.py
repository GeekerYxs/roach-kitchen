"""Measure the masters' 蓄力 (action-bar fill) in real battles, read-only (no injection, no packets).

    python -X utf8 research/shitu/sp_watch.py ROLE [ROLE ...]          appends to logs/sp_watch.csv until killed
    python -X utf8 research/shitu/sp_watch.py --report [csv]           per role: battles, median / mean seconds

Per battle and role: seconds from the in-battle flag going up to the role's 蓄力点 (fighter +0xF4) first going up
(= one 蓄力时间 plus the battle's opening; the opening is the same for everybody, so roles compare), the same for its
fighting pet, the battle length, and the live enemies at the start. The stat panel's 蓄力时间 (ANALYSIS.md: 5300 =
5.3 s per bar) is what this estimates.
"""
import csv
import statistics
import sys
import time
from pathlib import Path

from common import find_roles, module_base
from provisioner import world as w
from provisioner.memory import ProcessMemory

HERE = Path(__file__).resolve().parent
CSV = HERE / 'logs' / 'sp_watch.csv'
FIELDS = ['role', 'start', 'me_s', 'pet_s', 'battle_s', 'enemies', 'map_id']
TICK = 0.05


class Watch:
    def __init__(self, role, pid):
        self.role, self.mem = role, ProcessMemory(pid, module_base(pid))
        self.start = None

    def tick(self, now, out):
        st = w.read_world(self.mem)       # the battle object stays allocated between battles: use the flag
        if not st.in_battle:
            if self.start is not None:
                out.append(self.row(now))
                self.start = None
            return
        if self.start is None:
            self.start, self.me_s, self.pet_s, self.enemies = now, None, None, None
            self.me_sp0 = self.pet_sp0 = None
            self.map_id = st.map_id
        try:
            bt = w.read_battle(self.mem)
        except Exception:               # the battle object is being torn down
            return
        if bt is None:
            return
        if self.enemies is None and bt.enemies:
            self.enemies = len(bt.enemies)
        for who, f in (('me', bt.me), ('pet', bt.pet)):
            if f is None:
                continue
            sp0 = getattr(self, f'{who}_sp0')
            if sp0 is None:
                setattr(self, f'{who}_sp0', f.sp)
            elif f.sp > sp0 and getattr(self, f'{who}_s') is None:
                setattr(self, f'{who}_s', round(now - self.start, 2))

    def row(self, now):
        return {'role': self.role, 'start': round(self.start, 1), 'me_s': self.me_s, 'pet_s': self.pet_s,
                'battle_s': round(now - self.start, 1), 'enemies': self.enemies, 'map_id': self.map_id}


def watch(roles, path=CSV):
    path.parent.mkdir(exist_ok=True)
    new = not path.exists()
    ws = {}
    last_find = 0
    with open(path, 'a', encoding='utf-8', newline='') as f:
        wr = csv.DictWriter(f, FIELDS)
        if new:
            wr.writeheader()
        while True:
            now = time.time()
            if now - last_find > 30:             # windows come back after a relog
                for r, (pid, _) in find_roles(tuple(roles)).items():
                    if r not in ws or ws[r].mem.pid != pid:
                        ws[r] = Watch(r, pid)
                last_find = now
            out = []
            for r, wa in list(ws.items()):
                try:
                    wa.tick(now, out)
                except Exception:
                    del ws[r]
            for row in out:
                wr.writerow(row)
            if out:
                f.flush()
            time.sleep(TICK)


def report(path=CSV):
    by = {}
    with open(path, encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f):
            by.setdefault(r['role'], []).append(r)
    print(f'{"角色":12} 场数  师傅蓄力(中位/平均)  宠物蓄力(中位/平均)  每场秒数(中位)')
    for role, rs in by.items():
        me = [float(r['me_s']) for r in rs if r['me_s']]
        pet = [float(r['pet_s']) for r in rs if r['pet_s']]
        bs = [float(r['battle_s']) for r in rs]
        fmt = lambda v: f'{statistics.median(v):5.2f}/{statistics.mean(v):5.2f}' if v else '    -/    -'
        print(f'{role:12} {len(rs):4}  {fmt(me):>18}  {fmt(pet):>18}  {statistics.median(bs):6.1f}')


if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == '--report':
        report(Path(a[1]) if len(a) > 1 else CSV)
    else:
        watch(a)
