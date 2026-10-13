"""Stage 1: an alt that arrived in 逍遥村西区 eats its one (御)小肉林 30188 (auto full HP after each battle).

Entry: python -m factory.meat [factory.toml]
Attaches to every client with our DLL that is in the world on map 1. Per client: read -> decide -> at most
one action -> verify (count 1 -> 0) -> record meat_at in factory.db. Re-running skips alts already done.

decide() is pure (tests/test_factory_meat.py).
"""
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from provisioner import native
from provisioner.game import Game, NotSent
from provisioner.memory import ProcessMemory
from provisioner.world import item_count, read_bag, read_level, read_world

from . import db
from .config import ROOT, load_settings
from .phase import MEAT_ITEM, POTATO_ITEM, SCROLL_ITEM, VILLAGE_MAP
from .runner import run_stage

ACTION = 'meat'

CONFIRM_WAIT = 5.0      # bag count must drop within this long after the request


@dataclass(frozen=True)
class Decision:
    kind: str      # 'done' | 'verified' | 'skip' | 'fail' | 'wait' | 'use' | 'unconfirmed'
    reason: str
    arg: object = None


@dataclass
class Memo:
    sent_at: float | None = None
    count_before: int | None = None


def decide(world, bag, alt_row, memo, now):
    """world: WorldState or None; bag: tuple of BagSlot or None; alt_row: factory.db alts row."""
    if alt_row['meat_at'] is not None:
        return Decision('done', '已吃过小肉林（账本）')
    if world is None or bag is None:
        return Decision('wait', '加载中')
    count = item_count(bag, MEAT_ITEM)
    if memo.sent_at is not None:
        if count < memo.count_before:
            return Decision('verified', f'小肉林 {memo.count_before} -> {count}')
        if now - memo.sent_at < CONFIRM_WAIT:
            return Decision('wait', '等背包数量变化')
        return Decision('unconfirmed', f'{CONFIRM_WAIT:.0f}s 内小肉林数量没变（{count}）')
    if count == 0:
        if alt_row['pending_action'] == ACTION:
            return Decision('verified', '上次已发出请求，现在背包没有小肉林 -> 视为已吃')
        return Decision('skip', '背包里没有小肉林，跳过吃肉（用户 2026-10-13 定）')
    if world.map_id != VILLAGE_MAP:
        return Decision('fail', f'不在逍遥村西区（地图 {world.map_id}）')
    if world.verification:
        return Decision('wait', '验证码弹窗，等待答题')
    if world.in_battle or world.busy or world.nav_active or world.moving:
        return Decision('wait', '角色忙/战斗/移动中')
    slot = next(s for s in bag if s.item_id == MEAT_ITEM)
    return Decision('use', f'吃小肉林（背包第 {slot.slot} 格，{slot.quantity} 个）', slot)


class MeatJob:
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
                    self._evidence(mem, result, 'before')
                    while True:
                        now = time.monotonic()
                        if now - started > self.s.meat_timeout:
                            raise RuntimeError(f'{self.s.meat_timeout:.0f}s 内没有完成')
                        if not native.alive(self.c.session.pid):
                            raise RuntimeError('游戏进程已退出')
                        world, bag = read_world(mem), read_bag(mem)
                        if world and world.char_id != cid:
                            raise RuntimeError(f'角色变了 {cid} -> {world.char_id}')
                        row = db.alt(conn, cid)
                        if row['quarantined']:
                            raise RuntimeError(f'已隔离: {row["last_error"]}')
                        d = decide(world, bag, row, memo, now)
                        if d.reason != last_reason:
                            self.log.info('%s', d.reason)
                        last_reason = d.reason
                        if d.kind == 'done':
                            result.update(ok=True, skipped=True)
                            break
                        if d.kind == 'verified':
                            db.complete_action(conn, cid, time.time(), meat_at=time.time())
                            result.update(ok=True, seconds_to_verify=round(now - (memo.sent_at or now), 2))
                            break
                        if d.kind == 'skip':
                            db.set_ledger(conn, cid, time.time(), meat_at=time.time())
                            db.log_event(conn, time.time(), 'skip', d.reason, char_id=cid)
                            result.update(ok=True, skipped=True, no_meat=True)
                            break
                        if d.kind == 'fail':
                            raise RuntimeError(d.reason)
                        if d.kind == 'unconfirmed':
                            memo = Memo()
                            if db.record_failure(conn, cid, d.reason, time.time()):
                                raise RuntimeError(f'连续失败 {db.MAX_RETRIES} 次，已隔离')
                        elif d.kind == 'use':
                            db.mark_pending(conn, cid, ACTION, time.time())
                            try:
                                ret = game.use_item(d.arg.slot)
                            except NotSent as e:
                                db.clear_pending(conn, cid, time.time(), str(e))
                                raise
                            self.log.debug('send 0x0049 slot=%d -> %#x', d.arg.slot, ret)
                            memo = Memo(sent_at=now, count_before=item_count(bag, MEAT_ITEM))
                        time.sleep(self.s.tick)
                    self._evidence(mem, result, 'after')
                finally:
                    game.close()
        except Exception as e:
            result['error'] = f'{type(e).__name__}: {e}'
            self.log.error('失败: %s', e, exc_info=not isinstance(e, RuntimeError))
        finally:
            conn.close()
        result['seconds'] = round(time.monotonic() - started, 1)
        return result

    def _evidence(self, mem, result, when):
        """Log level and the stage-relevant bag counts (first live check of the level offset)."""
        bag, level = read_bag(mem), read_level(mem)
        counts = {i: item_count(bag, i) for i in (MEAT_ITEM, POTATO_ITEM, SCROLL_ITEM)} if bag else {}
        result[when] = {'level': level, 'meat': counts.get(MEAT_ITEM), 'potato': counts.get(POTATO_ITEM),
                        'scroll': counts.get(SCROLL_ITEM), 'bag_slots': len(bag) if bag else None}
        self.log.info('%s: 等级=%s 小肉林=%s 地瓜=%s 回城卷=%s 背包占用格=%s', '吃前' if when == 'before' else '吃后',
                      level, *(result[when][k] for k in ('meat', 'potato', 'scroll', 'bag_slots')))
        if when == 'before' and bag:
            self.log.debug('背包: %s', [(s.slot, s.item_id, s.quantity) for s in bag])


def main():
    settings = load_settings(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'factory.toml')
    return run_stage('meat', settings, lambda c, account, slot, log_: MeatJob(c, account, slot, settings, log_))


if __name__ == '__main__':
    sys.exit(main())
