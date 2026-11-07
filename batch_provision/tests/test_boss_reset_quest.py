"""Unit tests for projects/boss_gear_5/reset_quest.py (no game needed, user 2026-11-07): the 0xA0 abandon body, the
mixed-progress check, and that only the given quests are dropped on the roles that have them."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'projects' / 'boss_gear_5'))

import reset_quest as rq  # noqa: E402


class FakeGame:
    def __init__(self, role):
        self.role, self.sent = role, []

    def send(self, op, body):
        self.sent.append((op, body))
        if op == 0x48:                              # drop: <IBBH>(0, 0, slot, quantity)
            slot = body[5]
            self.role.bag = [b for b in self.role.bag if b.slot != slot]
            return
        quest = int.from_bytes(body[4:8], 'little')
        self.role.quests.pop(quest, None)          # the server drops it


class FakeRole:
    def __init__(self, name, **quests):
        self.name, self.mem = name, None
        self.quests = {int(k[1:]): v for k, v in quests.items()}
        self.game = FakeGame(self)
        self.bag = []

    def dialog(self):
        return None


def fake_read_quest(role, quest):
    s = role.quests.get(quest)
    return SimpleNamespace(active=bool(s), done=False, steps=s or ())


class ResetQuestTest(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(rq.w, 'read_quest', side_effect=lambda mem, q: fake_read_quest(self.by_mem[id(mem)], q))
        p.start()
        self.addCleanup(p.stop)
        mock.patch.object(rq.w, 'read_bag', side_effect=lambda mem: self.by_mem[id(mem)].bag).start()
        mock.patch.object(rq.time, 'sleep').start()
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(rq.t, 'say').start()

    def roles(self, *rs):
        self.by_mem = {}
        for r in rs:
            r.mem = object()
            self.by_mem[id(r.mem)] = r
        return list(rs)

    def test_body_is_zero_then_quest_id(self):
        self.assertEqual(rq.OP_CANCEL_TASK, 0xA0)
        self.assertEqual(rq.cancel_body(518), b'\0\0\0\0' + (518).to_bytes(4, 'little'))

    def test_same_progress(self):
        cs = self.roles(FakeRole('a', q518=(1,)), FakeRole('b', q518=(1,)))
        self.assertTrue(rq.same_progress(cs, 518))
        cs = self.roles(FakeRole('a', q518=(1,)), FakeRole('b', q518=(2, 1)))
        self.assertFalse(rq.same_progress(cs, 518))
        cs = self.roles(FakeRole('a'), FakeRole('b', q518=(1,)))
        self.assertFalse(rq.same_progress(cs, 518))
        self.assertTrue(rq.same_progress(self.roles(FakeRole('a'), FakeRole('b')), 518))

    def test_reset_drops_only_given_quests_on_holders(self):
        a = FakeRole('a', q518=(1,), q475=(1,))
        b = FakeRole('b', q518=(2, 1))
        c = FakeRole('c')
        cs = self.roles(a, b, c)
        dropped = rq.reset(cs, (518,))
        self.assertEqual(len(dropped), 2)
        self.assertEqual(a.quests, {475: (1,)})          # 葵花宝典 left alone
        self.assertEqual(b.quests, {})
        self.assertEqual(c.game.sent, [])                # nothing sent for a role without it

    def test_check_same_resets_only_when_mixed(self):
        a, b = FakeRole('a', q1852=(1,), q1853=(1, 0)), FakeRole('b', q1852=(1,))
        self.assertFalse(rq.check_same(self.roles(a, b), (1852, 1853), 'x'))   # 1853 is leader-only: not compared
        self.assertTrue(a.quests)
        b.quests[1852] = (2, 1)
        self.assertTrue(rq.check_same(self.roles(a, b), (1852, 1853), 'x'))
        self.assertEqual((a.quests, b.quests), ({}, {}))

    def test_reset_drops_left_quest_items_only(self):
        a = FakeRole('a', q673=(1,))
        a.bag = [SimpleNamespace(slot=3, item_id=11169, quantity=1), SimpleNamespace(slot=4, item_id=10779, quantity=1)]
        rq.reset(self.roles(a), (673,), {11169: '老树根'})
        self.assertEqual([b.item_id for b in a.bag], [10779])   # 葵花宝典 stays
        self.assertIn((0x48, bytes([0, 0, 0, 0, 0, 3, 1, 0])), [(op, b) for op, b in a.game.sent])


if __name__ == '__main__':
    unittest.main()
