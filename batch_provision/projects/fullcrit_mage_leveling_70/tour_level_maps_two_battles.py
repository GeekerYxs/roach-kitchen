"""Tour the 11 user-directed level 1-70 maps, stopping after exactly two battles on each map.

The user explicitly asked to assume every apprentice is ready to change maps after two fights. This is a route
verification run, not a claim that two fights actually level a character to the next threshold. The four apprentices
remain silent; only the 方士 captain and its pet fight. A captain with zero 劲爆汽水 immediately breaks off and
returns the party to town.
"""
import _bootstrap  # noqa: F401
import maze_train as m
import pp_chain
import trial_run as t
from common import APPRENTICES, MASTERS
from lunhui15 import LEADER
from provisioner import world as w
import sys

import home_supply
from policy import LADDER
from route import ROUTES

SODA_ID, SWEET_ID = 8456, 8573
ROLES = (LEADER,) + APPRENTICES


def say(msg):
    t.say(f'[{LEADER}] {msg}')


def count(c, item_id):
    return w.item_count(w.read_bag(c.mem) or (), item_id)


class SodaGuardCaster(m.Caster):
    def tick(self, now):
        if self.c.name == LEADER and count(self.c, SODA_ID) == 0:
            raise t.Stop('队长劲爆汽水为0，立即结束巡逻并全队回城')
        return super().tick(now)


# Kept for callers that imported these from here; the single implementation is home_supply.
top_up_scrolls_at_home = home_supply.top_up_scrolls_at_home
top_up_master_sweets_at_home = home_supply.top_up_master_sweets_at_home


def home_between_maps():
    home_supply.home_and_restock(ROLES)


def install_stage(name, maze, legs, patrol_a=None, patrol_b=None):
    m.CASTERS = (LEADER,)
    m.Caster = SodaGuardCaster
    m.STAGES = (dict(name=name, maze=maze, until=None, patrol_a=patrol_a,
                     patrol_b=patrol_b, legs=legs, battle_limit=2,
                     done_when=lambda: count(t.Client(LEADER), SODA_ID) == 0),)
    say(f'前往 {name}（map {maze}），完成两场即切图')
    m.main()


def run_stage(name, maze, legs, patrol_a=None, patrol_b=None, pp=None, via=()):
    if pp:
        pp_chain.main(pp, list(via))
    install_stage(name, maze, legs, patrol_a, patrol_b)


def run_prison():
    import ruin_east_to_prison as prison

    cs = {n: t.Client(n) for n in ROLES}
    prison.home_and_fly(cs)
    install_stage('惊魂监狱', 264,
                  {24: ('click', 1339, (5660, 3258))},
                  (2369, 2000), (1000, 2900))


def route_stages():
    """The user-directed no-task leveling route (route.ROUTES, in policy.LADDER order)."""
    return [(name,) + ROUTES[name] for name, _map, _until in LADDER]


def run_route(first_stage=1):
    if len(APPRENTICES) != 4 or len(MASTERS) != 1:
        raise t.Stop('这条路线要求一名队长带四个小号（见 team.toml）')
    if first_stage < 1 or first_stage > 11:
        raise t.Stop(f'续跑起始图编号超界: {first_stage}（合法范围 1..11）')
    for index, (name, maze, legs, a, b, pp, via) in enumerate(route_stages(), start=1):
        if index < first_stage:
            continue
        if name == '惊魂监狱':
            run_prison()
        else:
            run_stage(name, maze, legs, a, b, pp=pp, via=via)
        if index != 11:
            home_between_maps()


def main():
    first_stage = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    home_between_maps()
    run_route(first_stage)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        try:
            lead = t.Client(LEADER)
            if lead.world().nav_active:
                lead.game.cancel_navigation()
        except Exception:
            pass
        say('收到停止指令，已取消队长寻路')
    except t.Stop as exc:
        lead = t.Client(LEADER)
        if lead.world().nav_active:
            lead.game.cancel_navigation()
        say(f'停止：{exc}')
        if count(lead, SODA_ID) == 0 and any(t.Client(n).world().map_id not in (1, 8) for n in ROLES):
            from line.ops import home_village
            home_village()
        raise SystemExit(1)
