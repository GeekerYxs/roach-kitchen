"""禁锢之地 crystal farm loop for one team (user 2026-10-29): the leader walks the team everywhere, nobody walks alone.

    python -X utf8 research/jingu/farm.py --minutes 10 --cycles 1     (test: one 10-minute stint, then sell + hand in)
    python -X utf8 research/jingu/farm.py [--first-minutes 5]          (the night: go in, farm until a bag is full,
                                                                        out, sell, hand in, back in; until the
                                                                        暗影之力的庇佑 runs out, research/jingu/buff.py)

Cycle:
  1. team up: the leader walks to whoever is not in the team and invites it (turnin.invite)
  2. the leader walks the team to 禁锢之地 NPC 10184, map 181 (3123,2583) (ResLib; player doc stands at (3114,2637)),
     picks 「传送至 禁锢之地-次元时空Ⅱ」 -> map 1202. The team's 暗影之力的庇佑 is buff 1902 = 次元时空Ⅱ
     (Gemini session e45999df, read from session+0x1D264); the buff map must match or nothing drops.
  3. the leader patrols A (3350,3350) <-> B (3700,3650) (user's (3400,3430)/(3607,3587) rounded + widened); the
     followers fight along. Stop when any bag has <= FREE_MIN free slots, the stint time is up, or the night is over.
  4. out: the leader walks the team onto the exit EXIT (9024,5916) = NPC 11132 荒芜之地2区 in the server's 0x40a0
     spawn list of 1202 (u16 x,y at the end of the entry); standing on it carries the whole team (still in the
     team) to 181 (3114,2637), verified 2026-10-29 01:17. 飞鞋 (1 h cooldown) is only a spare, never used here.
  5. sell first (钱德勒, research/jingu/sell.py rules), THEN hand in (银狐王勇, turnin.py): the hand-in gives
     勋章, which needs bag room (user).
"""
import argparse
import math
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'shitu'))

import trial_run as t                       # noqa: E402  (puts batch_provision/ on sys.path)
import turnin                               # noqa: E402
import sell                                 # noqa: E402
from buff import shadow_left                # noqa: E402
from factory import items as fi             # noqa: E402
from provisioner import world as w          # noqa: E402

LEADER = '波大臀圆'
MEMBERS = ('自由一号', '自由二号', '自由三号', '曾经不曾')
TOWN = 181
GATE_NPC, GATE_STAND = 10184, (3123, 2630)
GATE_PICK = '次元时空Ⅱ'
FARM = 1202
PATROL = ((3350, 3350), (3700, 3650))        # user's (3400,3430)/(3607,3587), rounded and a bit wider
SHOE_POINT = (648, 1716)
EXIT = (9024, 5916)
SHOP_STAND = (390, 1760)                    # 钱德勒 2609 at (354,1725)
NPC_STAND = turnin.STAND                    # 银狐王勇 2603
FREE_MIN = 2                                # a bag this full -> go out
ARRIVE = 40
TURN = 30                                   # px before a patrol point: already head for the other one
                                            # (80 cut the walk to (3452,3442)-(3602,3562), measured 01:39)
STILL = 0.5                                 # s standing still out of battle -> walk again


def bag_free(c):
    return w.read_bag_capacity(c.mem) - len(w.read_bag(c.mem))


def walk_team(lead, xy, near=60, timeout=600, stop=None):
    """The leader walks (with the team) to xy on its map; battles pause it, a stalled walk is re-sent.
    stop() -> reason ends the walk early (returned); None when arrived."""
    end, sent, moved_at, last_xy = time.monotonic() + timeout, 0.0, time.monotonic(), None
    while time.monotonic() < end:
        if stop and (why := stop()):
            return why
        s = lead.world()
        now = time.monotonic()
        if s.in_battle or s.busy or s.verification:
            moved_at, sent = now, 0.0
        elif math.dist((s.x, s.y), xy) <= near and not s.moving:
            return None
        else:
            if last_xy is None or math.dist((s.x, s.y), last_xy) > 15:
                last_xy, moved_at = (s.x, s.y), now
            if (s.nav_active or s.moving) and now - moved_at > 6:
                # 2026-10-29 03:07: a 银狐王勇 dialog left open after the hand-ins froze the leader (nav on, no step)
                turnin.close(lead)
                lead.game.cancel_navigation()
                moved_at, sent = now, 0.0
            elif not s.nav_active and not s.moving and now - sent > 2:
                lead.game.navigate(s.map_id, *xy)
                sent = now
        time.sleep(0.3)
    raise t.Stop(f'{lead.name} {timeout}s 没带队走到 {xy}')


def team_up(lead, cs):
    for c in cs:
        if c.char_id in lead.team():
            continue
        s = c.world()
        if s.map_id != lead.world().map_id:
            raise t.Stop(f'{c.name} 在 map {s.map_id}，队长在 map {lead.world().map_id}')
        if math.dist((s.x, s.y), (lead.world().x, lead.world().y)) > 100:
            walk_team(lead, (round(s.x) - 8, round(s.y) - 8), near=50, timeout=180)
        turnin.invite(lead, c)
    t.say(f'队伍: {lead.team()}')


def wait_calm(cs, timeout=120):
    t.wait(lambda: not any((s := c.world()).in_battle or s.busy for c in cs), timeout, '全员打完战斗')


def enter(lead, cs):
    team_up(lead, cs)
    walk_team(lead, GATE_STAND, near=80)
    wait_calm([lead] + cs)
    lead.game.click_npc(GATE_NPC)
    dlg = t.wait(lambda: lead.dialog(), 5, '点禁锢之地')
    opts = [(o, t.plain(l)) for o, l in dlg.options]
    hit = next((o for o, l in opts if l.rstrip().endswith(GATE_PICK)), None)
    if hit is None:
        raise t.Stop(f'禁锢之地对话里没有「{GATE_PICK}」: {opts}')
    lead.game.select_dialog(hit)
    t.wait(lambda: lead.world().map_id == FARM, 10, '队长进 1202')
    try:
        t.wait(lambda: all(c.world().map_id == FARM for c in cs), 10, '队员进 1202')
    except t.Stop:
        raise t.Stop(f'队员没跟进图: {[(c.name, c.world().map_id) for c in cs]}')
    t.say(f'全队进了 map {FARM}')


def patrol(lead, cs, until):
    """A <-> B without stopping, until a bag is nearly full or `until` (monotonic). -> reason.

    Like the official auto-patrol, the leader never stands still at a turn (user 2026-10-29: a 1-2 s pause at each
    end): within TURN px of the target it is already sent to the other point while still walking. Out of battle,
    standing still for STILL s re-sends the walk at once; the path-finder flag can stay set after arriving
    (measured 01:3x: 6.3 s at B waiting for the 6 s stall rule), so the flag is not trusted here."""
    def stop():
        if time.monotonic() >= until:
            return '时间到'
        full = [c.name for c in [lead] + cs if bag_free(c) <= FREE_MIN]
        if full:
            return f'背包快满: {full}'
        if any(c.world().map_id != FARM for c in [lead] + cs):
            return f'有人不在 1202: {[(c.name, c.world().map_id) for c in [lead] + cs]}'
        return None
    i, laps, sent, last_xy, still_at, checked, fought = 0, 0, 0.0, None, time.monotonic(), 0.0, False
    lead.game.navigate(FARM, *PATROL[i])
    while True:
        now = time.monotonic()
        if now - checked >= 2:                  # bags / map: every 2 s is enough
            checked = now
            if (why := stop()):
                lead.game.cancel_navigation()
                t.say(f'停止巡逻（{why}），走了 {laps} 趟')
                return why
        s = lead.world()
        if s.in_battle or s.busy or s.verification:
            last_xy, still_at, sent, fought = None, now, 0.0, True
        elif fought:                            # battle just over: walk on at once (measured a 0.5 s wait)
            fought = False
            lead.game.navigate(FARM, *PATROL[i])
            sent, still_at = now, now
        elif math.dist((s.x, s.y), PATROL[i]) <= TURN:
            i, laps = 1 - i, laps + 1
            lead.game.navigate(FARM, *PATROL[i])
            sent, still_at = now, now
        else:
            if last_xy is None or math.dist((s.x, s.y), last_xy) >= 1:
                last_xy, still_at = (s.x, s.y), now
            elif now - still_at >= STILL and now - sent >= STILL:
                lead.game.navigate(FARM, *PATROL[i])
                sent = now
        time.sleep(0.1)


def leave(lead, cs):
    """The leader walks the team onto the exit; members are carried across with it (checked). A member still in
    1202 afterwards steps onto the exit itself: it stands right there, a few px (logged)."""
    wait_calm([lead] + cs, timeout=300)
    why = walk_team(lead, EXIT, near=20, timeout=900,
                    stop=lambda: None if lead.world().map_id == FARM else '队长已出图')
    if why is None:     # 2026-10-29 01:17: on the exit the map flips a moment later (it did cross)
        try:
            t.wait(lambda: lead.world().map_id != FARM, 10, '站上出口后跨图')
            why = '队长已出图'
        except t.Stop:
            pass
    if why is None:
        raise t.Stop(f'队长站在出口 {EXIT} 上没出图（坐标不对？）现在 {lead.world()}；全队还在 1202，一起站着')
    t.say(f'队长出图: map {lead.world().map_id} ({lead.world().x:.0f},{lead.world().y:.0f})')
    try:
        t.wait(lambda: all(c.world().map_id != FARM for c in cs), 15, '队员跟着出图')
    except t.Stop:
        late = [c for c in cs if c.world().map_id == FARM]
        t.say(f'没跟出来的队员自己踩出口: {[(c.name, round(c.world().x), round(c.world().y)) for c in late]}')
        for c in late:
            c.game.navigate(FARM, *EXIT)
        t.wait(lambda: all(c.world().map_id != FARM for c in cs), 60, '队员踩出口出图')
    t.say(f'全队出图: {[(c.name, c.world().map_id) for c in [lead] + cs]}')


def in_place(lead, cs, job):
    """Leader does job first, then each member leaves the team where it stands, does job, is invited back."""
    job(lead)
    for c in cs:
        if c.team():
            c.game.team_leave()
            t.wait(lambda: not c.team(), 5, f'{c.name} 离队')
        try:
            job(c)
        finally:
            turnin.invite(lead, c)


def cash_in(lead, cs, table):
    team_up(lead, cs)
    walk_team(lead, SHOP_STAND, near=60)
    time.sleep(2)
    in_place(lead, cs, lambda c: sell.sell(c.name, table))
    walk_team(lead, NPC_STAND, near=60)
    time.sleep(2)
    in_place(lead, cs, turnin.hand_in)
    for c in [lead, *cs]:
        turnin.close(c)


def buff_seconds(cs):
    """Fewest seconds of 暗影之力的庇佑 left in the team (0 = someone has none: nothing would drop for it)."""
    return min((b[1] if (b := shadow_left(c.mem)) else 0) for c in cs)


def main(minutes, hours, cycles, first_minutes=0):
    table = fi.load_items()
    every = [t.Client(n) for n in (LEADER,) + MEMBERS]
    roster = every[0].team()
    # 2026-10-29 01:2x: the user re-formed the team with 曾经不曾 as leader; a follower cannot walk the team
    lead = next((c for c in every if roster and c.char_id == roster[0]), every[0])
    cs = [c for c in every if c is not lead]
    t.say(f'队长 {lead.name}，队员 {[c.name for c in cs]}')
    left = buff_seconds(every)
    night_end = time.monotonic() + (hours * 3600 if hours else left - 120)
    t.say(f'暗影之力的庇佑最少剩 {left // 3600}h{left % 3600 // 60}m；循环到 '
          f'{time.strftime("%H:%M", time.localtime(time.time() + night_end - time.monotonic()))}')
    for n in range(cycles):
        if time.monotonic() >= night_end:
            break
        t.say(f'===== 第 {n + 1} 轮 =====')
        if n == 0 and lead.world().map_id != FARM and any(turnin.crystals(c) >= 10 for c in every):
            t.say('在图外、身上有结晶：先卖、先交')
            cash_in(lead, cs, table)
        if lead.world().map_id != FARM:
            enter(lead, cs)
        m = first_minutes if n == 0 and first_minutes else minutes
        stint_end = min(night_end, time.monotonic() + m * 60) if m else night_end
        patrol(lead, cs, stint_end)
        leave(lead, cs)
        cash_in(lead, cs, table)
    t.say('结束')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--minutes', type=float, default=0, help='each stint in the map (0 = until a bag is full)')
    ap.add_argument('--hours', type=float, default=0, help='0 = until the 暗影之力的庇佑 runs out')
    ap.add_argument('--first-minutes', type=float, default=0, help='first stint only (a test exit + sale)')
    ap.add_argument('--cycles', type=int, default=99)
    a = ap.parse_args()
    try:
        main(a.minutes, a.hours, a.cycles, a.first_minutes)
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
