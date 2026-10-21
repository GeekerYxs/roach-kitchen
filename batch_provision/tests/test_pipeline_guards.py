"""Pipeline guards: never log in an account that is online in someone else's window; slot config."""
import logging
import unittest
from unittest import mock

from provisioner import config, pipeline
from provisioner.pipeline import OwnWindows, online_elsewhere

LOG = logging.getLogger('test')
LOG.addHandler(logging.NullHandler())
TITLE = '什么什么大冒险2(①逍遥村敬老院)-{}_Sep 24 2026《什么什么大冒险》'


class OnlineElsewhere(unittest.TestCase):
    def check(self, titles, names=('mw01r1', 'mw01r2'), own_pids=()):
        own = OwnWindows(8, LOG)
        for pid in own_pids:
            own._open[pid] = None
        with mock.patch.object(pipeline, 'known_role_names', return_value=set(names)), \
                mock.patch.object(pipeline, 'game_window_titles', return_value=titles):
            return online_elsewhere('mw01', own)

    def test_users_window_blocks_login(self):
        self.assertIn('mw01r2', self.check({500: [TITLE.format('mw01r2')]}))

    def test_other_account_does_not_block(self):
        self.assertIsNone(self.check({500: [TITLE.format('mw02r1')]}))

    def test_prefix_name_is_not_a_match(self):
        # mw01r1 must not match a window of mw01r10
        self.assertIsNone(self.check({500: [TITLE.format('mw01r10')]}, names=('mw01r1',)))

    def test_own_window_is_ignored(self):
        self.assertIsNone(self.check({600: [TITLE.format('mw01r1')]}, own_pids=(600,)))

    def test_unknown_names_cannot_block(self):
        self.assertIsNone(self.check({500: [TITLE.format('mw01r1')]}, names=()))


class Slots(unittest.TestCase):
    def test_single_and_list(self):
        self.assertEqual(config._slots(1), (1,))
        self.assertEqual(config._slots([2, 3, 4, 3]), (2, 3, 4))

    def test_out_of_range(self):
        with self.assertRaises(ValueError):
            config._slots([0, 5])


if __name__ == '__main__':
    unittest.main()


# box08 as seen live 2026-10-21: the server listed 仓1 last once it was a level behind the others
BOX08 = [(216310, 11, 'box08仓2'), (216312, 11, 'box08仓3'), (216315, 11, 'box08仓4'), (216309, 10, 'box08仓1')]


class RoleSlot(unittest.TestCase):
    def test_slot_of_finds_by_name(self):
        self.assertEqual(pipeline.slot_of(BOX08, 'box08仓4'), 3)
        self.assertEqual(pipeline.slot_of(BOX08, 'box08仓1'), 4)
        self.assertIsNone(pipeline.slot_of(BOX08, 'box08仓5'))

    def store_run(self, cls, slot, expected):
        run = object.__new__(cls)
        run.slot, run.expected, run.log = slot, expected, LOG
        return run

    def test_store_runs_enter_by_name(self):
        from factory.store import StoreRun
        from factory.storeship import ShipRun
        for cls in (StoreRun, ShipRun):
            self.assertEqual(self.store_run(cls, 4, 'box08仓4').role_slot(BOX08), 3)
            self.assertEqual(self.store_run(cls, 1, 'box08仓1').role_slot(BOX08), 4)
            with self.assertRaisesRegex(RuntimeError, '没有 box08仓4'):
                self.store_run(cls, 4, 'box08仓4').role_slot(BOX08[:2])

    def test_plain_run_keeps_the_slot_number(self):
        run = object.__new__(pipeline.AccountRun)
        run.slot = 2
        self.assertEqual(run.role_slot(BOX08), 2)
        run.slot = 5
        with self.assertRaisesRegex(RuntimeError, '槽5 没有角色'):
            run.role_slot(BOX08)
