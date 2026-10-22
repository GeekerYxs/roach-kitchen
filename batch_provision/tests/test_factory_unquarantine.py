"""Release of alts quarantined by a program fault (factory/unquarantine.py)."""
import time
import unittest

from factory import db
from factory.unquarantine import EVENT, SHOE_FAULT, select


class SelectTest(unittest.TestCase):
    def test_only_the_fault_text(self):
        rows = [{'char_id': 1, 'name': 'mw149r17', 'last_error': f'3s 内{SHOE_FAULT}'},
                {'char_id': 2, 'name': 'mw150r17', 'last_error': '邀请没收到'},
                {'char_id': 3, 'name': 'mw151r17', 'last_error': None}]
        self.assertEqual([r['char_id'] for r in select(rows, SHOE_FAULT)], [1])
        self.assertEqual(select(rows, ''), [])


class ReleaseKeepsTheSecondChanceTest(unittest.TestCase):
    def test_release_fix_is_not_counted_as_release(self):
        conn = db.connect(':memory:')
        now = time.time()
        db.register_alt(conn, 7, 'mw149', 1, 'mw149r17', now)
        for _ in range(db.MAX_RETRIES):
            db.record_failure(conn, 7, f'3s 内{SHOE_FAULT}', now)
        self.assertEqual(db.alt(conn, 7)['quarantined'], 1)
        db.release_quarantine(conn, 7, now, event=EVENT)
        row = db.alt(conn, 7)
        self.assertEqual((row['quarantined'], row['phase'], row['failures']), (0, 'unknown', 0))
        kinds = [r['kind'] for r in conn.execute('SELECT kind FROM events WHERE char_id=7')]
        self.assertIn(EVENT, kinds)
        self.assertNotIn('release', kinds)      # schedule.retry_quarantined counts kind='release' only


if __name__ == '__main__':
    unittest.main()
