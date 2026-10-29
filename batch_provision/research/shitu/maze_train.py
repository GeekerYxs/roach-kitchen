"""师徒 leveling in a maze, generic version of lunhui15.py: walk there leg by leg, patrol, stop at the target level.

    python -X utf8 research/shitu/maze_train.py

Current plan (user, 2026-10-27): from 轮回之城 (555) walk to 平静海岸3区 (82), 暗影迷城 (600) until every apprentice
is 19, then walk to 无尽平原1区 (140), 八阵图 (700) until 23, then walk to 大个王 in 龙之都外城 (20) and stop.
Each maze: patrol landing point <-> B. A maze entrance/exit is entered by clicking its NPC. Team, casting and talent exactly as
lunhui15.py (伏地魔1 leader; 伏地魔1/2 扫射 803 + pet 烈焰爆发 1504 every turn; apprentices send nothing; talent ->
体质).
legs: what the leader does on each map until the maze is reached (NPC data: AutoPath/NPCDirection.csv):
  ('click', npc, xy)        walk next to an exit NPC and click it (picks a menu option if one opens)
  ('walk', dest_map, xy)    official path-finder with a destination map (crosses map links, e.g. 81 -> 82)
B point: the stage's patrol_b, or when None the first of 8 points PROBE px around the landing point that the leader actually
reaches (a point it cannot reach stalls twice and the next one is tried).
"""
import math
import os
import sys
import time

import trial_run as t
from factory.welltrain import Talent, decide_talent
from lunhui15 import APPRENTICES, ARRIVE, CASTERS, HELPERS, LEADER, MEMBERS, NAV_RETRY, NEAR, STALL, TICK, Caster
from provisioner import world as w
from well10 import form_team

# Stages in order (user, 2026-10-27): 暗影迷城 until 19, then 八阵图 until 25. legs = what the leader does on each map
# before it reaches the stage's maze; patrol_b = fixed B point, None = probe (see Route.patrol).
STAGES = (
    dict(name='暗影迷城', maze=600, until=19, patrol_b=(1136, 771),      # B probed live 01:02 (landing (786,771))
         legs={555: ('click', 10157, (2880, 360)),       # 轮回之城 exit -> 平静海岸2区
               81: ('walk', 82, (1724, 2489)),           # across the 81 -> 82 link to the 暗影迷城 entrance
               82: ('click', 10160, (1724, 2489))}),     # 暗影迷城 entrance
    dict(name='八阵图', maze=700, until=23, patrol_b=(1200, 1800),       # B from the user; 25 -> 23 (user 01:24)
         legs={600: ('click', 10159, (672, 756)),        # 暗影迷城 exit -> 平静海岸3区
               82: ('walk', 140, (831, 2257)),           # across the 82 -> 140 link to the 八阵图 entrance
               140: ('click', 10164, (831, 2257))}),     # 八阵图 entrance (无尽平原1区)
    # goal stage: walk to a spot and stop there (no level target)
    dict(name='龙之都外城 大个王', goal=(20, (4398, 2553)), maze=None, until=None, patrol_b=None,
         legs={700: ('click', 10163, (672, 1608)),       # 八阵图 exit -> 无尽平原1区
               140: ('walk', 20, (4398, 2553))}),        # across the 140 -> 20 link to 大个王 (NPC 557)
)
PROBE = 350
NEAR_ENOUGH = 250  # a patrol point we stall this close to counts as reached
UNSTICK = ((300, 0), (0, 300), (-300, 0), (0, -300))   # side steps out of a wedged spot, tried in turn
UNSTICK_WAIT = 8.0                                     # seconds the side step runs before pathing to the goal again
MIN_LEG = 200      # a replacement A point must be at least this far from B (a patrol needs walking to meet monsters)
CLICK_NEAR = 25     # live 01:09: 10159 ignored 3 clicks from 67 px, answered at once from 0 px; 10164 can only be
                    # reached to ~34 px (stalls there), clicking from there works -> click once stalled within NEAR
CLICK_WAIT = 8.0


MAX_FALLS = 5      # one apprentice knocked out this often in one stage = the map is too hard for it: stop

class Route:
    def __init__(self, stage):
        self.stage, self.maze, self.legs, self.patrol_b = stage['name'], stage['maze'], stage['legs'], stage['patrol_b']
        self.goal = stage.get('goal')
        self.patrol_a = stage.get('patrol_a')         # fixed A point (default: where the leader first stands)
        self.last_nav, self.progress_xy, self.progress_at = -1e9, None, 0.0
        self.clicked_at, self.clicks, self.map = None, 0, None
        self.points, self.target, self.stalls, self.probes = None, 0, 0, []
        self.last_reason = None

    def say(self, msg):
        if msg != self.last_reason:
            t.say(f'[{LEADER}] {msg}')
            self.last_reason = msg

    def walk(self, lead, st, map_id, xy, now, why):
        """No 15 px of progress for STALL seconds (walking or not) = one stall: cancel and path again."""
        if self.progress_xy is None or math.dist((st.x, st.y), self.progress_xy) > 15:
            self.progress_xy, self.progress_at = (st.x, st.y), now
        if now - self.progress_at > STALL:
            self.stalls += 1
            anchor = getattr(self, 'wedge_xy', None)      # stalls within 150 px of the first one count as one spot
            if anchor is None or math.dist((st.x, st.y), anchor) > 150:
                self.wedge_xy, self.wedged = (st.x, st.y), 0
            self.wedged += 1
            self.say(f'{STALL:.0f}s 没动（第 {self.stalls} 次），重新寻路（{why}）')
            if self.wedged >= 20:      # 2026-10-28 伏地魔2 wedged at 古迹 (3840,2944) for 300 tries; home + rerun fixes it
                raise t.Stop(f'寻路连续卡住 {self.wedged} 次（{why}，在 ({st.x:.0f},{st.y:.0f})）')
            if st.nav_active:
                lead.game.cancel_navigation()
            self.progress_at, self.last_nav = now, -1e9
            if self.wedged % 5 == 0:
                # 2026-10-29 伏地魔2 at the same 古迹 spot (3840,2944) as round 4: pathing again from there never
                # works. Step aside first (a different side each time), the next pathing starts somewhere else
                dx, dy = UNSTICK[(self.wedged // 5 - 1) % len(UNSTICK)]
                aside = (max(1, round(st.x + dx)), max(1, round(st.y + dy)))
                self.say(f'同一处卡了 {self.wedged} 次，先往旁边走到 {aside} 再接着去')
                lead.game.navigate(st.map_id, *aside)
                self.last_nav = now + UNSTICK_WAIT - NAV_RETRY     # let the side walk run before pathing again
            return
        if st.nav_active or st.moving or now - self.last_nav < NAV_RETRY:
            return
        dist = math.dist((st.x, st.y), xy) if st.map_id == map_id else None
        self.say(f'寻路{why}' + (f'（距离 {dist:.0f}）' if dist is not None else ''))
        lead.game.navigate(map_id, *xy)
        self.last_nav = now

    def tick(self, lead, st, now):
        if st.map_id != self.map:
            self.map, self.clicked_at, self.clicks, self.stalls, self.last_nav = st.map_id, None, 0, 0, -1e9
            self.progress_xy, self.progress_at = (st.x, st.y), now
            self.say(f'到地图 {st.map_id} ({st.x:.0f},{st.y:.0f})')
        if st.in_battle or st.busy or st.verification:
            self.progress_at = now
            if st.in_battle:
                self.last_nav = -1e9
            return
        if self.goal and st.map_id == self.goal[0]:
            if self.goal[1] is None or math.dist((st.x, st.y), self.goal[1]) <= NEAR and not st.moving:
                return 'arrived'
            return self.walk(lead, st, *self.goal, now, f'去终点 {self.goal}')
        if st.map_id == self.maze:
            return self.patrol(lead, st, now)
        leg = self.legs.get(st.map_id)
        if self.stalls >= 10:
            raise t.Stop(f'在地图 {st.map_id} 卡住 10 次，走不过去')
        if leg is None:
            raise t.Stop(f'{LEADER} 在意外的地图 {st.map_id}')
        if leg[0] == 'walk':
            return self.walk(lead, st, leg[1], leg[2], now, f'去地图 {leg[1]} {leg[2]}')
        npc, xy = leg[1], leg[2]
        if st.dialog:
            want = leg[3] if len(leg) > 3 else None          # optional option text, e.g. 952「到通天塔二区」
            hit = [(o, l) for o, l in st.dialog.options if o and (not want or want in l)][:1]
            if not hit:
                raise t.Stop(f'NPC {npc} 对话框不认识: {st.dialog.text!r} {st.dialog.options}')
            self.say(f'NPC {npc} 对话框 {st.dialog.options}，选「{hit[0][1]}」')
            lead.game.select_dialog(hit[0][0])
            time.sleep(1)
            return
        d = math.dist((st.x, st.y), xy)
        if d > CLICK_NEAR and not (d <= NEAR and self.stalls >= 1):     # 10164: the NPC spot itself is not walkable
            return self.walk(lead, st, st.map_id, xy, now, f'去 NPC {npc} {xy}')
        if st.nav_active:
            lead.game.cancel_navigation()
            return
        if self.clicked_at and now - self.clicked_at < CLICK_WAIT:
            return
        if self.clicks >= 3:
            raise t.Stop(f'点了 3 次 NPC {npc} 都没换地图')
        self.say(f'点 NPC {npc}')
        lead.game.click_npc(npc)
        self.clicked_at, self.clicks = now, self.clicks + 1

    def patrol(self, lead, st, now):
        if self.points is None:
            land = self.patrol_a or (round(st.x), round(st.y))
            self.points = [land, self.patrol_b]
            self.probes = [] if self.patrol_b else [
                (round(land[0] + PROBE * math.cos(a)), round(land[1] + PROBE * math.sin(a)))
                for a in (i * math.pi / 4 for i in range(8))]
            self.probes = [p for p in self.probes if p[0] > 0 and p[1] > 0]
            if not self.patrol_b:
                self.points[1] = self.probes.pop(0)
            self.target = 0 if self.patrol_a else 1
            self.say(f'进入迷宫，落点 {land}；B 点' + ('固定' if self.patrol_b else '试探') + f' {self.points[1]}')
        xy = self.points[self.target]
        if self.stalls >= 2 and math.dist((st.x, st.y), xy) <= NEAR_ENOUGH:
            # round 3 通天塔二区: the user's (562,249) is ~180 px past the walkable end; stalling that close = arrived
            self.say(f'{xy} 走不到跟前，停在 ({st.x:.0f},{st.y:.0f}) 离 {math.dist((st.x, st.y), xy):.0f} px，算到了，掉头')
            self.target, self.stalls, self.last_nav = 1 - self.target, 0, -1e9
            return
        if self.stalls >= 2 and self.target == 0:
            self.a_fails = getattr(self, 'a_fails', 0) + 1           # reset only on reaching A (flips resets at B)
        if (self.stalls >= 2 and self.target == 0 and self.a_fails >= 3 and self.patrol_b
                and math.dist((st.x, st.y), self.points[1]) >= MIN_LEG):
            # 2026-10-29 八阵图 伏地魔3: from B the way back to the landing A never worked (stuck at (912,1984)
            # 20 times). Where it got stuck is reachable from B: patrol there instead, any walk meets monsters
            self.points[0] = (round(st.x), round(st.y))
            self.say(f'{xy} 从 B 点回不去，A 点改成这里 {self.points[0]}，在它和 B 点 {self.points[1]} 之间巡逻')
            self.target, self.stalls, self.flips, self.a_fails, self.last_nav = 1, 0, 0, 0, -1e9
            self.wedged = 0
            return
        if self.stalls >= 2 and (self.patrol_b or self.target == 0) and getattr(self, 'flips', 0) < 4:
            # round 4 通天塔二区 01:36: the path-finder hung twice on the 1700 px walk from the landing to A; walk to
            # the other point instead (the next lap tries this one again); give up after 4 such turns in a row
            self.flips = getattr(self, 'flips', 0) + 1
            self.say(f'{xy} 卡住两次（停在 ({st.x:.0f},{st.y:.0f})），先去另一个巡逻点（第 {self.flips} 次）')
            self.target, self.stalls, self.last_nav = 1 - self.target, 0, -1e9
            return
        if self.stalls >= 2:
            if self.target == 0 or self.patrol_b or not isinstance(self.probes, list) or not self.probes:
                raise t.Stop(f'巡逻点 {xy} 走不到')
            self.points[1] = self.probes.pop(0)
            self.say(f'{xy} 走不到，改试 {self.points[1]}')
            self.stalls, self.last_nav = 0, -1e9
            return
        if math.dist((st.x, st.y), xy) <= ARRIVE and not st.moving:
            self.flips = 0
            if self.target == 0:
                self.a_fails = 0
            if self.target == 1 and self.probes is not None and not self.patrol_b and self.probes != 'fixed':
                self.say(f'B 点定为 {xy}（实际走到了），以后在 {self.points[0]} <-> {xy} 巡逻')
                self.probes = 'fixed'
            self.target, self.stalls, self.last_nav = 1 - self.target, 0, -1e9
            return
        self.walk(lead, st, self.maze, xy, now, f'巡逻去 {"AB"[self.target]} 点 {xy}')


STOP_AT = float(os.environ.get('SHITU_STOP_AT') or 0)   # epoch seconds; 0 = never


def main():
    cs = {n: t.Client(n) for n in (LEADER,) + MEMBERS}
    lead = cs[LEADER]
    for n, c in cs.items():
        s = c.world()
        t.say(f'[{n}] 等级 {w.read_level(c.mem)} 地图 {s.map_id} ({s.x:.0f},{s.y:.0f}) 天赋 {w.read_talent_points(c.mem)}')
    form_team(lead, [cs[n] for n in MEMBERS])
    casters = [Caster(cs[n]) for n in CASTERS]
    talents = {n: Talent() for n in APPRENTICES}
    stage_i = 0
    while STAGES[stage_i]['until'] and min(w.read_level(cs[n].mem) for n in APPRENTICES) >= STAGES[stage_i]['until']:
        stage_i += 1
    route = Route(STAGES[stage_i])
    t.say(f'当前段: {STAGES[stage_i]["name"]}' + (f'（刷到 {STAGES[stage_i]["until"]} 级）' if STAGES[stage_i]['until'] else ''))
    battles, in_battle, last_levels, t0 = 0, False, None, time.monotonic()
    fallen, falls = set(), {}            # round 3 (user 12:3x) stopped at the first death; now after MAX_FALLS
    while True:
        now = time.monotonic()
        sts = {n: c.world() for n, c in cs.items()}
        if any(s is None for s in sts.values()):
            time.sleep(TICK)
            continue
        for n in APPRENTICES:
            if sts[n].in_battle and n not in fallen:
                b = w.read_battle(cs[n].mem)
                if b and b.me and b.me.dead:
                    fallen.add(n)
                    t.say(f'[{n}] 战斗中倒下了，这场打完就停')
        if fallen and not sts[LEADER].in_battle:
            # unattended (2026-10-28): a knocked-out apprentice is back at full HP after the battle (亿万29 in
            # 通天塔二区: 1935/1935) and still in the team; count it and go on, stop only when one falls MAX_FALLS times
            for n in fallen:
                falls[n] = falls.get(n, 0) + 1
            t.say(f'{sorted(fallen)} 战斗中倒下（本段累计 {falls}），继续')
            worst = max(falls.values())
            fallen = set()
            if worst >= MAX_FALLS:
                if sts[LEADER].nav_active:
                    lead.game.cancel_navigation()
                raise t.Stop(f'{falls} 本段倒下 {worst} 次，已停下（地图 {sts[LEADER].map_id} '
                             f'({sts[LEADER].x:.0f},{sts[LEADER].y:.0f})，共 {battles} 场），等指示')
        missing = [n for n, c in cs.items() if c.char_id not in lead.team()]
        if missing:
            raise t.Stop(f'{missing} 不在 {LEADER} 的队里了（掉线或死亡？）')
        levels = {n: w.read_level(cs[n].mem) for n in APPRENTICES}
        if levels != last_levels:
            t.say(f'等级 {levels}，战斗 {battles} 场，用时 {(now - t0) / 60:.1f} 分')
            last_levels = levels
        for n in APPRENTICES:
            tm, pts = talents[n], w.read_talent_points(cs[n].mem)
            d = decide_talent(pts, tm, now)
            if d.kind == 'add':
                t.say(f'[{n}] {d.reason}')
                cs[n].game.add_constitution(d.arg)
                tm.sent_at, tm.before = now, pts
            elif d.kind == 'verified':
                tm.sent_at, tm.misses = None, 0
            elif d.kind == 'unconfirmed':
                t.say(f'[{n}] {d.reason}')
                tm.sent_at, tm.misses, tm.last_miss = None, tm.misses + 1, now
        lw = sts[LEADER]
        if lw.in_battle != in_battle:
            in_battle = lw.in_battle
            battles += in_battle
            if not in_battle:
                for c in casters:
                    c.reset()
        stage = STAGES[stage_i]
        if stage.get('quest'):                        # (quest id, steps): done once no apprentice still shows them
            qid, steps = stage['quest']
            qs = {n: w.read_quest(cs[n].mem, qid) for n in APPRENTICES}
            if not lw.in_battle and all(q.done or tuple(q.steps) != tuple(steps) for q in qs.values()):
                if lw.nav_active:
                    lead.game.cancel_navigation()
                t.say(f'{stage["name"]} 完成：任务 {qid} ' + ', '.join(f'{n} {q}' for n, q in qs.items()) +
                      f'；共 {battles} 场，{(now - t0) / 60:.1f} 分；停在地图 {lw.map_id} ({lw.x:.0f},{lw.y:.0f})')
                return
        if STOP_AT and time.time() >= STOP_AT and not lw.in_battle:      # r4: break off for the 散福 3 小时双倍
            if lw.nav_active:
                lead.game.cancel_navigation()
            t.say(f'{stage["name"]} 到点暂停（SHITU_STOP_AT）；共 {battles} 场，{(now - t0) / 60:.1f} 分')
            return
        if stage.get('done_when') and not lw.in_battle and stage['done_when']():   # quanshou: 0x46ff kill count
            if lw.nav_active:
                lead.game.cancel_navigation()
            t.say(f'{stage["name"]} 完成；共 {battles} 场，{(now - t0) / 60:.1f} 分；'
                  f'停在地图 {lw.map_id} ({lw.x:.0f},{lw.y:.0f})')
            return
        if stage['until'] and not lw.in_battle and all(v >= stage['until'] for v in levels.values()) and \
                all(w.read_talent_points(cs[n].mem) == 0 for n in APPRENTICES):
            if lw.nav_active:
                lead.game.cancel_navigation()
            if stage_i == len(STAGES) - 1:
                t.say(f'全部到 {stage["until"]} 级 {levels}，共 {battles} 场，{(now - t0) / 60:.1f} 分；'
                      f'停在地图 {lw.map_id} ({lw.x:.0f},{lw.y:.0f})，巡逻点 {route.points}，等下一步')
                return
            stage_i += 1
            route = Route(STAGES[stage_i])
            t.say(f'全部到 {stage["until"]} 级 {levels}，换下一段: {STAGES[stage_i]["name"]}')
            time.sleep(1)
            continue
        for c in casters:
            if sts[c.c.name].in_battle:
                c.tick(now)
        if route.tick(lead, lw, now) == 'arrived':
            t.say(f'到 {stage["name"]}：地图 {lw.map_id} ({lw.x:.0f},{lw.y:.0f})，等级 {levels}，'
                  f'共 {battles} 场，{(now - t0) / 60:.1f} 分；停下等下一步')
            return
        time.sleep(TICK)


if __name__ == '__main__':
    try:
        main()
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
