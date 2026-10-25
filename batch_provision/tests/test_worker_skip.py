"""Unit tests for provisioner.worker.may_skip (no game needed)."""
import unittest

from provisioner.worker import may_skip

ROLES = ['mw101r1', 'mw101r2', 'mw101r3', 'mw101r4']


class MaySkip(unittest.TestCase):
    def test_all_created_and_seen_skips(self):
        self.assertTrue(may_skip(ROLES, lambda r: True, list(ROLES)))
        self.assertTrue(may_skip(ROLES, lambda r: True, None))       # never seen: the records are all we have

    def test_records_say_created_but_the_roster_was_empty(self):
        # 2026-10-26: mw101..mw130 had created records from 10-12, the server had deleted the roles
        self.assertFalse(may_skip(ROLES, lambda r: True, []))
        self.assertFalse(may_skip(ROLES, lambda r: True, ROLES[:3]))

    def test_not_all_created_logs_in(self):
        self.assertFalse(may_skip(ROLES, lambda r: r != 'mw101r4', list(ROLES)))


if __name__ == '__main__':
    unittest.main()
