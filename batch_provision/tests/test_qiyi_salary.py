"""Unit tests for research/qiyi/salary.py (no game needed), on the dialogs 飞天把你射成蜂窝 saw live on 2026-10-28:
算得快 menu -> 领取今天的薪水 -> +40 金龙币, 达哥罗斯 menu -> 立刻领取 -> +20; the same day again -> 已经领过 / 已经拿过."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'qiyi'))

import salary  # noqa: E402
from provisioner.world import Dialog, WorldState, parse_options  # noqa: E402

PAY, ALLOWANCE = salary.CLAIMS

PAY_MENU = ('#FFFFFF#这鬼天气，吐口唾沫在地上都能砸个坑，我的鼻子都被冻红了。\n#ABB5FC#[URL opt=1]领取开拓团薪金[/URL]\n'
            '#ABB5FC#[URL opt=2]捐献物资[/URL]\n#ABB5FC#[URL opt=3]声望商店[/URL]\n#ABB5FC#[URL opt=4]离开[/URL]\n')
PAY_PAGE = ('#FFFFFF#为了感谢你为开拓团做出的卓越贡献，每天都可以领取开拓团薪金一份。\n\n'
            '#ABB5FC#[URL opt=1]领取今天的薪水[/URL]\n')
PAY_ALREADY = '#FFFFFF#你今天已经领过薪水了，我这里记录得清清楚楚，别想在我这里占便宜。\n\n#ABB5FC#[URL opt=1]好的[/URL]\n'
ALLOW_MENU = ('#FFFFFF#这片永冻群山长久以来守护的秘密，在你的帮助下得以展现。\n'
              '#ABB5FC#[URL opt=1]矿脉探索：永洞山脉的遗产 #FFCC00#[全部完成][/URL]\n'
              '#ABB5FC#[URL opt=2]每日津贴：勘探先锋防寒补助[/URL]\n#ABB5FC#[URL opt=3]离开[/URL]\n')
ALLOW_PAGE = ('#FFFFFF##ffffff#这项津贴由#00ff00#龙之都开拓军#ffffff#赞助，每天定时发放。\n\n#ffd965#声望阶段:#abfc03# 亲如一家\n'
              '#ffd965#津贴奖励：#abfc03#龙之都金龙币x20\n\n#ABB5FC#[URL opt=1]立刻领取[/URL]\n'
              '#ABB5FC#[URL opt=2]查看津贴奖励[/URL]\n#ABB5FC#[URL opt=3]返回[/URL]\n')
ALLOW_ALREADY = ('#FFFFFF#你已经拿过今天的津贴，这可是每日一发，不要心急。\n\n#ABB5FC#[URL opt=1]查看津贴奖励[/URL]\n'
                 '#ABB5FC#[URL opt=2]返回[/URL]\n')


def state(map_id, x, y, text=None, nav=False):
    dialog = Dialog(text, parse_options(text)) if text else None
    return WorldState(1, map_id, x, y, 0, 0, 0, False, False, nav, False, dialog=dialog)


def kind_args(a):
    return a.kind, a.args


class Decide(unittest.TestCase):
    def test_pay_first_claim(self):
        d = salary.decide
        self.assertEqual(kind_args(d(state(3110, 456, 3532), PAY, 0, False)), ('nav', (3110, 664, 4172)))
        self.assertEqual(kind_args(d(state(3110, 664, 4172), PAY, 0, False)), ('click', (14603,)))
        self.assertEqual(kind_args(d(state(3110, 664, 4172, PAY_MENU), PAY, 0, False)), ('pick', (1,)))
        self.assertEqual(kind_args(d(state(3110, 664, 4172, PAY_PAGE), PAY, 0, False)), ('pick', (1,)))
        self.assertEqual(d(state(3110, 664, 4172), PAY, 40, False).kind, 'done')

    def test_allowance_first_claim(self):
        d = salary.decide
        self.assertEqual(kind_args(d(state(3110, 664, 4172), ALLOWANCE, 0, False)), ('nav', (3110, 220, 4517)))
        self.assertEqual(kind_args(d(state(3110, 220, 4517), ALLOWANCE, 0, False)), ('click', (14604,)))
        self.assertEqual(kind_args(d(state(3110, 220, 4517, ALLOW_MENU), ALLOWANCE, 0, False)), ('pick', (2,)))
        self.assertEqual(kind_args(d(state(3110, 220, 4517, ALLOW_PAGE), ALLOWANCE, 0, False)), ('pick', (1,)))
        self.assertEqual(d(state(3110, 220, 4517), ALLOWANCE, 20, False).kind, 'done')

    def test_already_taken_closes_dialog_then_done(self):
        for claim, text, at in ((PAY, PAY_ALREADY, (664, 4172)), (ALLOWANCE, ALLOW_ALREADY, (220, 4517))):
            self.assertEqual(kind_args(salary.decide(state(3110, *at, text), claim, 0, True)), ('pick', (0,)))
            self.assertEqual(salary.decide(state(3110, *at), claim, 0, True).kind, 'done')

    def test_never_picks_pay_twice(self):
        self.assertEqual(kind_args(salary.decide(state(3110, 664, 4172, PAY_MENU), PAY, 40, False)), ('pick', (0,)))
        self.assertEqual(kind_args(salary.decide(state(3110, 220, 4517, ALLOW_PAGE), ALLOWANCE, 20, False)),
                         ('pick', (0,)))

    def test_route_before_the_map(self):
        self.assertEqual(kind_args(salary.decide(state(20, 3863, 2027), PAY, 0, False)), ('nav', (20, 663, 166)))
        self.assertEqual(kind_args(salary.decide(state(3100, 4500, 2500), PAY, 0, False)),
                         ('nav', (3100, 1144, 1364)))


class Step(unittest.TestCase):
    def test_claims_run_in_order(self):
        # pay: 291 -> 331, then allowance: 331 -> 351
        with mock.patch.object(salary, 'coins', side_effect=[291, 291, 331, 331, 331, 351]):
            step = salary.make_step()
            self.assertEqual(kind_args(step(state(3110, 664, 4172), None)), ('click', (14603,)))
            self.assertEqual(step(state(3110, 664, 4172, PAY_PAGE), None).kind, 'pick')
            self.assertEqual(kind_args(step(state(3110, 664, 4172), None)), ('nav', (3110, 220, 4517)))
            self.assertEqual(kind_args(step(state(3110, 220, 4517), None)), ('click', (14604,)))
            a = step(state(3110, 220, 4517), None)
            self.assertEqual(a.kind, 'done')
            self.assertIn('+40', a.why)
            self.assertIn('+20', a.why)

    def test_both_already_taken(self):
        with mock.patch.object(salary, 'coins', return_value=351):
            step = salary.make_step()
            self.assertEqual(step(state(3110, 664, 4172, PAY_ALREADY), None).kind, 'pick')
            self.assertEqual(kind_args(step(state(3110, 664, 4172), None)), ('nav', (3110, 220, 4517)))
            self.assertEqual(step(state(3110, 220, 4517, ALLOW_ALREADY), None).kind, 'pick')
            self.assertEqual(step(state(3110, 220, 4517), None).kind, 'done')


if __name__ == '__main__':
    unittest.main()
