"""Patrol map 1200 with 波大臀圆; only command pet 烈焰爆发 and replay a retained SP immediately.

The route is a short out-and-back derived from the character's starting position. It never sends a character
attack or pet normal attack. In battle, it waits for a server-side action update after 烈焰爆发; if the pet still
has the same positive SP, it immediately recasts (the user's 完美施法 mechanic).
"""
import _bootstrap  # noqa: F401
import math
import time
from pathlib import Path

import monitor
from common import modules
from trial_run import Client, say
from provisioner import world as w

ROLE = '波大臀圆'
MAP_ID = 1200
PET_MAGIC = 1504
MIN_MP = 100
TICK = 0.05
MAX_CASTS_PER_BATTLE = 8


def main():
    c = Client(ROLE)
    st = c.world()
    if st.map_id != MAP_ID or st.verification:
        raise RuntimeError(f'当前状态不符合巡逻条件: map={st.map_id}, verify={st.verification}')
    pet = w.read_fighting_pet(c.mem)
    level = pet.abilities.get(PET_MAGIC, 0) if pet else 0
    if not pet or not level or pet.mp < MIN_MP:
        raise RuntimeError(f'出战宠物/烈焰爆发/魔力不足: pet={pet}, skill={level}')

    dll = next((Path(path) for _, path in modules(c.pid) if 'provision_native' in path.lower()), None)
    tap = None
    if dll:
        monitor.RUNTIME = dll.parent.parent / 'runtime'
        tap = monitor.Tap(c.pid, from_end=True)
        tap.ready()

    a = (int(st.x), int(st.y))
    b = (max(0, a[0] - 500), a[1])
    target = b
    last_cast_sp = None
    last_cast_at = 0.0
    pending = False
    blocked_sp = None
    warned_pending = False
    casts_this_battle = 0
    last_battle = False
    progress_xy = None
    progress_at = time.monotonic()
    say(f'[{ROLE}] map1200 往返巡逻 {a} ↔ {b}；仅宠物烈焰爆发 lv{level}，人物不下战斗指令')
    if tap and not tap.ready():
        say(f'[{ROLE}] 抓包文件尚未就绪，继续用内存状态监测蓄力点')

    try:
        while True:
            st = c.world()
            if st.map_id != MAP_ID or st.verification:
                c.game.cancel_navigation()
                raise RuntimeError(f'地图变化或出现验证，停止: map={st.map_id}, verify={st.verification}')

            packets = tap.poll() if tap and tap.ready() else []

            if st.in_battle:
                if st.nav_active or st.moving:
                    c.game.cancel_navigation()
                progress_xy = None
                if not last_battle:
                    last_cast_sp, pending, casts_this_battle, blocked_sp = None, False, 0, None
                    say(f'[{ROLE}] 进入战斗，停止移动；只观察宠物蓄力并施放烈焰爆发')
                last_battle = True
                battle = w.read_battle(c.mem)
                pet_fighter = battle.pet if battle else None
                live_pet = w.read_fighting_pet(c.mem)
                if pet_fighter and not pet_fighter.dead and battle.enemies and live_pet and live_pet.mp >= MIN_MP:
                    sp = pet_fighter.sp
                    pet_pos = pet_fighter.pos
                    pet_done = any(direction == 'S->C' and op == 0x4111 and len(body) == 2
                                   and body[0] == pet_pos and t >= last_cast_at
                                   for t, direction, op, body, _caller in packets)
                    charge_changed = pending and sp != last_cast_sp
                    if pending and (pet_done or charge_changed):
                        pending = False
                        warned_pending = False
                        if sp > 0 and sp == last_cast_sp:
                            say(f'[{ROLE}] 宠物行动结束后蓄力仍为 {sp}：未扣点，立即重放烈焰爆发')
                            blocked_sp = None
                        elif sp > 0:
                            say(f'[{ROLE}] 施法后蓄力变化但仍有 {sp} 点：立即继续释放，不留蓄力')
                            blocked_sp = None
                        else:
                            blocked_sp = 0
                    elif pending and not warned_pending and time.time() - last_cast_at >= 1.0:
                        say(f'[{ROLE}] 尚未确认宠物行动结束，暂不重复当前指令；等结束包或蓄力变化')
                        warned_pending = True
                    if not pending and sp > 0 and sp != blocked_sp and casts_this_battle < MAX_CASTS_PER_BATTLE:
                        target_pos = battle.enemies[0]
                        c.game.cast_pet_magic(target_pos, PET_MAGIC, level)
                        last_cast_sp, last_cast_at, pending = sp, time.time(), True
                        warned_pending = False
                        casts_this_battle += 1
                        say(f'[{ROLE}] 宠物释放烈焰爆发 lv{level}，SP={sp}，目标位={target_pos}'
                            f'（本场第 {casts_this_battle} 次）')
                    elif casts_this_battle >= MAX_CASTS_PER_BATTLE and not pending:
                        blocked_sp = sp
                time.sleep(TICK)
                continue

            if last_battle:
                last_battle = False
                pending, last_cast_sp, blocked_sp = False, None, None
                progress_xy, progress_at = None, time.monotonic()
                say(f'[{ROLE}] 战斗结束，恢复巡逻')
            now = time.monotonic()
            xy = (st.x, st.y)
            if progress_xy is None or math.dist(xy, progress_xy) > 12:
                progress_xy, progress_at = xy, now
            if math.dist(xy, target) <= 70:
                if st.nav_active or st.moving:
                    c.game.cancel_navigation()
                target = a if target == b else b
                progress_xy, progress_at = xy, now
                say(f'[{ROLE}] 到达路点，切换巡逻目标 {target}')
                time.sleep(TICK)
                continue
            if (st.nav_active or st.moving) and now - progress_at >= 6:
                c.game.cancel_navigation()
                target = a if target == b else b
                progress_xy, progress_at = xy, now
                say(f'[{ROLE}] 6 秒无位移，取消卡住的寻路并改走 {target}')
                time.sleep(TICK)
                continue
            if not st.nav_active and not st.moving:
                c.game.navigate(MAP_ID, *target)
                progress_xy, progress_at = xy, now
                say(f'[{ROLE}] 巡逻寻路至 {target}')
            time.sleep(TICK)
    except KeyboardInterrupt:
        c.game.cancel_navigation()
        say(f'[{ROLE}] 收到停止指令，已取消寻路')
    except BaseException:
        c.game.cancel_navigation()
        raise


if __name__ == '__main__':
    main()
