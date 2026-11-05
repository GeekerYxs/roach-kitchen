"""Read-only live monitor for an active run_level_to_70.py process; survives a client that is offline for a moment."""
import _bootstrap  # noqa: F401
import os
import time
from datetime import datetime
from pathlib import Path

import trial_run as t
from common import APPRENTICES
from line.ops import read_exp
from provisioner import world as w

LEADER = os.environ["SHITU_LEADER"]
ROLES = (LEADER,) + tuple(APPRENTICES)
RUNTIME = Path(__file__).with_name("runtime")
RUNTIME.mkdir(exist_ok=True)
LOG = RUNTIME / f"level_monitor_{datetime.now():%Y%m%d_%H%M%S}.log"


def say(message):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def sample(name, c):
    st, bag, team, battle = c.world(), w.read_bag(c.mem) or (), w.read_team(c.mem), w.read_battle(c.mem)
    return {
        "lv": w.read_level(c.mem), "exp": read_exp(c.mem),
        "map": st.map_id if st else None, "xy": (round(st.x), round(st.y)) if st else None,
        "battle": st.in_battle if st else None,
        "dead": bool(battle and battle.me and battle.me.dead),
        "pet_dead": bool(battle and battle.pet and battle.pet.dead),
        "team": team.members if team else (),
        "scroll": w.item_count(bag, 9801),
        "soda": w.item_count(bag, 8456) if name == LEADER else None,
        "sweet": w.item_count(bag, 8573) if name == LEADER else None,
    }


OFFLINE = {"lv": None, "exp": None, "map": None, "xy": None, "battle": None, "dead": False, "pet_dead": False,
           "team": (), "scroll": None, "soda": None, "sweet": None}


def main():
    clients = {}
    previous, previous_levels, previous_at = {}, {}, time.monotonic()
    say(f"只读监控启动；日志 {LOG}")
    while True:
        now = time.monotonic()
        data, offline = {}, []
        for name in ROLES:
            try:
                c = clients.get(name) or clients.setdefault(name, t.Client(name))
                data[name] = sample(name, c)
            except Exception as exc:          # client restarting / logged out: report it, keep monitoring
                clients.pop(name, None)
                data[name] = dict(OFFLINE)
                offline.append(f"{name}: {exc!r}")
        expected = {c.char_id for c in clients.values()}
        try:
            roster = set(clients[LEADER].team()) if LEADER in clients else set()
        except Exception:
            roster = set()
        lv = {n: data[n]["lv"] for n in APPRENTICES}
        xp_rate = {}
        elapsed = max(now - previous_at, 1)
        for n in APPRENTICES:
            if previous.get(n) is not None and data[n]["exp"] is not None and previous_levels.get(n) is not None:
                if data[n]["lv"] == previous_levels[n]:
                    xp_rate[n] = round((data[n]["exp"] - previous[n]) * 3600 / elapsed)
                else:
                    xp_rate[n] = "level-up"
        locations = {n: (data[n]["map"], data[n]["xy"]) for n in ROLES}
        dead = [n for n, d in data.items() if d["dead"] or d["pet_dead"]]
        message = (f"levels={lv} XP/hr~={xp_rate} maps={locations} team={len(roster)}/{len(expected)} "
                   f"dead={dead} leader_soda={data[LEADER]['soda']} leader_sweets={data[LEADER]['sweet']} "
                   f"scrolls=" + str({n: data[n]["scroll"] for n in ROLES}) +
                   (f" OFFLINE={offline}" if offline else ""))
        say(message)
        previous = {n: data[n]["exp"] for n in APPRENTICES}
        previous_levels = {n: data[n]["lv"] for n in APPRENTICES}
        previous_at = now
        if all(v is not None for v in lv.values()) and min(lv.values()) >= 70:
            say(f"全部小号达到70，监控结束：{lv}")
            return
        time.sleep(60)


if __name__ == "__main__":
    main()
