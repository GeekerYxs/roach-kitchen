"""Unit tests for factory.db on a temporary SQLite file (no game needed)."""
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from factory import db
from factory import phase as P
from factory.phase import AltObs, derive_phase

FRESH = AltObs(char_id=1, map_id=P.VILLAGE_MAP, level=1, gold=0, team_leader=0, quest=P.QUEST_NONE)


class FactoryDb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'factory.db'
        self.conn = db.connect(self.path)
        for cid in (1, 2, 3, 4, 5):
            db.register_alt(self.conn, cid, f'mw0{cid}', 1, f'r{cid}', now=0.0)
            db.set_ledger(self.conn, cid, 0.0, meat_at=1.0, shoe_recorded_at=2.0)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def observe(self, obs, now):
        plan = derive_phase(obs, db.ledger(self.conn, obs.char_id), db.station_roles(self.conn))
        return db.save_observation(self.conn, obs, plan, now)

    def queue_all(self, now=5.0):
        for cid in (1, 2, 3, 4, 5):
            self.observe(replace(FRESH, char_id=cid), now + cid)   # cid 1 queued first

    def test_register_is_idempotent(self):
        db.register_alt(self.conn, 1, 'other', 2, 'x', now=9.0)
        self.assertEqual(db.alt(self.conn, 1)['account'], 'mw01')

    def test_observation_round_trip_and_phase_change(self):
        self.assertTrue(self.observe(FRESH, 5.0))
        self.assertFalse(self.observe(FRESH, 6.0))            # same phase again: no change
        row = db.alt(self.conn, 1)
        self.assertEqual((row['phase'], row['phase_since'], row['needs_gold']), (P.QUEUE_WELL, 5.0, 1))
        self.assertEqual(db.last_observation(self.conn, 1), FRESH)

    def test_unknown_ledger_field_rejected(self):
        with self.assertRaises(ValueError):
            db.set_ledger(self.conn, 1, 0.0, level=3)

    def test_queue_is_fifo_and_claim_is_exclusive(self):
        self.queue_all()
        ids = [r['char_id'] for r in db.waiting(self.conn, P.QUEUE_WELL, now=20.0, limit=4)]
        self.assertEqual(ids, [1, 2, 3, 4])
        self.assertEqual(db.claim(self.conn, 'well1', ids, 60, now=20.0), [1, 2, 3, 4])
        # another station cannot take them while the lease is alive
        self.assertEqual(db.claim(self.conn, 'well2', [1, 5], 60, now=21.0), [5])
        self.assertEqual(db.waiting(self.conn, P.QUEUE_WELL, now=21.0), [])
        # the holder itself may claim again (restart): that renews its lease
        self.assertEqual(db.claim(self.conn, 'well1', [1, 2], 60, now=22.0), [1, 2])
        self.assertEqual(db.alt(self.conn, 1)['lease_until'], 82.0)

    def test_expired_lease_frees_the_alts(self):
        self.queue_all()
        db.claim(self.conn, 'well1', [1, 2], 60, now=20.0)
        self.assertEqual(db.renew(self.conn, 'well1', [1, 2], 60, now=70.0), 2)     # alive: extended to 130
        self.assertEqual(len(db.held(self.conn, 'well1', now=129.0)), 2)
        # station died: no renew after 130
        self.assertEqual(db.claim(self.conn, 'well2', [1, 2], 60, now=131.0), [1, 2])
        self.assertEqual(db.renew(self.conn, 'well1', [1, 2], 60, now=132.0), 0)

    def test_renew_only_the_current_batch(self):
        """2026-10-14 runner: members of a failed batch stayed held, the station's next batches renewed them every
        10 s and 10 of 30 windows idled for over an hour. Only the batch's own members are renewed now."""
        self.queue_all()
        db.claim(self.conn, 'well1', [1, 2], 60, now=20.0)      # batch 1 fails, 1 and 2 are not released
        db.claim(self.conn, 'well1', [3], 60, now=30.0)         # batch 2
        self.assertEqual(db.renew(self.conn, 'well1', [3], 60, now=70.0), 1)
        self.assertEqual([r['char_id'] for r in db.waiting(self.conn, P.QUEUE_WELL, now=81.0)][:2], [1, 2])

    def test_release_station(self):
        self.queue_all()
        db.claim(self.conn, 'well1', [1, 2], 60, now=20.0)
        db.claim(self.conn, 'coast1', [3], 60, now=20.0)
        self.assertEqual(sorted(db.release_station(self.conn, 'well1', 21.0, 'test')), [1, 2])
        self.assertEqual(db.held(self.conn, 'well1', now=22.0), [])
        self.assertEqual([r['char_id'] for r in db.held(self.conn, 'coast1', now=22.0)], [3])
        self.assertEqual(db.release_station(self.conn, 'well1', 23.0, 'test'), [])

    def test_release(self):
        self.queue_all()
        db.claim(self.conn, 'well1', [1, 2], 60, now=20.0)
        db.release(self.conn, 'well1', [1], now=21.0)
        self.assertEqual([r['char_id'] for r in db.held(self.conn, 'well1', now=22.0)], [2])

    def test_gold_filter(self):
        self.queue_all()
        self.observe(replace(FRESH, char_id=3, gold=500), 30.0)
        self.assertEqual([r['char_id'] for r in db.waiting(self.conn, P.QUEUE_WELL, 31.0, need_gold=False)], [3])

    def test_three_failures_quarantine_and_drop_lease(self):
        self.queue_all()
        db.claim(self.conn, 'well1', [1], 60, now=20.0)
        self.assertFalse(db.record_failure(self.conn, 1, 'x', now=21.0))
        self.assertFalse(db.record_failure(self.conn, 1, 'x', now=22.0))
        self.assertTrue(db.record_failure(self.conn, 1, 'boom', now=23.0))
        row = db.alt(self.conn, 1)
        self.assertEqual((row['phase'], row['station_id'], row['last_error']), (P.QUARANTINED, None, 'boom'))
        self.assertNotIn(1, [r['char_id'] for r in db.waiting(self.conn, P.QUEUE_WELL, 24.0)])
        self.assertEqual(db.claim(self.conn, 'well2', [1], 60, now=24.0), [])
        # it stays quarantined on later observations
        self.observe(FRESH, 25.0)
        self.assertEqual(db.alt(self.conn, 1)['phase'], P.QUARANTINED)

    def test_phase_change_resets_failures(self):
        self.queue_all()
        db.record_failure(self.conn, 1, 'x', now=21.0)
        db.record_failure(self.conn, 1, 'x', now=22.0)
        self.observe(replace(FRESH, team_leader=999), 23.0)        # new phase (leave_team)
        self.assertEqual(db.alt(self.conn, 1)['failures'], 0)

    def test_release_quarantine(self):
        for t in (21.0, 22.0, 23.0):
            db.record_failure(self.conn, 1, 'x', now=t)
        db.release_quarantine(self.conn, 1, now=30.0)
        self.observe(FRESH, 31.0)
        self.assertEqual(db.alt(self.conn, 1)['phase'], P.QUEUE_WELL)

    def test_station_roles_feed_derive_phase(self):
        db.heartbeat(self.conn, 'well1', P.WELL, 900, 'patrol', now=1.0)
        self.observe(replace(FRESH, team_leader=900, map_id=P.WELL_MAP), 5.0)
        self.assertEqual(db.alt(self.conn, 1)['phase'], P.LEVELING)

    def test_second_process_sees_writes(self):
        self.queue_all()
        other = db.connect(self.path)
        try:
            self.assertEqual(db.claim(other, 'well1', [1], 60, now=20.0), [1])
            self.assertEqual(db.alt(self.conn, 1)['station_id'], 'well1')
        finally:
            other.close()


if __name__ == '__main__':
    unittest.main()
