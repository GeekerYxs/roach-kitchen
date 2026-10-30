"""dts.enter_room: click the 蛇王卧室 door again when one click does not teleport (no game)."""
import sys
import unittest
import unittest.mock
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'shitu'))

import dts  # noqa: E402


class FakeLead:
    name = 'm'

    def __init__(self, inside_after):
        self.clicks, self.inside_after = 0, inside_after
        self.game = SimpleNamespace(click_npc=self.click, select_dialog=lambda o: None)

    def click(self, npc):
        self.clicks += 1

    def world(self):
        x, y = dts.ROOM_XY if self.clicks >= self.inside_after else dts.DOOR_XY
        return SimpleNamespace(x=x, y=y)

    def dialog(self):
        return None


class EnterRoom(unittest.TestCase):
    def setUp(self):
        def wait(cond, timeout, what):            # no real waiting: one look, then the same Stop as trial_run.wait
            v = cond()
            if v:
                return v
            raise dts.t.Stop(f'{timeout}s 内没等到: {what}')
        p = unittest.mock.patch.object(dts.t, 'wait', wait)
        p.start()
        self.addCleanup(p.stop)
        q = unittest.mock.patch.object(dts.t, 'say', lambda m: None)
        q.start()
        self.addCleanup(q.stop)

    def test_second_click_gets_in(self):
        lead = FakeLead(inside_after=2)
        dts.enter_room(lead)
        self.assertEqual(lead.clicks, 2)

    def test_gives_up_after_three(self):
        lead = FakeLead(inside_after=99)
        with self.assertRaises(dts.t.Stop):
            dts.enter_room(lead)
        self.assertEqual(lead.clicks, 3)


if __name__ == '__main__':
    unittest.main()
