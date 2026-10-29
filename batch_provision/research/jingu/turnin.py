"""禁锢之地: hand in 黑暗结晶 at 银狐王勇 for gold, the leader leads the team there; nobody walks alone.

    python -X utf8 research/jingu/turnin.py 波大臀圆 曾经不曾 自由一号 自由二号 自由三号

银狐王勇 = NPC 2603, map 181 荒芜之地 (750,1665) (ResLib NPCDirection). Its menu (player doc 禁锢打螺丝.docx, live 2026-10-29):
「暗影试炼·收集黑暗结晶」 -> 「兑换黑暗结晶奖励」 -> 「给予 10 / 50 / 200 / 500 颗 黑暗结晶」; each crystal pays 392 gold and costs 549 潜能 (lv70),
+1 潜能 = u32 session+0xEF8 (live 2026-10-29: 190 crystals -> gold +74480, 潜能 -104310 exact, lv67 same price).
+1 南方联军将领勋章 per 10.
Map 181 is wild: an alt walking alone gets killed (user 2026-10-29). So the LEADER (first roster member) walks the whole
team to the NPC and hands in first; then each member, standing where it is, leaves the team, clicks the NPC (no
walking), hands in and is invited back at once. Each hand-in: click -> 暗影试炼 -> 兑换 -> the biggest 给予 that fits,
again until fewer than 10 are left.
"""
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'shitu'))

import teamwalk as d                        # noqa: E402  (puts batch_provision/ on sys.path)
import trial_run as t                       # noqa: E402
from provisioner import world as w          # noqa: E402

MAP, NPC, STAND = 181, 2603, (750, 1705)
CRYSTAL = 11077
MENU = ('兑换黑暗结晶', '暗影试炼')    # 2nd page entry first, then the NPC's first-page entry
GIVE = re.compile(r'给予\s*(\d+)\s*颗')
POT = 0xEF8                                 # u32 at session+0xEF8 = 潜能


def crystals(c):
    return w.item_count(w.read_bag(c.mem), CRYSTAL)


def potential(c):
    s = c.mem.u32(c.mem.base + w.SESSION_MGR_RVA)
    return c.mem.u32(s + POT)


def pick_give(options, have):
    """(opt, n) of the biggest 给予 n that the bag covers, or None."""
    fits = [(int(m.group(1)), o) for o, l in options if (m := GIVE.search(t.plain(l))) and int(m.group(1)) <= have]
    return (max(fits)[1], max(fits)[0]) if fits else None


def close(c):
    """Close any NPC dialog and wait until it is really gone."""
    for _ in range(3):
        if c.dialog() is None:
            return
        c.game.select_dialog(0)
        try:
            t.wait(lambda: c.dialog() is None, 3, f'{c.name} 关对话框')
            return
        except t.Stop:
            pass


def open_menu(c):
    """Click the NPC and go into 兑换黑暗结晶奖励; returns the dialog showing the 给予 options."""
    close(c)        # a give page still on screen would be taken for the fresh one (2026-10-29 自由二号, 波大臀圆)
    c.game.click_npc(NPC)
    dlg = t.wait(lambda: c.dialog(), 5, f'{c.name} 点银狐王勇')
    for _ in range(3):
        opts = [(o, t.plain(l)) for o, l in dlg.options]
        if any(GIVE.search(l) for _, l in opts):
            return dlg
        hit = next((o for k in MENU for o, l in opts if k in l), None)
        if hit is None:
            raise t.Stop(f'{c.name} 对话里没有 {MENU}: {opts}')
        prev = dlg.text
        c.game.select_dialog(hit)
        dlg = t.wait(lambda: (x := c.dialog()) and x.text != prev and x, 5, f'{c.name} 进兑换页')
    raise t.Stop(f'{c.name} 没进到给予页')


def hand_in(c):
    start_n, start_g, start_p = crystals(c), w.read_gold(c.mem), potential(c)
    t.say(f'[{c.name}] 结晶 {start_n}，金币 {start_g}，潜能? {start_p}')
    if start_n < 10:
        return
    misses = 0
    for _ in range(40):
        have = crystals(c)
        if have < 10:
            break
        dlg = open_menu(c)
        pick = pick_give(dlg.options, have)
        if pick is None:
            raise t.Stop(f'{c.name} 有 {have} 颗但没有合适的给予选项: {dlg.options}')
        opt, n = pick
        c.game.select_dialog(opt)
        try:
            t.wait(lambda: crystals(c) <= have - n, 5, f'{c.name} 给予 {n}')
        except t.Stop:
            dlg = c.dialog()
            misses += 1
            t.say(f'[{c.name}] 给予 {n} 后结晶没少（{crystals(c)}），第 {misses} 次，'
                  f'对话: {t.body(dlg)[:60] if dlg else None}')
            if misses >= 3:
                raise t.Stop(f'{c.name} 连续 3 次给予没扣结晶')
        close(c)
    n, g, p = crystals(c), w.read_gold(c.mem), potential(c)
    t.say(f'[{c.name}] 交了 {start_n - n} 颗，金币 +{g - start_g}，潜能? {p - start_p:+d}，剩 {n} 颗')


def invite(lead, c):
    for attempt in range(3):     # 2026-10-29 自由三号: the first invite right after arriving was not taken
        lead.game.team_invite(c.char_id, w.read_level(lead.mem), w.read_invite_byte(lead.mem), lead.name)
        time.sleep(1.5)
        c.game.team_accept()
        try:
            return t.wait(lambda: c.char_id in lead.team(), 5, f'{c.name} 入队')
        except t.Stop:
            # 2026-10-29 自由二号: 「与邀请者之间有障碍。」 with the leader ~130 px away; the leader (with the team)
            # walks over to the member, never the member alone
            t.say(f'[{c.name}] 第 {attempt + 1} 次邀请没进队，队长走过去')
            s = c.world()
            lead.game.navigate(MAP, round(s.x) - 8, round(s.y) - 8)
            time.sleep(4)
            if lead.world().nav_active:
                lead.game.cancel_navigation()
    raise t.Stop(f'{c.name} 3 次邀请都没进队')


def lead_to_npc(lead):
    """The leader walks the team next to the NPC; battles on the way pause the walk, then it is sent again."""
    end = time.monotonic() + 300
    while time.monotonic() < end:
        s = lead.world()
        if s.in_battle or s.busy:
            pass
        elif abs(s.x - STAND[0]) <= 60 and abs(s.y - STAND[1]) <= 60 and not s.moving:
            return
        elif not s.nav_active and not s.moving:
            lead.game.navigate(MAP, *STAND)
        time.sleep(1)
    raise t.Stop(f'{lead.name} 300s 没带队走到银狐王勇')


def main(names):
    cs = {n: t.Client(n) for n in names}
    for c in cs.values():
        if c.world().map_id != MAP:
            raise t.Stop(f'{c.name} 不在荒芜之地 (map {c.world().map_id})')
    roster = next((x for c in cs.values() if (x := c.team())), ())
    lead = next((c for c in cs.values() if roster and c.char_id == roster[0]), None)
    if lead is None or any(c.char_id not in roster for c in cs.values()):
        raise t.Stop(f'要求所有号都在同一队且队长在名单里；队伍 {roster}')
    lead_to_npc(lead)
    time.sleep(2)                               # followers catch up
    hand_in(lead)
    for c in cs.values():
        if c is lead or crystals(c) < 10:
            continue
        c.game.team_leave()
        t.wait(lambda: not c.team(), 5, f'{c.name} 离队')
        try:
            hand_in(c)
        finally:
            invite(lead, c)
    t.say(f'队伍: {lead.team()}')


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
