"""Unit tests for battlelog (no game needed): real 八阵图 packets, tap framing with the codec, battle assembly, the
SQLite store and the file import."""
import json
import os
import sqlite3
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import battlelog_sample as sample                               # noqa: E402
from battlelog import __main__ as cli, decode, store            # noqa: E402

# Codec tables: table k maps v -> (v + k + 1) % 256, so a wrong table index changes every byte.
DECODE = [bytes((v + k + 1) % 256 for v in range(256)) for k in range(10)]
ENCODE = [bytes(sorted(range(256), key=lambda v: t[v])) for t in DECODE]


def frame(opcode, body):
    """Encoded wire frame as the server sends it (inverse of decode.tap_packets)."""
    inverted = ~len(body) & 0xFFFF
    index = ((opcode << 8) ^ inverted) % 10
    return struct.pack('<HH', inverted, opcode) + bytes(ENCODE[(index + i) % 10][v] for i, v in enumerate(body))


def recv(tick, data):
    return json.dumps({'kind': 'wire_recv', 'tick': tick, 'opcode': 0, 'caller_rva': 0, 'length': len(data),
                       'hex': data.hex()})


def request(tick, opcode, body):
    return json.dumps({'kind': 'request', 'tick': tick, 'opcode': opcode, 'caller_rva': 1, 'length': len(body),
                       'hex': body.hex()})


def result(char_id, exp, items=()):
    body = bytearray(decode.RESULT_ITEMS + decode.ITEM_SIZE * len(items) + 22)
    struct.pack_into('<Iq', body, 0, char_id, exp)
    struct.pack_into('<q', body, 20, exp // 2)
    struct.pack_into('<II', body, 28, 10, exp // 10)
    struct.pack_into('<10i', body, decode.RESULT_MONSTERS, 1197, 1203, *([-1] * 8))
    body[decode.RESULT_ITEM_COUNT] = len(items)
    for i, (item, qty, slot) in enumerate(items):
        at = decode.RESULT_ITEMS + decode.ITEM_SIZE * i
        struct.pack_into('<IHH', body, at, item, qty, 1)
        body[at + 8] = slot
    return bytes(body)


def lineup(own_id, players=(), units=((1197, 21), (1203, 22)), trailer=b''):
    body = bytearray(decode.LINEUP_HEAD)
    struct.pack_into('<I', body, 0, own_id)
    body[40], body[41], body[42], body[43] = 16, 11, len(players), len(units)
    for i, (char_id, name, level) in enumerate(players):
        p = bytearray(decode.PLAYER_SIZE)
        struct.pack_into('<qqxxxxxxxxI', p, 0, 900, 900, char_id)
        struct.pack_into('<I', p, 64, level)
        p[73] = 15 + i
        n = name.encode('gbk')
        p[74:74 + len(n)] = n
        body += p
    for i, (npc, level) in enumerate(units):
        u = bytearray(decode.UNIT_SIZE)
        struct.pack_into('<qq', u, 0, 600, 652)
        struct.pack_into('<II', u, 24, npc, level)
        u[37], u[38] = i, decode.UNIT_MONSTER
        body += u
    return bytes(body + trailer)


class RealPackets(unittest.TestCase):
    def test_map(self):
        self.assertEqual(decode.parse_map(sample.MAP), (700, 1000, 1735))

    def test_lineup(self):
        lu = decode.parse_lineup(sample.LINEUP)
        self.assertEqual((lu.own_id, lu.own_pos, lu.own_pet_pos), (222201, 19, 14))
        self.assertEqual([(p.name, p.level, p.pos) for p in lu.players],
                         [('亿万19', 19, 15), ('亿万17', 19, 16), ('伏地魔1', 70, 17), ('亿万18', 19, 18)])
        self.assertEqual([(m.npc_id, m.level, m.pos) for m in lu.monsters],
                         [(1198, 21, 0), (1197, 21, 1), (1197, 21, 2), (1197, 21, 3), (1198, 21, 4)])
        self.assertEqual([(u.level, u.pos) for u in lu.units if u.kind == decode.UNIT_PET],
                         [(19, 10), (19, 11), (70, 12), (19, 13)])

    def test_result(self):
        r = decode.parse_result(sample.RESULT)
        self.assertEqual((r.char_id, r.exp, r.pet_exp, r.pet_training, r.potential), (222201, 1926, 963, 10, 212))
        self.assertEqual(r.monster_ids, (1198, 1197, 1197, 1197, 1198))
        self.assertEqual(r.items, (decode.Item(65271, 1, 25),))

    def test_level_up(self):
        self.assertEqual(decode.level_up(struct.pack('<IIIx', 0x10017, 0, 222201)), (222201, 23))


class Lineups(unittest.TestCase):
    def test_trailer_allowed_other_length_refused(self):
        lu = decode.parse_lineup(lineup(7, trailer=bytes.fromhex('30580a000100')))
        self.assertEqual(len(lu.monsters), 2)
        with self.assertRaises(ValueError):
            decode.parse_lineup(lineup(7, trailer=b'\0\0\0'))


class Framing(unittest.TestCase):
    def test_frames_split_across_records_keep_the_first_tick(self):
        a, b = frame(decode.OP_MAP, sample.MAP), frame(decode.OP_LINEUP, sample.LINEUP)
        lines = [recv(100, a + b[:30]), request(150, 0x1001, b'\x01\x02'), recv(200, b[30:]), '{"kind":"wire_send"}']
        out = decode.tap_packets(lines, DECODE)
        self.assertEqual([(p.tick, p.direction, p.opcode) for p in out],
                         [(100, decode.RECV, decode.OP_MAP), (150, decode.SEND, 0x1001), (100, decode.RECV, decode.OP_LINEUP)])
        self.assertEqual(out[0].body, sample.MAP)
        self.assertEqual(out[2].body, sample.LINEUP)

    def test_pack_round_trip(self):
        ps = [decode.Packet(1000, decode.RECV, 0x4104, b'abc'), decode.Packet(1500, decode.SEND, 0x1001, b'')]
        self.assertEqual(decode.unpack_packets(decode.pack_packets(ps, 900), 900), ps)


def P(tick, opcode, body, direction=decode.RECV):
    return decode.Packet(tick, direction, opcode, body)


class Assembly(unittest.TestCase):
    def test_two_battles_patrol_level_up_and_unfinished(self):
        ps = [P(1000, decode.OP_MAP, struct.pack('<3H', 700, 10, 20)), P(1010, decode.OP_LINEUP, lineup(7)),
              P(2000, 0x4104, b'x'), P(2100, 0x1001, b'', decode.SEND),
              P(5000, decode.OP_RESULT, result(8, 99)),                 # a teammate's result: not ours
              P(5100, decode.OP_LEVEL_UP, struct.pack('<IIIx', 23, 0, 7)),
              P(5200, decode.OP_RESULT, result(7, 1582, [(65271, 1, 25)])),
              P(9200, decode.OP_MAP, struct.pack('<3H', 700, 30, 40)), P(9210, decode.OP_LINEUP, lineup(7))]
        b1, b2 = decode.assemble(ps)
        self.assertEqual((b1.start_tick, b1.end_tick, b1.patrol_ms, b1.map_id, b1.level_after), (1000, 5200, None, 700, 23))
        self.assertEqual(b1.result.exp, 1582)
        self.assertEqual([p.opcode for p in b1.packets],
                         [0x4104, 0x1001, decode.OP_RESULT, decode.OP_LEVEL_UP, decode.OP_RESULT])
        self.assertEqual((b2.start_tick, b2.end_tick, b2.patrol_ms, b2.x), (9200, None, 4000, 30))

    def test_lineup_without_map_opens_a_battle(self):
        (b,) = decode.assemble([P(10, decode.OP_LINEUP, lineup(7)), P(20, decode.OP_RESULT, result(7, 5))])
        self.assertEqual((b.start_tick, b.map_id, b.result.exp), (10, None, 5))

    def test_bad_lineup_is_kept_with_error(self):
        (b,) = decode.assemble([P(10, decode.OP_LINEUP, lineup(7, trailer=b'\0')), P(20, decode.OP_RESULT, result(7, 5))])
        self.assertIsNone(b.lineup)
        self.assertEqual(b.own_id, 7)
        self.assertEqual(b.result.exp, 5)
        self.assertTrue(b.errors)


class Store(unittest.TestCase):
    def db(self):
        db = sqlite3.connect(':memory:')
        db.executescript(store.SCHEMA)
        return db

    def test_row_and_teammate_fill(self):
        db = self.db()
        mine = decode.assemble([P(1000, decode.OP_MAP, sample.MAP), P(1000, decode.OP_LINEUP, sample.LINEUP),
                                P(9000, decode.OP_RESULT, sample.RESULT)])
        mate = decode.assemble([P(2000, decode.OP_LINEUP, lineup(222200, players=[(222201, '亿万20', 19)])),
                                P(9000, decode.OP_RESULT, result(222200, 1926))])
        rows = [store.to_row(mine[0], 'a', 1, 100.0), store.to_row(mate[0], 'b', 2, 99.0)]
        self.assertEqual((rows[0]['fight_s'], rows[0]['start_time'], rows[0]['monster_levels']), (8.0, 101.0, '21 21 21 21 21'))
        self.assertEqual(json.loads(rows[0]['items']), [[65271, 1, 25]])
        store.save(db, rows)
        self.assertEqual(store.fill_from_teammates(db), (2, 2))         # each is listed in the other's lineup
        self.assertEqual(db.execute("select role, level from battles where source = 'a'").fetchone(), ('亿万20', 19))
        self.assertEqual(db.execute("select role, level from battles where source = 'b'").fetchone(), ('亿万19', 19))
        blob, t0 = db.execute("select packets, start_tick from battles where source = 'a'").fetchone()
        self.assertEqual(decode.unpack_packets(blob, t0)[-1].body, sample.RESULT)

    def test_teammate_too_far_in_time_gives_no_level(self):
        db = self.db()
        mine = decode.assemble([P(1000, decode.OP_LINEUP, lineup(5)), P(2000, decode.OP_RESULT, result(5, 1))])
        mate = decode.assemble([P(1000, decode.OP_LINEUP, lineup(6, players=[(5, 'x', 30)])),
                                P(2000, decode.OP_RESULT, result(6, 1))])
        store.save(db, [store.to_row(mine[0], 'a', 1, 0.0), store.to_row(mate[0], 'b', 2, 60.0)])
        self.assertEqual(store.fill_from_teammates(db), (1, 0))


class Import(unittest.TestCase):
    def test_import_then_skip_unchanged_then_reimport_grown_file(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / 'tap_42_codec.json').write_text(json.dumps({'decode': [t.hex() for t in DECODE]}))
            tap = d / 'tap_42.jsonl'
            first = [recv(1000, frame(decode.OP_MAP, sample.MAP) + frame(decode.OP_LINEUP, sample.LINEUP)),
                     recv(9000, frame(decode.OP_RESULT, sample.RESULT))]
            tap.write_text('\n'.join(first) + '\n')
            os.utime(tap, (5000.0, 5000.0))
            db = sqlite3.connect(':memory:')
            db.executescript(store.SCHEMA)
            self.assertEqual(cli.import_file(db, tap, now=1.0), 1)
            self.assertIsNone(cli.import_file(db, tap, now=2.0))
            row = db.execute('select exp, start_time, end_time, map_id from battles').fetchone()
            self.assertEqual(row, (1926, 4992.0, 5000.0, 700))
            tap.write_text('\n'.join(first + [recv(12000, frame(decode.OP_MAP, sample.MAP))]) + '\n{"kind":')
            os.utime(tap, (6000.0, 6000.0))
            self.assertEqual(cli.import_file(db, tap, now=3.0), 2)
            self.assertEqual(db.execute('select count(*), count(end_tick) from battles').fetchone(), (2, 1))
            self.assertEqual(db.execute('select patrol_s from battles where end_tick is null').fetchone(), (3.0,))


if __name__ == '__main__':
    unittest.main()
