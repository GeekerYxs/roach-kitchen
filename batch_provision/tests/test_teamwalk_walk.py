"""teamwalk._walk: battle time on the way does not count toward the walk timeout (round 5, 亿万44 at a 通天花)."""
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'shitu'))

import teamwalk  # noqa: E402


class FakeClient:
    """In battle for `battle` seconds, then standing on the goal."""
    def __init__(self, battle, arrive=True):
        self.t0, self.battle, self.arrive = time.monotonic(), battle, arrive
        self.name = 'x'
        self.game = NS(navigate=lambda *a: None, cancel_navigation=lambda: None)

    def world(self):
        fighting = time.monotonic() - self.t0 < self.battle
        xy = (10, 10) if self.arrive and not fighting else (500, 500)
        return NS(x=xy[0], y=xy[1], in_battle=fighting, moving=False, nav_active=not fighting)


class Fighter:
    def tick(self, now):
        pass

    def reset(self):
        pass


class Walk(unittest.TestCase):
    def test_battle_longer_than_timeout_still_arrives(self):
        teamwalk._walk(FakeClient(battle=0.8), Fighter(), (10, 10), 20, 0.5)

    def test_never_arriving_stops_within_three_timeouts(self):
        t0 = time.monotonic()
        with self.assertRaises(teamwalk.t.Stop):
            teamwalk._walk(FakeClient(battle=5, arrive=False), Fighter(), (10, 10), 20, 0.4)
        self.assertLess(time.monotonic() - t0, 1.6)


if __name__ == '__main__':
    unittest.main()
