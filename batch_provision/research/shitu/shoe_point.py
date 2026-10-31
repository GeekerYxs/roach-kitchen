"""飞鞋 (0x82) record / return for the whole team at a field or town spot (B+ route, user 2026-10-30).

    python -X utf8 research/shitu/shoe_point.py record MAP X Y NAME..     everybody standing within NEAR of (X, Y) on MAP
                                                                         records there (read back and checked)
    python -X utf8 research/shitu/shoe_point.py fly MAP X Y MASTER APP..  everybody flies to that record, master first

User rules: a record is free and can be redone any time, a return works once per hour; mazes (maps.csv kind 3) can
not be recorded, towns and fields can. So the route records where the team walks past anyway (遗忘洞穴 entrance in
无尽平原2区, 遗址 entrance in 苦无沙漠1区) and flies there the next time instead of crossing the field (monsters).

fly is all or nothing up front: when anybody's record is not at (X, Y) or anybody returned less than an hour ago
(logs/shoe_used.json, kept across batches for the master), nobody flies and it exits 1 -> the route (soft cmd) walks
as before. The master flies first; when he does not arrive nobody else flies either. Exit 0 = everybody is there.
"""
import math
import sys
import time

COOLDOWN = 3600 + 60           # user: once per hour; a minute of margin for clock / server rounding
NEAR = 200                     # px: a team stops spread around the leader's goal
ARRIVE = 60                    # px from the record after a return


def record_ok(rec, map_id, xy, near=NEAR):
    """read_shoe_record (map, x, y) is on map_id within near of xy."""
    return bool(rec) and rec[0] == map_id and math.dist(rec[1:], xy) <= near


def cooldown_left(used_at, now):
    """Seconds until the next return is allowed (0 = now); used_at None = never used (as far as we know)."""
    return 0 if used_at is None else max(0, int(used_at + COOLDOWN - now))


def why_not(name, rec, used_at, now, map_id, xy):
    """None when this role can fly to (map_id, xy) now, else the reason (Chinese, for the log)."""
    if not record_ok(rec, map_id, xy):
        return f'{name} 的飞鞋记录 {rec} 不在地图 {map_id} {xy} 附近'
    left = cooldown_left(used_at, now)
    if left:
        return f'{name} 的飞鞋还要 {left // 60} 分 {left % 60} 秒才能再用'
    return None


def _used_file():
    from common import LOGS
    return LOGS / 'shoe_used.json'


def used_at(name):
    from bai_shi import load_state
    return load_state(_used_file()).get(name, {}).get('used', {}).get('at')


def mark_used(name, to):
    """One return spent (take224.to_boss uses the 大个王 record too: the hour must count it)."""
    from bai_shi import mark
    mark(name, 'used', path=_used_file(), at=time.time(), to=list(to))


def _settle(c, t):
    """Out of any battle and standing still (the record takes the SERVER position, shoe_dagewang.py)."""
    from quanshou import flee
    if c.world().in_battle:
        flee(c)
        t.wait(lambda: not c.world().in_battle, 60, f'{c.name} 战斗结束')
    t.wait(lambda: (s := c.world()) and not s.moving, 10, f'{c.name} 站稳')


def record(map_id, xy, names):
    import trial_run as t
    from bai_shi import mark
    from provisioner import world as w
    cs = [t.Client(n) for n in names]
    for c in cs:
        _settle(c, t)
    time.sleep(1.5)
    bad = []
    for c in cs:
        st = c.world()
        if st.map_id != map_id or math.dist((st.x, st.y), xy) > NEAR:
            bad.append(c.name)
            t.say(f'[{c.name}] 不在记录点附近（地图 {st.map_id} ({st.x:.0f},{st.y:.0f})），不记')
            continue
        c.game.shoe_record()
    time.sleep(1.0)
    for c in cs:
        if c.name in bad:
            continue
        rec = w.read_shoe_record(c.mem)
        ok = record_ok(rec, map_id, xy)
        t.say(f'[{c.name}] 飞鞋记录 {rec} {"OK" if ok else "不对"}')
        if ok:
            mark(c.name, 'shoe_point', record=list(rec))
        else:
            bad.append(c.name)
    if bad:
        raise t.Stop(f'飞鞋没记上: {" ".join(bad)}（地图 {map_id} 是迷宫就记不了）')


def fly(map_id, xy, names):
    import trial_run as t
    from bai_shi import mark
    from provisioner import world as w
    cs = [t.Client(n) for n in names]
    sts = [c.world() for c in cs]
    if all(s.map_id == map_id and math.dist((s.x, s.y), xy) <= NEAR for s in sts):
        t.say(f'全员已在地图 {map_id} {xy} 附近，不用飞')
        return
    now = time.time()
    reasons = [r for c in cs if (r := why_not(c.name, w.read_shoe_record(c.mem), used_at(c.name), now, map_id, xy))]
    if reasons:
        raise t.Stop('不飞，照原路走：' + '；'.join(reasons))
    for c in cs:
        c.game.cancel_navigation()
        if c.team():
            c.game.team_leave()
    for c in cs:
        t.wait(lambda: not c.team(), 5, f'{c.name} 离队')
    flown = []
    for c in cs:                                   # names[0] = the master: when he can't go, nobody goes
        _settle(c, t)
        rec = w.read_shoe_record(c.mem)
        c.game.shoe_return()
        try:
            t.wait(lambda: (s := c.world()) and s.map_id == rec[0] and math.dist((s.x, s.y), rec[1:]) <= ARRIVE,
                   6, f'{c.name} 飞到 {rec}')
        except t.Stop:
            st = c.world()
            msg = f'{c.name} 飞鞋没生效（现在地图 {st.map_id} ({st.x:.0f},{st.y:.0f})）'
            if flown:                              # half the team on another map: everybody home, the route goes on
                from quanshou import scroll       # from 逍遥村 (pp_chain / form_team know that start)
                for o in cs:
                    if o.world().map_id not in (1, 8):
                        scroll(o)
                msg += '，已飞的人和没飞的人都回城'
            raise t.Stop(msg)
        flown.append(c.name)
        mark_used(c.name, rec)
        t.say(f'[{c.name}] 飞鞋到了 {rec}')


def main(argv):
    op, map_id, x, y, *names = argv
    if op not in ('record', 'fly') or not names:
        raise SystemExit(__doc__)
    (record if op == 'record' else fly)(int(map_id), (int(x), int(y)), names)


if __name__ == '__main__':
    import trial_run as t
    try:
        main(sys.argv[1:])
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
