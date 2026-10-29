"""Unit tests for research/qiyi/go.py decide() (no game needed), on the states 飞天把你射成蜂窝 went through live on
2026-10-28: 外城 return point -> 交叉口 -> 飞行平台特警 -> 飞行平台 -> 阿尔法机组机长 -> 永冻群山
-> 隐藏的传送石 -> 星灵神域."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'qiyi'))

import go  # noqa: E402
from provisioner.world import Dialog, WorldState, parse_options  # noqa: E402

GUARD_TEXT = ('#FFFFFF#这里是重要军事区域，非相关人员请速速离开。\n\n#ABB5FC#[URL opt=1]请求进入[/URL]\n'
              '#ABB5FC#[URL opt=2]离开[/URL]\n')
CAPTAIN_TEXT = ('#FFFFFF#我这里的航班通往永冻山脉，这条航线风险极高，请务必做好保暖措施。\n\n'
                '#ABB5FC#[URL opt=1]乘坐航班[/URL]\n#ABB5FC#[URL opt=2]离开[/URL]\n')
STONE_TEXT = ('#FFFFFF#（这些冰雕整个雪山到处都是，如果没有雪宝宝的情报，谁都猜不到它竟然另藏机关。）\n'
              '#ABB5FC#[URL opt=1]启动传送机关[/URL]\n#ABB5FC#[URL opt=2]离开[/URL]\n')


def dialog(text):
    return Dialog(text, parse_options(text))


def state(map_id, x, y, nav=False, dialog=None, battle=False, busy=False, verif=False):
    return WorldState(1, map_id, x, y, 0, 0, 0, busy, battle, nav, verif, dialog=dialog)


class Decide(unittest.TestCase):
    def test_live_route(self):
        steps = [
            (state(20, 3863, 2027), 'nav', (20, 663, 166)),
            (state(20, 3134, 1760, nav=True), 'wait', ()),
            (state(20, 663, 166), 'wait', ()),
            (state(25, 2982, 1563), 'nav', (25, 1912, 220)),
            (state(25, 1912, 220), 'click', (14673,)),
            (state(25, 1912, 220, dialog=dialog(GUARD_TEXT)), 'pick', (1,)),
            (state(3100, 4500, 2500), 'nav', (3100, 1144, 1364)),
            (state(3100, 1144, 1364), 'click', (14641,)),
            (state(3100, 1144, 1364, dialog=dialog(CAPTAIN_TEXT)), 'pick', (1,)),
            (state(3110, 456, 3532), 'nav', (3110, 1112, 620)),
            (state(3110, 1525, 3717, nav=True, battle=True), 'wait', ()),
            (state(3110, 1112, 620), 'click', (14616,)),
            (state(3110, 1112, 620, dialog=dialog(STONE_TEXT)), 'pick', (1,)),
            (state(3120, 1736, 1956), 'done', ()),
        ]
        for w, kind, args in steps:
            a = go.decide(w)
            self.assertEqual((a.kind, a.args), (kind, args), w)

    def test_earlier_goal_stops_there(self):
        self.assertEqual(go.decide(state(3100, 4500, 2500), goal=3100).kind, 'done')
        self.assertEqual(go.decide(state(3110, 664, 4172), goal=3110).kind, 'done')

    def test_waits_on_battle_quiz_busy_and_unknown(self):
        self.assertEqual(go.decide(None).kind, 'wait')
        for w in (state(20, 1, 1, battle=True), state(25, 1912, 220, verif=True), state(25, 1912, 220, busy=True)):
            self.assertEqual(go.decide(w).kind, 'wait')

    def test_off_route_map_and_wrong_dialog_fail(self):
        self.assertEqual(go.decide(state(24, 3000, 3500)).kind, 'fail')
        self.assertEqual(go.decide(state(25, 1912, 220, dialog=dialog(CAPTAIN_TEXT))).kind, 'fail')

    def test_stale_walk_is_cancelled(self):
        # live 2026-10-28 (舔尊 ...): re-sent walk on the exit -> crossed to 25 with nav stuck active at (2982,1563)
        stuck = WorldState(1, 25, 2982, 1563, 663, 166, 0, False, False, True, False, still_for=6)
        self.assertEqual(go.decide(stuck).kind, 'cancel')
        self.assertEqual(go.decide(state(25, 2982, 1563, nav=True)).kind, 'wait')

    def test_far_from_npc_walks_again(self):
        self.assertEqual(go.decide(state(25, 1912, 400)).kind, 'nav')


if __name__ == '__main__':
    unittest.main()
