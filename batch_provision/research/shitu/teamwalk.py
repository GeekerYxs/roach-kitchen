"""Team movement helpers for master-led trips in wild maps (round 3, 2026-10-27). Every newer team script uses these.

The rule they implement (three apprentices died walking alone, 千万7 / 千万5 / 千万8): in a wild map the MASTER leads
and fights (lunhui15.Caster); an apprentice only walks alone for the last few steps to an NPC, and runs away from any
battle on the way (Escaper).

  lead_to(lead, caster, xy)   leader walks to xy, casting in battles; re-navigates when standing still STALL s
                              (the client's 寻路 flag can stay set while nobody moves: 16:45-16:48, 3 min).
  past(lead, caster, xy)      leader walks OVER px beyond xy in the direction it came, so the members trailing behind
                              it stand next to xy (the last ones were too far to click the NPC). Needs lead.came_from.
  step_to(c, xy, near)        a member alone walks a few steps (Escaper in battles, same stall rule).
  regroup(lead, members)      bring members back into lead's team: member walks onto the leader (≤ 80 px), invite,
                              accept 1.5 s later, up to 4 tries (well10.form_team failed on 「与邀请者之间有障碍」 and on
                              the stale inviter field: the accept went out before the new invite).
  Escaper(c)                  in a battle: send 逃跑 (fight action 8) when the own SP changes, again after 6 s.

MAP is the map id all navigation goes to; set it before use (teamwalk.MAP = 170).
"""
import math
import time

import trial_run as t
from provisioner import world as w
from provisioner.game import FIGHT_ESCAPE

MAP = 280
NEAR, STALL, OVER, JOIN_NEAR = 100, 3.0, 80, 80


class Escaper:
    """User 16:3x: in 通天塔 battles just run away (「打不过的」). Like provisioner/novice.py: send 逃跑 (fight action 8)
    when the own SP changes (the one sent at SP 0 does nothing), again if SP stayed the same ESCAPE_AGAIN seconds.
    Running does not always work: never send an apprentice on a long walk alone with it."""
    ESCAPE_AGAIN = 6.0

    def __init__(self, c):
        self.c, self.escapes = c, 0
        self.reset()

    def reset(self):
        self.last_sp, self.last_t = None, 0.0

    def tick(self, now):
        sp = w.read_my_sp(self.c.mem)
        if sp is None:
            return
        if sp != self.last_sp or now - self.last_t >= self.ESCAPE_AGAIN:
            self.c.game.fight_command(FIGHT_ESCAPE)
            self.last_sp, self.last_t, self.escapes = sp, now, self.escapes + 1


def _walk(c, fighter, xy, near, timeout):
    end, last, still = time.monotonic() + timeout, 0, (None, time.monotonic())
    while True:
        now, s = time.monotonic(), c.world()
        pos = (round(s.x), round(s.y))
        if s.in_battle or s.moving or pos != still[0]:
            still = (pos, now)
        if s.in_battle:
            fighter.tick(now)
        elif math.dist((s.x, s.y), xy) <= near and not s.moving:
            return
        elif now - last > 2 and (not s.nav_active and not s.moving or now - still[1] > STALL):
            if s.nav_active:
                c.game.cancel_navigation()
            fighter.reset()
            c.game.navigate(MAP, *xy)
            last, still = now, (pos, now)
        if now > end:
            raise t.Stop(f'{c.name} {timeout}s 没走到 {xy}')
        time.sleep(0.15)


def lead_to(lead, caster, xy):
    """Leader walks to xy on MAP, casting in battles."""
    _walk(lead, caster, xy, NEAR, 240)


def step_to(c, xy, near=60):
    """A member alone walks to xy on MAP, running from battles."""
    _walk(c, Escaper(c), xy, near, 60)


def past(lead, caster, xy):
    """Leader walks OVER px on beyond xy (direction lead.came_from -> xy). Best effort: 6 s, then as it is."""
    hist = getattr(lead, 'came_from', None)
    lead.came_from = xy
    if not hist:
        return
    dx, dy = xy[0] - hist[0], xy[1] - hist[1]
    d = math.hypot(dx, dy) or 1
    goal = (round(xy[0] + dx / d * OVER), round(xy[1] + dy / d * OVER))
    lead.game.navigate(MAP, *goal)
    end = time.monotonic() + 6
    while time.monotonic() < end:
        st = lead.world()
        if st.in_battle:
            caster.tick(time.monotonic())
            end = time.monotonic() + 6
        elif math.dist((st.x, st.y), goal) <= 30 and not st.moving:
            break
        time.sleep(0.15)
    if lead.world().nav_active:
        lead.game.cancel_navigation()
    time.sleep(0.8)


def regroup(lead, members):
    """Bring every member back into lead's team (see the module doc)."""
    for c in members:
        if c.char_id in lead.team():
            continue
        esc = Escaper(c)
        for attempt in range(4):
            ls = lead.world()
            end, last = time.monotonic() + 60, 0
            while True:
                s = c.world()
                if s.in_battle:
                    esc.tick(time.monotonic())
                elif math.dist((s.x, s.y), (ls.x, ls.y)) <= JOIN_NEAR and not s.moving:   # 40 hung at 48 px (17:46)
                    break
                elif not s.nav_active and not s.moving and time.monotonic() - last > 2:
                    esc.reset()
                    c.game.navigate(MAP, round(ls.x), round(ls.y))
                    last = time.monotonic()
                if time.monotonic() > end:
                    raise t.Stop(f'{c.name} 60s 没走到 {lead.name} 旁')
                time.sleep(0.15)
            t.wait(lambda: not lead.world().in_battle, 120, f'{lead.name} 战斗结束')
            lead.game.team_invite(c.char_id, w.read_level(lead.mem), w.read_invite_byte(lead.mem), lead.name)
            time.sleep(1.5)
            c.game.team_accept()
            try:
                t.wait(lambda: c.char_id in lead.team(), 3, f'{c.name} 入队')
                break
            except t.Stop:
                t.say(f'[{c.name}] 第 {attempt + 1} 次邀请没进队')
        else:
            raise t.Stop(f'{c.name} 邀请 4 次都没进队')
    t.say(f'[{lead.name}] 队伍 {lead.team()}')
