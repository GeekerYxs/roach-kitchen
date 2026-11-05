"""quanshou.fetch (user 2026-11-05): an apprentice out of 回城卷 with no lender in reach is fetched by the master: on the
same map the master walks over; else the apprentice flies to its 飞鞋 record when the master is there or can fly to the
same spot. home() sends the apprentices first and the master last, so the master is still out there to fetch."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

HERE = Path(__file__).resolve().parent.parent / 'research' / 'shitu'
sys.path.insert(0, str(HERE))

import quanshou as q  # noqa: E402
import shoe_point  # noqa: E402


class Role:
    def __init__(self, name, map_id, rec=None):
        self.name, self.mem, self.map_id, self.rec = name, self, map_id, rec

    def world(self):
        return NS(map_id=self.map_id, x=100, y=100, in_battle=False, moving=False)


def run(c, m, used=None):
    log = []
    used = used or {}

    def fly(x):
        log.append(('fly', x.name))
        x.map_id = x.rec[0]
        return True
    with mock.patch.object(q.t, 'Client', lambda n: m), mock.patch('common.MASTERS', (m.name,)), \
            mock.patch.object(q.w, 'read_shoe_record', lambda mem: mem.rec), \
            mock.patch.object(shoe_point, 'used_at', lambda n: used.get(n)), \
            mock.patch.object(q, '_fly', fly), \
            mock.patch.object(q, '_master_walks_to', lambda c, mc: log.append(('walk', mc.name)) or True), \
            mock.patch.object(q, 'borrow', lambda c: log.append(('borrow', c.name)) or True), \
            mock.patch.object(q, 'scroll', lambda x: log.append(('scroll', x.name))), \
            mock.patch.object(q.t, 'say', lambda s: None):
        got = q.fetch(c)
    return got, log


class Fetch(unittest.TestCase):
    def test_same_map_master_walks_over(self):
        got, log = run(Role('a', 141), Role('M', 141))
        self.assertTrue(got)
        self.assertEqual(log, [('walk', 'M'), ('borrow', 'a')])

    def test_apprentice_flies_to_the_master_s_map(self):
        got, log = run(Role('a', 750, rec=(141, 3410, 252)), Role('M', 141))
        self.assertEqual(log, [('fly', 'a'), ('walk', 'M'), ('borrow', 'a')])

    def test_both_fly_to_the_shared_record(self):
        m = Role('M', 20, rec=(141, 3400, 250))
        got, log = run(Role('a', 750, rec=(141, 3410, 252)), m)
        self.assertEqual(log, [('fly', 'a'), ('fly', 'M'), ('walk', 'M'), ('borrow', 'a')])

    def test_master_home_already_goes_back_after(self):
        m = Role('M', 1, rec=(141, 3400, 250))
        got, log = run(Role('a', 750, rec=(141, 3410, 252)), m)
        self.assertEqual(log[-1], ('scroll', 'M'))

    def test_cooldown_or_no_record_gives_up(self):
        import time
        got, log = run(Role('a', 750, rec=(141, 3410, 252)), Role('M', 20, rec=(141, 3400, 250)),
                       used={'a': time.time()})
        self.assertFalse(got)
        self.assertEqual(log, [])
        got, log = run(Role('a', 750), Role('M', 20))
        self.assertFalse(got)

    def test_master_never_fetches_itself(self):
        got, log = run(Role('M', 750), Role('M', 750))
        self.assertFalse(got)


class Wiring(unittest.TestCase):
    def test_scroll_falls_back_to_fetch_and_home_sends_master_last(self):
        src = (HERE / 'quanshou.py').read_text(encoding='utf-8')
        self.assertIn('if slot is None and (borrow(c) or fetch(c)):', src)
        r4 = (HERE / 'r4_util.py').read_text(encoding='utf-8')
        body = r4[r4.index('def home():'):r4.index('def leave(')]
        self.assertLess(body.index('t.each(cs[1:], one)'), body.index('one(cs[0])'))


if __name__ == '__main__':
    unittest.main()
