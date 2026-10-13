"""Unit tests for the supervisor's decisions (factory/schedule.py), no game needed."""
import unittest

from factory.phase import (ACCEPT_QUEST, DELETE, DELETED, EAT_MEAT, FARMING, HANDIN, LEAVE_TEAM, LEVELING,
                           QUARANTINED, QUEUE_COAST, QUEUE_TRANSPORT, QUEUE_WELL, RETURN_HOME, UNKNOWN)
from factory.schedule import (COAST_WAIT, DOWNSTREAM, FARMING_SIDE, FINISHED, OTHER, PULL_COAST, PULL_FRESH,
                              UPSTREAM, WELL, Known, PullPolicy, close_reason, count_sides, decide_pull,
                              has_candidate, pick_delete, pick_rebuild, pick_roles, rebuild_names, side,
                              retry_quarantined, successor, team_ready)

P = PullPolicy(max_windows=20, coast_buffer=4, well_buffer=4, coast_backlog=8)


def names(accounts, slots):
    return [(f'{a}r{s}', a) for s in slots for a in accounts]


class SideTest(unittest.TestCase):
    def test_fixed_phases(self):
        self.assertEqual(side(EAT_MEAT), UPSTREAM)
        self.assertEqual(side(LEVELING), WELL)
        self.assertEqual(side(QUEUE_TRANSPORT), COAST_WAIT)
        self.assertEqual(side(ACCEPT_QUEST), COAST_WAIT)
        self.assertEqual(side(FARMING), FARMING_SIDE)
        self.assertEqual(side(DELETE), DOWNSTREAM)
        self.assertEqual(side(DELETED), FINISHED)
        self.assertEqual(side(QUARANTINED), FINISHED)

    def test_lost_alts_count_by_level(self):
        self.assertEqual(side(RETURN_HOME, 5), UPSTREAM)
        self.assertEqual(side(LEAVE_TEAM, 11), COAST_WAIT)
        self.assertEqual(side(UNKNOWN, None), OTHER)

    def test_count(self):
        c = count_sides([(EAT_MEAT, 2), (QUEUE_WELL, 2), (FARMING, 11), (UNKNOWN, None)])
        self.assertEqual(c, {UPSTREAM: 2, FARMING_SIDE: 1, OTHER: 1})


class PullTest(unittest.TestCase):
    def test_full(self):
        self.assertIsNone(decide_pull({}, 20, P, True, True).kind)

    def test_coast_first(self):
        self.assertEqual(decide_pull({}, 0, P, True, True).kind, PULL_COAST)
        self.assertEqual(decide_pull({COAST_WAIT: 3}, 10, P, True, True).kind, PULL_COAST)

    def test_fresh_when_coast_queue_full_or_no_coast_roles(self):
        self.assertEqual(decide_pull({COAST_WAIT: 4}, 10, P, True, True).kind, PULL_FRESH)
        self.assertEqual(decide_pull({}, 0, P, False, True).kind, PULL_FRESH)

    def test_backpressure_stops_the_well(self):
        self.assertIsNone(decide_pull({COAST_WAIT: 8}, 10, P, False, True).kind)
        self.assertEqual(decide_pull({COAST_WAIT: 7}, 10, P, False, True).kind, PULL_FRESH)

    def test_both_queues_full(self):
        d = decide_pull({COAST_WAIT: 4, UPSTREAM: 4}, 12, P, True, True)
        self.assertIsNone(d.kind)
        self.assertEqual(d.reason, '队列够人')

    def test_nothing_to_pull(self):
        self.assertIsNone(decide_pull({}, 0, P, False, False).kind)

    def test_well_team_in_training_does_not_count_as_waiting(self):
        self.assertEqual(decide_pull({COAST_WAIT: 4, WELL: 4}, 8, P, True, True).kind, PULL_FRESH)


class PickTest(unittest.TestCase):
    ORDER = names(['a', 'b', 'c', 'd'], (1, 2))

    def test_coast_takes_known_roles_most_advanced_first(self):
        known = {k.name: k for k in (Known('ar1', 'a', ACCEPT_QUEST, 11, since=1.0),
                                     Known('br1', 'b', HANDIN, 11, since=9.0),
                                     Known('cr1', 'c', ACCEPT_QUEST, 11, since=0.5),
                                     Known('dr1', 'd', EAT_MEAT, 2))}
        self.assertEqual(pick_roles(PULL_COAST, known, self.ORDER, set(), set(), 9), ['br1', 'cr1', 'ar1'])

    def test_fresh_resumes_known_then_new_in_order(self):
        known = {k.name: k for k in (Known('cr1', 'c', EAT_MEAT, 2), Known('ar1', 'a', ACCEPT_QUEST, 11))}
        # ar1 is coast-side, so not a fresh candidate; account a is still free, its unseen ar2 comes in order
        self.assertEqual(pick_roles(PULL_FRESH, known, self.ORDER, set(), set(), 9), ['cr1', 'br1', 'dr1', 'ar2'])

    def test_one_per_account_and_open_accounts(self):
        self.assertEqual(pick_roles(PULL_FRESH, {}, self.ORDER, {'a', 'c'}, set(), 9), ['br1', 'dr1'])
        self.assertEqual(pick_roles(PULL_FRESH, {}, self.ORDER, set(), set(), 2), ['ar1', 'br1'])

    def test_skips_quarantined_deleted_and_skip_set(self):
        known = {k.name: k for k in (Known('ar1', 'a', ACCEPT_QUEST, 11, quarantined=True),
                                     Known('br1', 'b', DELETED, 11, deleted=True),
                                     Known('cr1', 'c', QUEUE_COAST, 11))}
        self.assertEqual(pick_roles(PULL_COAST, known, self.ORDER, set(), set(), 9), ['cr1'])
        self.assertEqual(pick_roles(PULL_COAST, known, self.ORDER, set(), {'cr1'}, 9), [])
        # deleted / quarantined roles are known, so never offered again as "new"
        self.assertEqual(pick_roles(PULL_FRESH, known, self.ORDER, set(), set(), 9), ['dr1', 'ar2', 'br2', 'cr2'])

    def test_lost_roles_by_level(self):
        known = {k.name: k for k in (Known('ar1', 'a', RETURN_HOME, 11), Known('br1', 'b', RETURN_HOME, 4))}
        self.assertEqual(pick_roles(PULL_COAST, known, self.ORDER, set(), set(), 9), ['ar1'])
        self.assertEqual(pick_roles(PULL_FRESH, known, self.ORDER, set(), set(), 1), ['br1'])

    def test_has_candidate(self):
        self.assertFalse(has_candidate(PULL_COAST, {}, self.ORDER, set(), set()))
        self.assertTrue(has_candidate(PULL_FRESH, {}, self.ORDER, set(), set()))
        self.assertFalse(has_candidate(PULL_FRESH, {}, self.ORDER, {'a', 'b', 'c', 'd'}, set()))


class TeamReadyTest(unittest.TestCase):
    def test_ready(self):
        self.assertFalse(team_ready(0, 4, 999, 60))
        self.assertTrue(team_ready(4, 4, 0, 60))
        self.assertFalse(team_ready(2, 4, 59, 60))
        self.assertTrue(team_ready(2, 4, 60, 60))


class PickDeleteTest(unittest.TestCase):
    ROWS = [('ar1', 'a'), ('br1', 'b'), ('cr1', 'c')]

    def test_oldest_free_account(self):
        self.assertEqual(pick_delete(self.ROWS, set(), set(), 0, 20), 'ar1')

    def test_account_with_open_window_or_login_is_not_touched(self):
        self.assertEqual(pick_delete(self.ROWS, {'a'}, set(), 0, 20), 'br1')
        self.assertIsNone(pick_delete(self.ROWS, {'a', 'b', 'c'}, set(), 0, 20))

    def test_skip_and_window_cap(self):
        self.assertEqual(pick_delete(self.ROWS, set(), {'ar1', 'br1'}, 0, 20), 'cr1')
        self.assertIsNone(pick_delete(self.ROWS, set(), set(), 20, 20))
        self.assertIsNone(pick_delete([], set(), set(), 0, 20))


class RebuildTest(unittest.TestCase):
    def test_successor(self):
        self.assertEqual(successor('mw01r1'), 'mw01r5')
        self.assertEqual(successor('mw01r5'), 'mw01r9')
        self.assertEqual(successor('mw100r9'), 'mw100r13')
        with self.assertRaises(ValueError):
            successor('伏地魔1')

    def test_rebuild_names(self):
        self.assertEqual(rebuild_names(['ar1', 'ar2'], set(), 4), ['ar5', 'ar6'])
        self.assertEqual(rebuild_names(['ar1', 'ar2'], set(), 1), ['ar5'])           # only one slot free yet
        self.assertEqual(rebuild_names(['ar1', 'ar2'], {'ar5'}, 4), ['ar6'])         # ar1 rebuilt already
        self.assertEqual(rebuild_names(['ar1'], set(), 0), [])

    def test_pick_rebuild(self):
        H = 3 * 3600
        rows = [('ar1', 'a', 0.0), ('br1', 'b', 100.0), ('cr1', 'c', None)]
        self.assertEqual(pick_rebuild(rows, set(), set(), set(), H, H, 0, 21), 'a')
        self.assertIsNone(pick_rebuild(rows, set(), set(), set(), H - 1, H, 0, 21))   # not released yet
        self.assertEqual(pick_rebuild(rows, {'ar5'}, set(), set(), H + 100, H, 0, 21), 'b')   # a rebuilt
        self.assertEqual(pick_rebuild(rows, set(), {'a'}, set(), H + 100, H, 0, 21), 'b')     # a online
        self.assertEqual(pick_rebuild(rows, set(), set(), {'a'}, H + 100, H, 0, 21), 'b')     # a tried recently
        self.assertIsNone(pick_rebuild(rows, set(), set(), set(), H + 100, H, 21, 21))        # no window


class RetryQuarantinedTest(unittest.TestCase):
    def test_once_after_the_wait(self):
        H = 7200
        rows = [(1, 0.0, 0), (2, 0.0, 1), (3, 5000.0, 0), (4, None, 0)]
        self.assertEqual(retry_quarantined(rows, H, H), [1])        # 2: released before; 3: too recent
        self.assertEqual(retry_quarantined(rows, 5000.0 + H, H), [1, 3])
        self.assertEqual(retry_quarantined(rows, 1e9, 0), [])       # 0 = off


class CloseTest(unittest.TestCase):
    def test_close(self):
        self.assertIsNotNone(close_reason(DELETED, False))
        self.assertIsNotNone(close_reason(QUEUE_COAST, True))
        self.assertIsNotNone(close_reason(QUARANTINED, False))
        self.assertIsNone(close_reason(DELETE, False))
        self.assertIsNone(close_reason(FARMING, False))


if __name__ == '__main__':
    unittest.main()
