"""Unit tests for stage 10 (delete): the gate, roster lookup, the 0x0003 body and the DB records (no game needed)."""
import struct
import unittest

from factory import db
from factory.delete import ACTION, entry_diff, find_entry, gate, reply_outcome
from factory.phase import DELETE, DELETED, QUEST_ACTIVE, QUEST_DONE, AltObs
from provisioner.protocol import (CREATE_BODY_SIZE, DELETE_BODY_SIZE, DELETE_ID_OFFSET, SessionMismatch,
                                  build_create, build_delete, parse_delete_reply)

CTX = 0x1000


class FakeMemory:
    """A session context: account 'mw01' (SSO std::string at +0x20), token of 32 bytes on the heap at +0x74."""

    def __init__(self, account=b'mw01'):
        self.mem = bytearray(0x3000)
        self.mem[CTX + 0x1C] = 11
        self.mem[CTX + 0x20:CTX + 0x20 + len(account)] = account
        self.mem[CTX + 0x20 + len(account) + 1:CTX + 0x20 + 16] = b'\xAA' * (15 - len(account))   # SSO garbage
        struct.pack_into('<II', self.mem, CTX + 0x30, len(account), 15)
        struct.pack_into('<I', self.mem, CTX + 0x74, 0x2000)                  # token pointer (cap >= 16)
        struct.pack_into('<II', self.mem, CTX + 0x84, 32, 47)
        self.mem[0x2000:0x2020] = bytes(range(1, 33))

    def u32(self, address):
        return struct.unpack_from('<I', self.mem, address)[0]

    def read(self, address, size):
        return bytes(self.mem[address:address + size])


def old_build_create(memory, context, account, role):
    """build_create as it was before the shared helper (2026-10-12), to prove the refactor kept the bytes."""
    raw_account = memory.read(context + 0x20, 128)
    token_length = min(memory.u32(context + 0x84), 128)
    token_field = memory.u32(context + 0x74)
    body = bytearray(CREATE_BODY_SIZE)
    body[0] = memory.read(context + 0x1C, 1)[0]
    body[4:132] = raw_account
    body[136:136 + token_length] = memory.read(token_field, token_length)
    struct.pack_into('<II', body, 265, 3, 0)
    body[273:275] = bytes([1, 0])
    body[275:275 + len(role)] = role.encode()
    return bytes(body)


class Bodies(unittest.TestCase):
    def test_delete_body_layout(self):
        mem = FakeMemory()
        body = build_delete(mem, CTX, 'mw01', 202851)
        self.assertEqual(len(body), DELETE_BODY_SIZE)
        self.assertEqual(body[0], 11)
        self.assertEqual(body[4:8], b'mw01')
        self.assertEqual(body[4:132], mem.read(CTX + 0x20, 128))     # 128 raw bytes, garbage included
        self.assertEqual(body[136:168], bytes(range(1, 33)))
        self.assertEqual(struct.unpack_from('<I', body, DELETE_ID_OFFSET)[0], 202851)
        self.assertEqual(body[269:], bytes(DELETE_BODY_SIZE - 269))   # the optional string stays empty
        # same non-zero regions as the 2026-10-09 captures (account, token, id) and nothing else
        self.assertFalse(any(body[132:136]) or any(body[168:265]))

    def test_delete_refuses_other_account_and_zero_id(self):
        with self.assertRaises(SessionMismatch):
            build_delete(FakeMemory(), CTX, 'mw02', 202851)
        with self.assertRaises(ValueError):
            build_delete(FakeMemory(), CTX, 'mw01', 0)

    def test_create_body_unchanged_by_refactor(self):
        mem = FakeMemory()
        self.assertEqual(build_create(mem, CTX, 'mw01', 'mw01r1'), old_build_create(mem, CTX, 'mw01', 'mw01r1'))

    def test_parse_reply_matches_capture(self):
        self.assertEqual(parse_delete_reply(bytes.fromhex('000014730f')), (0, 259200000))
        with self.assertRaises(ValueError):
            parse_delete_reply(b'\0\0')
        self.assertEqual(reply_outcome(0), 'deleted')
        self.assertEqual(reply_outcome(3), 'rejected')


DONE_OBS = AltObs(char_id=1, map_id=81, level=12, gold=2000, team_leader=0, quest=QUEST_DONE)
ROW = {'quarantined': 0, 'last_error': None, 'pending_action': None, 'phase': DELETE}


class Gate(unittest.TestCase):
    def test_finished_alt_may_be_deleted(self):
        self.assertIsNone(gate(ROW, DONE_OBS, True))

    def test_refusals(self):
        self.assertIn('隔离', gate({**ROW, 'quarantined': 1}, DONE_OBS, True))
        self.assertIn('不重发', gate({**ROW, 'pending_action': ACTION}, DONE_OBS, True))
        self.assertIn('queue_receiver', gate({**ROW, 'phase': 'queue_receiver'}, DONE_OBS, True))
        self.assertIn('观察', gate(ROW, None, True))
        self.assertIn('任务', gate(ROW, AltObs(1, 81, 12, 0, 0, QUEST_ACTIVE), True))
        self.assertIn('料理', gate(ROW, AltObs(1, 81, 12, 0, 0, QUEST_DONE, dishes=1), True))
        self.assertIn('收货', gate(ROW, DONE_OBS, False))


class Roster(unittest.TestCase):
    ROSTER = [(202851, 12, 'mw01r1'), (202852, 1, 'mw01r2')]

    def test_found_by_id(self):
        self.assertEqual(find_entry(self.ROSTER, 202852, 'mw01r2'), (1, None))

    def test_name_mismatch_is_a_problem(self):
        index, problem = find_entry(self.ROSTER, 202851, 'mw09r1')
        self.assertEqual(index, 0)
        self.assertIn('mw09r1', problem)

    def test_missing_means_gone(self):
        self.assertEqual(find_entry(self.ROSTER, 999, 'x'), (None, None))

    def test_entry_diff(self):
        self.assertEqual(entry_diff(b'\x00\x01\x02', b'\x00\x05\x02'), [(1, 1, 5)])


class Records(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(':memory:')
        db.register_alt(self.conn, 1, 'mw01', 1, 'mw01r1', 100.0)

    def test_received_needs_a_receive_event(self):
        self.assertFalse(db.received(self.conn, 1))
        db.log_event(self.conn, 101.0, 'receive', '料理 小号 1 -> 0', char_id=1)
        self.assertTrue(db.received(self.conn, 1))

    def test_mark_deleted_clears_pending_and_sets_phase(self):
        db.mark_pending(self.conn, 1, ACTION, 102.0)
        db.mark_deleted(self.conn, 1, 103.0, 259200000)
        row = db.alt(self.conn, 1)
        self.assertEqual((row['phase'], row['deleted_at'], row['release_ms'], row['pending_action']),
                         (DELETED, 103.0, 259200000, None))
        self.assertEqual(db.waiting(self.conn, DELETE, 104.0), [])


if __name__ == '__main__':
    unittest.main()
