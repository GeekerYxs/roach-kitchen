"""Junk run: an alt that handed quest 78 in (still holding its 料理) sells what it carries before the receiver takes
the 料理 and all its gold (stage 9), so the shop money ends up in the treasury instead of being deleted with the alt.

Entry: python -m factory.sell [factory.toml]   (the supervisor runs it for every alt in phase sell_junk)
User, 2026-10-20: alts sell everything sellable before the delete, the worn 专打屁屁扳手 too (taken off first).
  1. walk on map 81 from the hand-in spot to 军医花袭人 at the PP鸡 landing (1152,932) (no battles on that path in
     stage 6; any battle on the way is escaped)
  2. take off every worn item the alt rule sells (factory/items.py) into a free bag slot: 0x47 move item, verified
     in the equipment table and the bag
  3. sell the alt-rule bag slots at 花袭人 (factory/supply.py ShopClient: fresh open per item, verified per slot),
     close the dialog
  4. ledger sold_at = now (also after a partial sale: an item the shop refuses must not loop the alt), walk back to
     the receiver post; phase.derive_phase then puts the alt into queue_receiver
Mid-chain (no 料理 yet, phase.bag_blocked: the bag is too full for the quest-78 materials): steps 1 and 3 only,
no unequip, no sold_at (the final run still comes), and the alt stays at 花袭人; still blocked afterwards -> quarantine.
Live 2026-10-20 (client 2.99, mvp01r1 at 小美): 扳手 + 5 新手装 sold 6/6, gold 0 -> 515 = exactly half the ItemLib
prices, 8.9 s.
Pure parts: factory/items.py (junk_count, unequip_plan), phase.derive_phase (tests).
"""
import math
import sys
import time
from pathlib import Path

from provisioner import native
from provisioner.game import FIGHT_ESCAPE, Game
from provisioner.memory import ProcessMemory
from provisioner.world import (item_count, read_bag, read_bag_capacity, read_dialog, read_equipment, read_gold,
                               read_quest, read_world)

from . import db, items
from .config import ROOT, load_settings
from .observe import observe
from .phase import COAST_MAP, DISH_ITEM, QUEST_ID, SELL_JUNK, derive_phase
from .runner import run_stage
from .supply import NURSE, SHOP_RANGE, ShopClient

ARRIVE_RANGE = 120
WALK_TIMEOUT = 90.0
NAV_RETRY = 3.0
STALL = 6.0                     # path-finder 'active' but not moving this long -> cancel and path again (live: mvp04r1
                                # stopped at (1200,1080) on the way back, 2026-10-20)
ESCAPE_EVERY = 2.0
UNEQUIP_WAIT = 3.0


class SellJob:
    def __init__(self, client, account, slot, settings, log_):
        self.c, self.account, self.slot, self.s, self.log = client, account, slot, settings, log_

    def run(self):
        started = time.monotonic()
        cid = self.c.char_id
        result = {'name': self.c.name, 'pid': self.c.session.pid, 'char_id': cid, 'ok': False}
        conn = db.connect(self.s.db_path)
        db.register_alt(conn, cid, self.account, self.slot, self.c.name, time.time())
        try:
            with ProcessMemory(self.c.session.pid, self.c.session.base) as mem:
                game = Game(self.c.session, mem)
                shop = ShopClient(game, mem, self.log)
                try:
                    plan = self._phase(conn, mem)
                    if plan.phase != SELL_JUNK:
                        self.log.info('不用卖（阶段 %s：%s）', plan.phase, plan.reason)
                        return {**result, 'ok': True, 'skipped': True}
                    quest = read_quest(mem, QUEST_ID)
                    final = item_count(read_bag(mem) or (), DISH_ITEM) > 0 or bool(quest and quest.done)
                    self._run(conn, mem, game, shop, result, final)
                    after = self._phase(conn, mem)
                    if not final and after.phase == SELL_JUNK:
                        db.record_failure(conn, cid, f'卖完背包还是满的（{after.reason}）', time.time(), max_retries=1)
                        raise RuntimeError(f'卖完背包还是满的，已隔离: {after.reason}')
                    result['ok'] = True
                finally:
                    if read_dialog(mem) is not None:
                        shop.close()
                    game.close()
        except Exception as e:
            result['error'] = f'{type(e).__name__}: {e}'
            self.log.error('失败: %s', e, exc_info=not isinstance(e, RuntimeError))
        finally:
            conn.close()
            result['seconds'] = round(time.monotonic() - started, 1)
        return result

    def _phase(self, conn, mem):
        obs = observe(mem, read_world(mem))
        if obs is None:
            raise RuntimeError('读不到角色状态')
        plan = derive_phase(obs, db.ledger(conn, self.c.char_id), db.station_roles(conn))
        db.save_observation(conn, obs, plan, time.time())
        return plan

    def _run(self, conn, mem, game, shop, result, final=True):
        """final: the alt holds its 料理 (the last sale before the delete); else only make room in the bag."""
        table = items.table()
        gold_before = read_gold(mem)
        if read_dialog(mem) is not None:
            shop.close()
        self.walk(mem, game, NURSE.spot, '去花袭人')
        result['unequipped'] = self.unequip(mem, game, table) if final else 0
        bag = read_bag(mem)
        slots = items.sell_slots(bag, table)
        self.log.info('在花袭人卖 %d 格（约 %d 金币）', len(slots), items.shop_value(slots, table))
        try:
            result['sold'] = shop.sell(NURSE, slots)
            left = items.sell_slots(read_bag(mem), table)
            if left:        # live 2026-10-20: one 1-gold belt of 13 was not confirmed in time; one more pass
                self.log.info('还有 %d 格没卖掉，再试一次', len(left))
                result['sold'] += shop.sell(NURSE, left)
        finally:
            shop.close()
        result['to_sell'] = len(slots)
        gold = read_gold(mem)
        result['gold_change'] = None if gold is None or gold_before is None else gold - gold_before
        if final:
            db.complete_action(conn, self.c.char_id, time.time(), sold_at=time.time())
        db.log_event(conn, time.time(), 'sell', f'{"" if final else "腾背包 "}卖 {result["sold"]}/{len(slots)} 格 '
                     f'脱 {result["unequipped"]} 件 金币变化 {result["gold_change"]}', char_id=self.c.char_id)
        self.log.info('卖了 %d/%d 格，脱下 %d 件，金币 %s -> %s', result['sold'], len(slots), result['unequipped'],
                      gold_before, gold)
        if not final:
            return          # back to queue_coast: the coast leader calls it over from here
        try:
            self.walk(mem, game, self.s.receiver_post, '回收货点')
        except RuntimeError as e:     # sold and booked already; the receiver walks the alt over itself
            self.log.warning('没走回收货点（%s），收货人会叫它过去', e)

    def unequip(self, mem, game, table):
        """Take off the worn items the alt rule sells. -> how many came off."""
        done = 0
        for equip_slot, bag_slot in items.unequip_plan(read_equipment(mem), read_bag(mem),
                                                       read_bag_capacity(mem) or 0, table):
            item = next(e.item_id for e in read_equipment(mem) if e.slot == equip_slot)
            self.log.info('脱下装备格 %d 的 %s 到背包第 %d 格', equip_slot, table[item].name, bag_slot)
            game.unequip(equip_slot, bag_slot)
            end = time.monotonic() + UNEQUIP_WAIT
            while time.monotonic() < end:
                worn = {e.slot for e in read_equipment(mem) or ()}
                if equip_slot not in worn and any(s.slot == bag_slot and s.item_id == item for s in read_bag(mem) or ()):
                    done += 1
                    break
                time.sleep(0.1)
            else:
                self.log.warning('装备格 %d %.0fs 内没脱下来', equip_slot, UNEQUIP_WAIT)
        return done

    def walk(self, mem, game, point, label):
        """Path-finder on map 81 to `point`, escaping battles. Raises when it does not get there."""
        end, last_nav, last_escape = time.monotonic() + WALK_TIMEOUT, 0.0, 0.0
        while time.monotonic() < end:
            if not native.alive(self.c.session.pid):
                raise RuntimeError('游戏进程已退出')
            w = read_world(mem)
            if w is None:
                time.sleep(0.3)
                continue
            if w.char_id != self.c.char_id:
                raise RuntimeError('角色变了')
            if w.map_id != COAST_MAP:
                raise RuntimeError(f'不在平静海岸2区（地图 {w.map_id}）')
            now = time.monotonic()
            if w.in_battle:
                if now - last_escape >= ESCAPE_EVERY:
                    self.log.info('%s 路上遇到战斗，逃跑', label)
                    game.fight_command(FIGHT_ESCAPE)
                    last_escape = now
            elif math.dist((w.x, w.y), point) <= ARRIVE_RANGE:
                if w.nav_active:
                    game.cancel_navigation()
                return
            elif w.nav_active and w.still_for >= STALL and now - last_nav >= STALL:
                self.log.info('%s：%.0fs 没动，重新寻路', label, w.still_for)
                game.cancel_navigation()
                last_nav = now - NAV_RETRY
            elif not w.nav_active and not w.moving and now - last_nav >= NAV_RETRY:
                self.log.info('%s（距离 %.0f）', label, math.dist((w.x, w.y), point))
                game.navigate(COAST_MAP, *point)
                last_nav = now
            time.sleep(self.s.tick)
        raise RuntimeError(f'{WALK_TIMEOUT:.0f}s 内没走到（{label}）')


assert ARRIVE_RANGE <= SHOP_RANGE      # close enough for the shop as supply.py measures it


def main():
    settings = load_settings(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'factory.toml')
    return run_stage('sell', settings, lambda c, account, slot, log_: SellJob(c, account, slot, settings, log_),
                     map_id=COAST_MAP, map_name='平静海岸2区')


if __name__ == '__main__':
    sys.exit(main())
