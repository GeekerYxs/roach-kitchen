"""junk_watch.py (user 2026-11-07): one tool per PC drops data/drop_names.txt items from every game window after each
battle, never from roles in data/drop_skip_roles.txt; native.call takes a per-window lock (no game)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

HERE = Path(__file__).resolve().parent.parent / 'research' / 'shitu'
sys.path.insert(0, str(HERE))

import junk_watch as J  # noqa: E402
import trash  # noqa: E402

TABLE = {31800: NS(name='锁住的藏宝盒', type=0x400), 9801: NS(name='回城卷', type=0x400),
         50: NS(name='定身丸', type=0x802)}
TITLE = '什么什么大冒险2(①逍遥村敬老院)-{}_Oct 27 2026《什么什么大冒险》制作委员会QQ群:515616289'


def st(battle=False, busy=False, dialog=None, quiz=False, map_id=1):
    return NS(in_battle=battle, busy=busy, dialog=dialog, verification=quiz, map_id=map_id)


class Game:
    def __init__(self, bag, drops=True):
        self.mem, self.state, self.sent, self.drops = self, st(), [], drops
        self.bag = [NS(slot=i, item_id=x, quantity=3) for i, x in enumerate(bag)]
        self.game = NS(send=self.send)

    def send(self, op, body):
        self.sent.append(op)
        if self.drops:
            self.bag = [s for s in self.bag if s.slot != body[5]]

    def world(self):
        return self.state


class Base(unittest.TestCase):
    def setUp(self):
        ps = [mock.patch.object(trash, 'names', lambda: frozenset({'锁住的藏宝盒'})),
              mock.patch.object(J.w, 'read_bag', lambda m: m.bag)]
        for p in ps:
            p.start()
            self.addCleanup(p.stop)
        self.logged, self.said = [], []

    def step(self, r, now):
        r.step(now, TABLE, say=self.said.append, log=lambda *a: self.logged.append(a))


class Steps(Base):
    def test_first_look_drops_names_only(self):
        c = Game([31800, 9801, 50])
        r = J.Role('a', c)
        self.step(r, 0)
        self.assertEqual(c.sent, [0x48])                     # 回城卷 / 定身丸 stay: not in the file
        self.step(r, 1.0)
        self.assertEqual(self.logged, [])                    # checked only VERIFY_AFTER later
        self.step(r, 2.0)
        self.assertEqual(self.logged, [('a', 1, [(0, 31800, '锁住的藏宝盒', 3, '已丢')])])

    def test_after_battle_not_during(self):
        c = Game([])
        r = J.Role('a', c)
        self.step(r, 0)                                      # nothing yet; next look in FALLBACK
        c.bag = [NS(slot=4, item_id=31800, quantity=1)]
        c.state = st(battle=True)
        self.step(r, 10)
        self.assertEqual(c.sent, [])
        c.state = st()
        self.step(r, 20)                                     # battle over: wait AFTER_BATTLE for the loot
        self.assertEqual(c.sent, [])
        self.step(r, 21)
        self.assertEqual(c.sent, [0x48])

    def test_waits_while_busy(self):
        for s in (st(busy=True), st(dialog=object()), st(quiz=True)):
            c = Game([31800])
            c.state = s
            r = J.Role('a', c)
            self.step(r, 0)
            self.assertEqual(c.sent, [], s)
            c.state = st()
            self.step(r, 0.5)
            self.assertEqual(c.sent, [0x48], s)

    def test_fallback_without_battles(self):
        c = Game([])
        r = J.Role('a', c)
        self.step(r, 0)
        c.bag = [NS(slot=0, item_id=31800, quantity=1)]
        self.step(r, J.FALLBACK - 1)
        self.assertEqual(c.sent, [])
        self.step(r, J.FALLBACK)
        self.assertEqual(c.sent, [0x48])

    def test_refused_drop_left_alone(self):
        c = Game([31800], drops=False)
        r = J.Role('a', c)
        self.step(r, 0)
        self.step(r, 2)
        self.assertEqual(self.logged[0][2][0][4], '丢不掉')
        r.due = 0
        self.step(r, 3)
        self.assertEqual(c.sent, [0x48])                     # not sent again inside STUCK_QUIET
        r.due = 0
        self.step(r, 3 + J.STUCK_QUIET)
        self.assertEqual(c.sent, [0x48, 0x48])


class Windows(Base):
    def test_role_of(self):
        self.assertEqual(J.role_of(['DIEmWin', TITLE.format('欧皇丨花花乀')]), '欧皇丨花花乀')
        self.assertEqual(J.role_of([TITLE.format('奥德赛26')]), '奥德赛26')
        self.assertIsNone(J.role_of(['DIEmWin', 'Default IME']))

    def test_skip_list_and_closed_windows(self):
        f = Path(tempfile.mkdtemp()) / 'skip.txt'
        f.write_text('# x\n欧皇丨花花乀   # 大号\n', encoding='utf-8')
        wins = {1: [TITLE.format('欧皇丨花花乀')], 2: [TITLE.format('奥德赛26')]}
        made = []
        with mock.patch.object(J, 'SKIP_FILE', f), mock.patch.object(J, '_skip', (None, frozenset())):
            watch = J.Watch(connect=lambda n: made.append(n) or Game([]), windows=lambda: dict(wins),
                            say=self.said.append)
            watch.tick(0, TABLE)
            self.assertEqual(made, ['奥德赛26'])
            del wins[2]
            watch.tick(J.SCAN_EVERY, TABLE)
            self.assertEqual(watch.roles, {})
            f.write_text('', encoding='utf-8')
            os.utime(f, (1, 1))
            watch.tick(2 * J.SCAN_EVERY, TABLE)
            self.assertEqual(made, ['奥德赛26', '欧皇丨花花乀'])     # out of the skip list: watched now

    def test_one_bad_window_does_not_stop_the_rest(self):
        wins = {1: [TITLE.format('a')], 2: [TITLE.format('b')]}
        good = Game([31800])

        def connect(n):
            if n == 'a':
                raise RuntimeError('不在游戏世界')
            return good
        with mock.patch.object(J, 'skip_roles', lambda: frozenset()):
            watch = J.Watch(connect=connect, windows=lambda: wins, say=self.said.append)
            watch.tick(0, TABLE)
        self.assertEqual(list(watch.roles), [2])
        self.assertEqual(good.sent, [0x48])

    def test_names_only_no_prank_types(self):
        self.assertFalse(trash.is_named(TABLE[50]))          # 定身丸: trash.py drops it for apprentices, not here
        self.assertTrue(trash.is_trash(TABLE[50]))


class Lock(unittest.TestCase):
    def test_call_holds_the_window_lock(self):
        from provisioner import native
        order = []
        status = iter([{'call_count': 5}, {'call_count': 6, 'call_result': 7}])
        k = mock.MagicMock()
        k.CreateMutexW.return_value = 99
        k.WaitForSingleObject.side_effect = lambda h, ms: order.append(('wait', h)) or 0
        k.ReleaseMutex.side_effect = lambda h: order.append(('release', h))
        with mock.patch.object(native, '_k', k), mock.patch.dict(native._call_mutex, clear=True), \
                mock.patch.object(native, 'read_status', lambda pid: next(status)), \
                mock.patch.object(native, '_command', lambda s, kind, req: order.append('cmd') or 1):
            self.assertEqual(native.call(NS(pid=42), 0x1234), 7)
        self.assertEqual(order, [('wait', 99), 'cmd', ('release', 99)])
        self.assertIn('smsm2_call_42', k.CreateMutexW.call_args[0][2])

    def test_timeout_raises(self):
        from provisioner import native
        k = mock.MagicMock()
        k.WaitForSingleObject.return_value = 0x102
        with mock.patch.object(native, '_k', k), mock.patch.dict(native._call_mutex, clear=True):
            with self.assertRaises(RuntimeError):
                native.call(NS(pid=1), 0x1234)
        k.ReleaseMutex.assert_not_called()


if __name__ == '__main__':
    unittest.main()
