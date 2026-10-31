"""take224.to_boss and the 飞鞋 hour: its return to the 大个王 record is written to shoe_used.json (shoe_point.fly in
B+ snake / king checks the same hour), and a return still cooling down is not tried (2026-10-31 live: a return in
cooldown just does nothing, 6 s lost)."""
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'shitu'))

import shoe_point  # noqa: E402
import take224  # noqa: E402

REC = (20, 4400, 2550)                       # next to 大个王 (4398, 2553)


class Client:
    def __init__(self, arrive):
        self.name, self.mem, self.returns = 'x', None, 0
        self.pos = (792, 2692)
        self.arrive = arrive
        self.game = NS(shoe_return=self.shoe_return)

    def shoe_return(self):
        self.returns += 1
        if self.arrive:
            self.pos = REC[1:]

    def world(self):
        return NS(map_id=20, x=self.pos[0], y=self.pos[1])


class ToBoss(unittest.TestCase):
    def run_to_boss(self, c, used):
        marks = []
        with mock.patch.object(take224.w, 'read_shoe_record', lambda mem: REC), \
                mock.patch.object(shoe_point, 'used_at', lambda n: used), \
                mock.patch.object(shoe_point, 'mark_used', lambda n, to: marks.append((n, tuple(to)))), \
                mock.patch.object(take224, 'walk', lambda c, xy, why: None), \
                mock.patch.object(take224.t, 'say', lambda s: None), \
                mock.patch.object(take224.time, 'sleep', lambda s: None):
            take224.to_boss(c)
        return marks

    def test_use_is_recorded(self):
        c = Client(arrive=True)
        self.assertEqual(self.run_to_boss(c, None), [('x', REC)])
        self.assertEqual(c.returns, 1)

    def test_no_effect_not_recorded(self):
        c = Client(arrive=False)
        self.assertEqual(self.run_to_boss(c, None), [])
        self.assertEqual(c.returns, 1)

    def test_cooldown_walks(self):
        c = Client(arrive=True)
        self.assertEqual(self.run_to_boss(c, time.time() - 600), [])
        self.assertEqual(c.returns, 0)


if __name__ == '__main__':
    unittest.main()
