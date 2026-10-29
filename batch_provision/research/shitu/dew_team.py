"""Task 181 step 7 with the master leading (user 16:4x after two apprentices died running alone): the team walks between
the three 通天花 nearest the 通天塔路口 gate, 954 -> 957 -> 955 -> 954 ... (user's minimap: those three are enough);
the leader casts in every battle (lunhui15.Caster). At a flower each apprentice still short of 5 leaves the team,
gathers until 「采集完了」, then everyone re-joins (teamwalk.regroup) and the leader walks on (teamwalk.lead_to / past).

    python -X utf8 research/shitu/dew_team.py MASTER 千万1:0 千万2:0 ...     (name:花露 already gathered)

Count = the 0x46ff 「已经采集N滴花露」 on each apprentice's tap. Stops when all have 5, or after ROUNDS laps.
"""
import re
import sys
import time

import trial_run as t
from provisioner import world as w
from lunhui15 import Caster
from monitor import Tap, texts
import teamwalk
from teamwalk import lead_to, past, regroup, step_to     # moved there 18:5x; dew_team.<name> still works

MAP = teamwalk.MAP = 280
FLOWERS = ((954, (292, 4295)), (957, (1050, 4065)), (955, (1440, 4724)))
COUNT = re.compile(r'已经采集(\d+)滴花露')
BOTTLE = 10692            # 花露瓶: given with the 5th drop (2026-10-28 team C, absent before), so in the bag = done
FULL = '足够的花露'       # the 5th drop says「获得了1个花露瓶」+「你已经采集了足够的花露…」, no count (16:5x)
ROUNDS = 6


def gather(c, tap, npc, xy, got):
    """Gather npc until it is used up for c (or got reaches 5). -> new count. The member first walks up to the flower:
    the last ones of the team trail stood too far (16:50: 千万4 / 千万8 got no dialog from 957)."""
    step_to(c, xy)
    for _ in range(4):
        c.game.click_npc(npc)
        try:
            d = t.wait(lambda: c.dialog(), 5, f'{c.name} 通天花 {npc}')
        except t.Stop:
            step_to(c, xy, near=30)
            c.game.click_npc(npc)
            try:
                d = t.wait(lambda: c.dialog(), 5, f'{c.name} 通天花 {npc}（走近后）')
            except t.Stop:
                # 2026-10-29 亿万52: no dialog from 954 twice (the server had it elsewhere, like team_npc's NPCs);
                # walk away and back, click once more, else leave this flower to the next round (6 rounds)
                t.say(f'[{c.name}] 走近后点通天花 {npc} 还是没对话框，走开再回来重点')
                c.game.cancel_navigation()
                c.game.navigate(MAP, xy[0] + 150, xy[1])
                try:
                    t.wait(lambda: not c.world().moving and not c.world().nav_active, 20, f'{c.name} 走开')
                except t.Stop:
                    pass
                step_to(c, xy, near=30)
                c.game.click_npc(npc)
                try:
                    d = t.wait(lambda: c.dialog(), 5, f'{c.name} 通天花 {npc}（走开再回来后）')
                except t.Stop:
                    t.say(f'[{c.name}] 通天花 {npc} 这一圈点不出对话框，下一圈再来（现在 {got}/5）')
                    return got
        if not any('采集' in t.plain(l) for _, l in d.options):
            c.game.select_dialog(0)
            break
        c.game.select_dialog(next(o for o, l in d.options if '采集' in t.plain(l)))
        end = time.monotonic() + 5
        while time.monotonic() < end:
            for _, dd, op, body, _ in tap.poll():
                text = ' '.join(texts(body)) if op == 0x46ff else ''
                k = COUNT.search(text)
                if k:
                    got, end = int(k.group(1)), 0
                elif FULL in text:
                    got, end = 5, 0
            time.sleep(0.1)
        if got >= 5:
            break
    return got


def main(master, counts):
    lead = t.Client(master)
    apps = {n: t.Client(n) for n in counts}
    for n, c in apps.items():       # 2026-10-28: a rerun counted from 0 and lapped flowers already used up for C's four
        if w.item_count(w.read_bag(c.mem), BOTTLE):
            t.say(f'[{n}] 背包已有花露瓶，5 滴已采完')
            counts[n] = 5
    taps = {n: Tap(c.pid, from_end=True) for n, c in apps.items()}
    for tap in taps.values():
        tap.ready()
    caster = Caster(lead)
    st = lead.world()
    lead.came_from = (round(st.x), round(st.y))     # past(): direction to the first flower
    regroup(lead, list(apps.values()))
    for lap in range(ROUNDS):
        for npc, xy in FLOWERS:
            need = [n for n in apps if counts[n] < 5]
            if not need:
                t.say(f'全部 5 滴: {counts}')
                return counts
            lead_to(lead, caster, xy)
            past(lead, caster, xy)
            for n in need:
                c = apps[n]
                c.game.team_leave()
                t.wait(lambda: not c.team(), 5, f'{n} 离队')
            for n in need:
                before = counts[n]
                counts[n] = gather(apps[n], taps[n], npc, xy, counts[n])
                t.say(f'[{n}] 通天花 {npc}: {before} -> {counts[n]}/5')
            if all(v >= 5 for v in counts.values()):   # done: the next step scrolls home, no team needed (user 2026-10-28)
                t.say(f'全部 5 滴: {counts}')
                return counts
            regroup(lead, list(apps.values()))
        t.say(f'第 {lap + 1} 圈后: {counts}')
    t.say(f'{ROUNDS} 圈后: {counts}')
    return counts


if __name__ == '__main__':
    master, *pairs = sys.argv[1:]
    try:
        main(master, {p.split(':')[0]: int(p.split(':')[1]) for p in pairs})
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
