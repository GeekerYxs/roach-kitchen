"""settle_roster: do not trust a role list read before the server has sent it."""
import logging
import unittest

from provisioner.login import settle_roster

LOG = logging.getLogger('test')
LOG.addHandler(logging.NullHandler())
FULL = [(1, 1, 'mw01r1'), (2, 1, 'mw01r2'), (3, 1, 'mw01r3'), (4, 1, 'mw01r4')]


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def sleep(self, s):
        self.now += s

    def __call__(self):
        return self.now


def run(sequence, **kw):
    """sequence: what each successive read returns (last value repeats)."""
    clock, reads = FakeClock(), list(sequence)

    def read():
        return reads.pop(0) if len(reads) > 1 else reads[0]

    return settle_roster(read, LOG, sleep=clock.sleep, clock=clock, **kw), clock.now


class SettleRoster(unittest.TestCase):
    def test_late_roster_is_waited_for(self):
        # mw146/mw147 case: empty for a while, then the real 4 roles arrive
        roster, _ = run([[], [], [], FULL])
        self.assertEqual(roster, FULL)

    def test_really_empty_account_is_accepted_after_wait(self):
        roster, waited = run([[]], empty_wait=8.0, gap=0.5)
        self.assertEqual(roster, [])
        self.assertGreaterEqual(waited, 8.0)

    def test_full_list_needs_two_equal_reads(self):
        roster, waited = run([FULL], gap=0.5)
        self.assertEqual(roster, FULL)
        self.assertLess(waited, 1.0)   # no long wait for the normal case

    def test_growing_list_is_not_cut_short(self):
        roster, _ = run([FULL[:1], FULL[:3], FULL])
        self.assertEqual(roster, FULL)


if __name__ == '__main__':
    unittest.main()
