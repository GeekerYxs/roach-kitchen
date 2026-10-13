"""A lost alt (outside the village and the coast, no team carrying it) goes home: 飞鞋 if allowed, else 回城卷.

Shared by the relay (factory/relay.py) and the supervisor (factory/supervisor.py). The decision is welltrain's
decide_member_return (unit-tested there); this only drives it for one alt without a leader.
"""
import time

from provisioner.game import Game, NotSent
from provisioner.memory import ProcessMemory
from provisioner.world import read_bag, read_shoe_record, read_team, read_world

from . import db
from .observe import observe
from .phase import VILLAGE_MAP, return_method
from .welltrain import ACTION_SCROLL, ACTION_SHOE, Home, decide_member_return, scroll_slot

HOME_TIMEOUT = 60.0


class HomeJob:
    def __init__(self, client, settings, log_):
        self.c, self.s, self.log = client, settings, log_

    def run(self):
        c, memo = self.c, Home()
        result = {'name': c.name, 'char_id': c.char_id, 'ok': False}
        started, last = time.monotonic(), None
        conn = db.connect(self.s.db_path)
        try:
            with ProcessMemory(c.session.pid, c.session.base) as mem:
                game = Game(c.session, mem)
                try:
                    while time.monotonic() - started < HOME_TIMEOUT:
                        now, wall = time.monotonic(), time.time()
                        w, team = read_world(mem), read_team(mem)
                        obs = observe(mem, w)
                        record = read_shoe_record(mem)
                        shoe_ok = (obs is not None and record is not None and record[0] == VILLAGE_MAP
                                   and return_method(obs, db.ledger(conn, c.char_id), wall) == 'shoe')
                        d = decide_member_return(w, team, -1, shoe_ok, scroll_slot(read_bag(mem)), memo, now)
                        if d.reason != last:
                            self.log.info('回村: %s', d.reason)
                        last = d.reason
                        row = db.alt(conn, c.char_id)
                        if d.kind == 'done':
                            if row['pending_action'] == ACTION_SHOE:
                                db.complete_action(conn, c.char_id, wall, shoe_used_at=row['pending_at'] or wall)
                            elif row['pending_action'] == ACTION_SCROLL:
                                db.complete_action(conn, c.char_id, wall)
                            return {**result, 'ok': True}
                        if d.kind == 'stuck':
                            return {**result, 'error': d.reason}
                        if d.kind == 'unconfirmed':
                            db.clear_pending(conn, c.char_id, wall, d.reason)
                            memo.tried.add(memo.method)
                            memo.method = memo.sent_at = None
                        elif d.kind in ('shoe', 'scroll'):
                            db.mark_pending(conn, c.char_id, ACTION_SHOE if d.kind == 'shoe' else ACTION_SCROLL, wall)
                            try:
                                game.shoe_return() if d.kind == 'shoe' else game.use_item(d.arg)
                            except NotSent as e:
                                db.clear_pending(conn, c.char_id, wall, str(e))
                                memo.tried.add(d.kind)
                                continue
                            memo.method, memo.sent_at = d.kind, now
                        time.sleep(self.s.tick)
                    return {**result, 'error': f'回村 {HOME_TIMEOUT:.0f}s 内没完成'}
                finally:
                    game.close()
        finally:
            conn.close()
