"""Stage 2: record the 飞鞋 point where the alt stands in 逍遥村西区 (normally the arrival spot).

Entry: python -m factory.shoe [factory.toml]
Per client: read -> decide -> at most one action -> verify (the client's recorded point becomes the
current map + position) -> record shoe_recorded_at in factory.db. Re-running skips alts already done.
The alt must stand still ~1 s first: the server records ITS position, which lags a walking character.

decide() is pure (tests/test_factory_shoe.py).
"""
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from provisioner import native
from provisioner.game import Game, NotSent
from provisioner.memory import ProcessMemory
from provisioner.world import read_shoe_record, read_world

from . import db
from .config import ROOT, load_settings
from .phase import VILLAGE_MAP
from .runner import run_stage

ACTION = 'shoe_record'
SETTLE = 1.5            # standing still this long before recording
CONFIRM_WAIT = 3.0      # the recorded point must match within this long
TOLERANCE = 3           # px between the recorded point and the standing position


@dataclass(frozen=True)
class Decision:
    kind: str      # 'done' | 'verified' | 'fail' | 'wait' | 'record' | 'unconfirmed'
    reason: str


@dataclass
class Memo:
    sent_at: float | None = None
    still_xy: tuple | None = None
    still_since: float = 0.0

    def observe(self, world, now):
        xy = (round(world.x), round(world.y)) if world else None
        if xy != self.still_xy or (world and (world.moving or world.busy or world.in_battle)):
            self.still_xy, self.still_since = xy, now


def matches(record, world):
    return (record is not None and world is not None and record[0] == world.map_id
            and math.dist(record[1:], (world.x, world.y)) <= TOLERANCE)


def decide(world, record, alt_row, memo, now):
    if alt_row['shoe_recorded_at'] is not None:
        return Decision('done', '已记录飞鞋（账本）')
    if world is None or record is None:
        return Decision('wait', '加载中')
    if memo.sent_at is not None:
        if matches(record, world):
            return Decision('verified', f'飞鞋记录点 = 地图{record[0]} ({record[1]},{record[2]})')
        if now - memo.sent_at < CONFIRM_WAIT:
            return Decision('wait', '等记录点更新')
        return Decision('unconfirmed', f'{CONFIRM_WAIT:.0f}s 内记录点没变成当前位置（读到 {record}）')
    if world.map_id != VILLAGE_MAP:
        return Decision('fail', f'不在逍遥村西区（地图 {world.map_id}）')
    if world.verification:
        return Decision('wait', '验证码弹窗，等待答题')
    if world.in_battle or world.busy or world.nav_active or world.moving:
        return Decision('wait', '角色忙/战斗/移动中')
    if now - memo.still_since < SETTLE:
        return Decision('wait', '站稳后再记录')
    return Decision('record', f'记录飞鞋 地图{world.map_id} ({world.x:.0f},{world.y:.0f})，原记录点 {record}')


class ShoeJob:
    def __init__(self, client, account, slot, settings, log_):
        self.c, self.account, self.slot, self.s, self.log = client, account, slot, settings, log_

    def run(self):
        started = time.monotonic()
        result = {'name': self.c.name, 'pid': self.c.session.pid, 'char_id': self.c.char_id, 'ok': False}
        conn = db.connect(self.s.db_path)
        cid = self.c.char_id
        db.register_alt(conn, cid, self.account, self.slot, self.c.name, time.time())
        memo, last_reason = Memo(), None
        try:
            with ProcessMemory(self.c.session.pid, self.c.session.base) as mem:
                game = Game(self.c.session, mem)
                try:
                    while True:
                        now = time.monotonic()
                        if now - started > self.s.shoe_timeout:
                            raise RuntimeError(f'{self.s.shoe_timeout:.0f}s 内没有完成')
                        if not native.alive(self.c.session.pid):
                            raise RuntimeError('游戏进程已退出')
                        world, record = read_world(mem), read_shoe_record(mem)
                        if world and world.char_id != cid:
                            raise RuntimeError(f'角色变了 {cid} -> {world.char_id}')
                        row = db.alt(conn, cid)
                        if row['quarantined']:
                            raise RuntimeError(f'已隔离: {row["last_error"]}')
                        memo.observe(world, now)
                        d = decide(world, record, row, memo, now)
                        if d.reason != last_reason:
                            self.log.info('%s', d.reason)
                        last_reason = d.reason
                        if d.kind == 'done':
                            result.update(ok=True, skipped=True)
                            break
                        if d.kind == 'verified':
                            db.complete_action(conn, cid, time.time(), shoe_recorded_at=time.time())
                            result.update(ok=True, record=list(record),
                                          seconds_to_verify=round(now - memo.sent_at, 2))
                            break
                        if d.kind == 'fail':
                            raise RuntimeError(d.reason)
                        if d.kind == 'unconfirmed':
                            memo.sent_at = None
                            if db.record_failure(conn, cid, d.reason, time.time()):
                                raise RuntimeError(f'连续失败 {db.MAX_RETRIES} 次，已隔离')
                        elif d.kind == 'record':
                            result.setdefault('record_before', list(record))
                            db.mark_pending(conn, cid, ACTION, time.time())
                            try:
                                game.shoe_record()
                            except NotSent as e:
                                db.clear_pending(conn, cid, time.time(), str(e))
                                raise
                            memo.sent_at = now
                        time.sleep(self.s.tick)
                finally:
                    game.close()
        except Exception as e:
            result['error'] = f'{type(e).__name__}: {e}'
            self.log.error('失败: %s', e, exc_info=not isinstance(e, RuntimeError))
        finally:
            conn.close()
        result['seconds'] = round(time.monotonic() - started, 1)
        return result


def main():
    settings = load_settings(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'factory.toml')
    return run_stage('shoe', settings, lambda c, account, slot, log_: ShoeJob(c, account, slot, settings, log_))


if __name__ == '__main__':
    sys.exit(main())
