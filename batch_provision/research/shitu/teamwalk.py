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
    """Walk c to xy; seconds spent in battles do not count toward timeout (2026-10-28 亿万44: a battle on the way to
    a 通天花 ate the 60 s, the dew step failed), but the whole walk stops after 3 * timeout."""
    t0 = time.monotonic()
    end, last, still, prev = t0 + timeout, 0, (None, t0), t0
    while True:
        now, s = time.monotonic(), c.world()
        pos = (round(s.x), round(s.y))
        if s.in_battle or s.moving or pos != still[0]:
            still = (pos, now)
        if s.in_battle:
            end = min(end + now - prev, t0 + 3 * timeout)
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
            raise t.Stop(f'{c.name} {timeout}s 没走到 {xy}（含战斗共 {now - t0:.0f}s）')
        prev = now
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


def _taps(*cs):
    """Taps from now on, to print the server's 0x46ff answers when an invite fails (None when no tap file)."""
    from monitor import Tap
    out = []
    for c in cs:
        try:
            tp = Tap(c.pid, from_end=True)
            tp.ready()
            out.append((c.name, tp))
        except Exception:
            pass
    return out


def _texts(taps):
    from monitor import texts
    got = []
    for name, tp in taps:
        try:
            got += [f'{name}:' + ' '.join(texts(body)) for _, d, op, body, _ in tp.poll() if op == 0x46ff and d == 'S->C']
        except Exception:
            pass
    return got


def flee(c):
    from quanshou import flee as run_away
    run_away(c)


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
                if time.monotonic() > end:     # 2026-10-28 亿万10 / 亿万1: the leader walks to the member instead
                    if getattr(c, 'lead_came', False):
                        raise t.Stop(f'{c.name} 60s 没走到 {lead.name} 旁，{lead.name} 走过去也没用')
                    t.say(f'[{c.name}] 60s 没走到 {lead.name} 旁 ({s.x:.0f},{s.y:.0f})，改让 {lead.name} 走过来')
                    c.lead_came = True
                    c.game.cancel_navigation()
                    s = c.world()
                    flee(lead)   # 2026-10-28 亿万9 as the 蝎子王 leader: nobody fights a battle during a regroup
                    lead.game.navigate(MAP, round(s.x), round(s.y))
                    ls, end = s, time.monotonic() + 60
                    t.wait(lambda: (q := lead.world()) and math.dist((q.x, q.y), (s.x, s.y)) <= JOIN_NEAR
                           and not q.moving, 60, f'{lead.name} 走到 {c.name} 旁')
                    continue
                time.sleep(0.15)
            flee(lead)   # 2026-10-28 亿万9 as the 蝎子王 leader: nobody fights a battle during a regroup
            if (dlg := c.dialog()) is not None:     # an NPC dialog left open (通天花 with nothing to gather) may block it
                t.say(f'[{c.name}] 入队前还开着对话框 {[(o, t.plain(l)) for o, l in dlg.options]}，先关掉')
                c.game.select_dialog(next((o for o, l in dlg.options if '离开' in t.plain(l)), 0))
                time.sleep(0.5)
            taps = _taps(lead, c)
            lead.game.team_invite(c.char_id, w.read_level(lead.mem), w.read_invite_byte(lead.mem), lead.name)
            time.sleep(1.5)
            c.game.team_accept()
            try:
                t.wait(lambda: c.char_id in lead.team(), 3, f'{c.name} 入队')
                c.lead_came = False
                break
            except t.Stop:
                s, ls = c.world(), lead.world()
                said = _texts(taps)
                t.say(f'[{c.name}] 第 {attempt + 1} 次邀请没进队（距离 {math.dist((s.x, s.y), (ls.x, ls.y)):.0f}，'
                      f'busy={s.busy} 战斗={s.in_battle} 对话框={c.dialog() is not None} 队伍={c.team()}，'
                      f'师傅队伍={lead.team()}，系统提示={said}）')
                if any('距离太远' in x for x in said):
                    # 2026-10-28 亿万28 in 苦无沙漠: 0 px on both clients, the server said 距离太远 four times (its
                    # position on the server was stale). Walking a few steps sends the real position.
                    # position on the server was stale; moving in place did not fix it (08:31): path-find over to a
                    # spot beside the leader, so the client sends a full walk
                    c.game.cancel_navigation()
                    c.game.navigate(MAP, round(ls.x) + 120 * (1 if attempt % 2 else -1), round(ls.y))
                    try:
                        t.wait(lambda: not c.world().moving and not c.world().nav_active, 20, f'{c.name} 走开再回来')
                    except t.Stop:
                        pass
                    c.game.navigate(MAP, round(ls.x), round(ls.y))
                    time.sleep(3)
                    continue
                c.game.team_leave()     # 2026-10-28 亿万8: a stale team state on the member side; leaving clears it
                time.sleep(1)
                # 2026-10-28 亿万3 at 54 px: 0x46ff「与邀请者之间有障碍」; the leader walking onto the member fixed it
                lead.game.navigate(MAP, round(s.x), round(s.y))
                try:
                    t.wait(lambda: (q := lead.world()) and math.dist((q.x, q.y), (s.x, s.y)) <= 10 and not q.moving,
                           15, f'{lead.name} 走到 {c.name} 脚下')
                except t.Stop as e:
                    t.say(f'[{lead.name}] {e}')
        else:
            raise t.Stop(f'{c.name} 邀请 4 次都没进队')
    t.say(f'[{lead.name}] 队伍 {lead.team()}')
