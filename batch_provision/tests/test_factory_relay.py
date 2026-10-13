"""Unit tests for the well + transport relay (factory/relay.py), no game needed."""
import unittest

from factory.phase import AltObs
from factory.relay import Job, jobs_in_order, next_jobs, outcome, progress_key
from provisioner.config import Account


def accounts(*names):
    return [Account(n, 'x') for n in names]


def keys(jobs):
    return [j.key for j in jobs]


def obs(map_id=1, level=2):
    return AltObs(char_id=1, map_id=map_id, level=level, gold=0, team_leader=0, quest='none')


class JobsTest(unittest.TestCase):
    def test_slot_major(self):
        self.assertEqual(keys(jobs_in_order(accounts('a', 'b'), (1, 2))), ['a#1', 'b#1', 'a#2', 'b#2'])

    def test_one_per_account_skips_open_and_finished(self):
        jobs = jobs_in_order(accounts('a', 'b', 'c'), (1, 2))
        self.assertEqual(keys(next_jobs(jobs, set(), set(), 4)), ['a#1', 'b#1', 'c#1'])   # a#2: account a taken
        self.assertEqual(keys(next_jobs(jobs, {'a#1'}, {'b'}, 4)), ['c#1', 'a#2'])
        self.assertEqual(keys(next_jobs(jobs, set(), set(), 2)), ['a#1', 'b#1'])
        self.assertEqual(next_jobs(jobs, {j.key for j in jobs}, set(), 4), [])

    def test_wrap_keeps_accounts_distinct(self):
        jobs = jobs_in_order(accounts('a', 'b'), (1, 2))
        self.assertEqual(keys(next_jobs(jobs, {'a#1'}, set(), 4)), ['b#1', 'a#2'])

    def test_key(self):
        self.assertEqual(Job(Account('mw09', 'x'), 3).key, 'mw09#3')


class OutcomeTest(unittest.TestCase):
    def test_outcome(self):
        self.assertEqual(outcome(obs(81, 11), False, 0, 3), 'done')
        self.assertEqual(outcome(obs(81, 11), True, 5, 3), 'done')         # landed beats everything
        self.assertEqual(outcome(obs(81, 10), False, 0, 3), 'keep')
        self.assertEqual(outcome(obs(1, 11), True, 0, 3), 'failed')
        self.assertEqual(outcome(obs(1, 11), False, 3, 3), 'failed')
        self.assertEqual(outcome(obs(1, 11), False, 2, 3), 'keep')
        self.assertEqual(outcome(None, False, 0, 3), 'keep')

    def test_progress_key(self):
        self.assertIsNone(progress_key(None))
        self.assertNotEqual(progress_key(obs(1, 5)), progress_key(obs(1, 6)))
        self.assertNotEqual(progress_key(obs(1, 11)), progress_key(obs(81, 11)))


if __name__ == '__main__':
    unittest.main()
