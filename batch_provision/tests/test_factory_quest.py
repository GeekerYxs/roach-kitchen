"""Unit tests for the quest-78 stage decision and the quest reads it relies on (no game needed)."""
import struct
import unittest
from dataclasses import replace

from factory.observe import quest_state
from factory.phase import QUEST_ACTIVE, QUEST_DONE, QUEST_NONE
from factory.quest import (ACTION, CONFIRM_WAIT, MAX_CLICKS, NPC, SELECT_RETRY, STAND_POINT, Memo, decide,
                           menu_choice)
from provisioner import world
from provisioner.world import Dialog, Quest, Team, WorldState, read_quest

AT_NPC = WorldState(char_id=1, map_id=81, x=1780.0, y=1370.0, target_x=1780.0, target_y=1370.0, flags=0,
                    busy=False, in_battle=False, nav_active=False, verification=False, still_for=1.0)
LANDED = replace(AT_NPC, x=1152.0, y=932.0, target_x=0.0, target_y=0.0)
NONE, ACTIVE, DONE = Quest(False, False), Quest(True, False, (1,)), Quest(False, True)
SOLO = Team((), (), 0)
ROW = {'pending_action': None}


def page(*labels):
    text = ''.join(f'[URL]{label}[/URL]' for label in labels) + '[URL]离开[/URL]'
    return Dialog(text, tuple((i, label) for i, label in enumerate(labels, 1)) + ((0, '离开'),))


FIRST = page('飞刀王的晚餐(11)[未接受]')
LAST = page('接受任务。')


class Decide(unittest.TestCase):
    def test_far_navigates_to_stand_point(self):
        d = decide(LANDED, NONE, SOLO, ROW, Memo(), 0.0)
        self.assertEqual((d.kind, d.arg), ('navigate', (81, *STAND_POINT)))

    def test_walking_waits_then_stall_cancels(self):
        walking = replace(LANDED, nav_active=True)
        memo = Memo(last_nav=0.0, progress_at=0.0)
        self.assertEqual(decide(walking, NONE, SOLO, ROW, memo, 3.0).kind, 'wait')
        self.assertEqual(decide(walking, NONE, SOLO, ROW, memo, 7.0).kind, 'cancel_nav')

    def test_at_npc_clicks_once_per_wait(self):
        d = decide(AT_NPC, NONE, SOLO, ROW, Memo(), 0.0)
        self.assertEqual((d.kind, d.arg), ('click', NPC))
        self.assertEqual(decide(AT_NPC, NONE, SOLO, ROW, Memo(clicked_at=0.0, clicks=1), 1.0).kind, 'wait')
        self.assertEqual(decide(AT_NPC, NONE, SOLO, ROW, Memo(clicked_at=0.0, clicks=MAX_CLICKS), 9.0).kind, 'fail')

    def test_at_npc_stops_navigation_and_settles(self):
        self.assertEqual(decide(replace(AT_NPC, nav_active=True), NONE, SOLO, ROW, Memo(), 0).kind, 'cancel_nav')
        self.assertEqual(decide(replace(AT_NPC, still_for=0.1), NONE, SOLO, ROW, Memo(), 0).kind, 'wait')

    def test_menu_pages_select_then_accept(self):
        d = decide(replace(AT_NPC, dialog=FIRST), NONE, SOLO, ROW, Memo(), 0.0)
        self.assertEqual((d.kind, d.arg), ('select', 1))
        d = decide(replace(AT_NPC, dialog=LAST), NONE, SOLO, ROW, Memo(), 0.0)
        self.assertEqual((d.kind, d.arg), ('accept', 1))

    def test_same_page_waits_then_chooses_again(self):
        memo = Memo(select_at=10.0, select_text=FIRST.text, selects=1)
        w = replace(AT_NPC, dialog=FIRST)
        self.assertEqual(decide(w, NONE, SOLO, ROW, memo, 10.0 + SELECT_RETRY - 0.1).kind, 'wait')
        self.assertEqual(decide(w, NONE, SOLO, ROW, memo, 10.0 + SELECT_RETRY).kind, 'select')
        # a new page is answered at once
        self.assertEqual(decide(replace(AT_NPC, dialog=LAST), NONE, SOLO, ROW, memo, 10.1).kind, 'accept')

    def test_unknown_menu_fails(self):
        d = decide(replace(AT_NPC, dialog=page('买东西')), NONE, SOLO, ROW, Memo(), 0.0)
        self.assertEqual(d.kind, 'fail')

    def test_accept_waits_for_table_then_unconfirmed(self):
        memo = Memo(accept_at=10.0)
        self.assertEqual(decide(AT_NPC, NONE, SOLO, ROW, memo, 10.0 + CONFIRM_WAIT - 0.1).kind, 'wait')
        self.assertEqual(decide(AT_NPC, NONE, SOLO, ROW, memo, 10.0 + CONFIRM_WAIT).kind, 'unconfirmed')

    def test_active_after_accept_is_verified(self):
        self.assertEqual(decide(AT_NPC, ACTIVE, SOLO, ROW, Memo(accept_at=1.0), 2.0).kind, 'verified')
        self.assertEqual(decide(AT_NPC, ACTIVE, SOLO, {'pending_action': ACTION}, Memo(), 0.0).kind, 'verified')

    def test_active_closes_dialog_once(self):
        w = replace(AT_NPC, dialog=page('离开'))
        self.assertEqual(decide(w, ACTIVE, SOLO, ROW, Memo(accept_at=1.0), 2.0).kind, 'close')
        self.assertEqual(decide(w, ACTIVE, SOLO, ROW, Memo(accept_at=1.0, closed_at=2.0), 2.2).kind, 'verified')

    def test_already_active_or_done_sends_nothing(self):
        self.assertEqual(decide(LANDED, ACTIVE, SOLO, ROW, Memo(), 0.0).kind, 'done')
        self.assertEqual(decide(LANDED, DONE, SOLO, ROW, Memo(), 0.0).kind, 'done')

    def test_wrong_map_or_team_fails(self):
        self.assertEqual(decide(replace(LANDED, map_id=1), NONE, SOLO, ROW, Memo(), 0.0).kind, 'fail')
        self.assertEqual(decide(LANDED, NONE, Team((9, 1), (70, 11), 9), ROW, Memo(), 0.0).kind, 'fail')

    def test_battle_escapes_on_sp_change(self):
        w = replace(LANDED, in_battle=True, my_sp=0)
        self.assertEqual(decide(w, NONE, SOLO, ROW, Memo(), 0.0).kind, 'escape')
        self.assertEqual(decide(w, NONE, SOLO, ROW, Memo(last_sp=0, last_escape=0.0), 1.0).kind, 'wait')
        self.assertEqual(decide(replace(w, my_sp=1), NONE, SOLO, ROW, Memo(last_sp=0, last_escape=0.0), 1.0).kind,
                         'escape')

    def test_loading_and_verification_wait(self):
        self.assertEqual(decide(None, NONE, SOLO, ROW, Memo(), 0.0).kind, 'wait')
        self.assertEqual(decide(AT_NPC, None, SOLO, ROW, Memo(), 0.0).kind, 'wait')
        self.assertEqual(decide(replace(AT_NPC, verification=True), NONE, SOLO, ROW, Memo(), 0.0).kind, 'wait')


class Menu(unittest.TestCase):
    def test_deepest_page_wins(self):
        self.assertEqual(menu_choice(page('继续。', '飞刀王的晚餐')), (1, '继续。'))

    def test_two_matches_are_ambiguous(self):
        self.assertEqual(menu_choice(page('继续。', '继续看看')), 'ambiguous')


class FakeMem:
    """Just enough of ProcessMemory for read_quest: a dict of address -> bytes."""
    base = 0x400000

    def __init__(self, blocks):
        self.blocks = blocks

    def read(self, address, size):
        for start, data in self.blocks.items():
            if start <= address and address + size <= start + len(data):
                return data[address - start:address - start + size]
        raise OSError(f'unmapped {address:#x}')

    def u32(self, address):
        return struct.unpack('<I', self.read(address, 4))[0]


def node(left, parent, right, key, size, nil_at, extra=b''):
    raw = bytearray(size)
    struct.pack_into('<4I', raw, 0, left, parent, right, key)
    raw[0x10:0x10 + len(extra)] = extra
    raw[nil_at] = 0
    return bytes(raw)


def sentinel(root, size, nil_at):
    raw = bytearray(size)
    struct.pack_into('<3I', raw, 0, 0, root, 0)
    raw[nil_at] = 1
    return bytes(raw)


def fake_client(active_keys, done_keys, steps=b''):
    session, session_ptr = 0x100000, 0x400000 + world.SESSION_MGR_RVA
    p = session + world.SESSION_PLAYER_DATA
    blocks = {session_ptr: struct.pack('<I', session), p + world.QUEST_ACTIVE: struct.pack('<I', 0x200000),
              p + world.QUEST_DONE: struct.pack('<I', 0x300000)}
    # a degenerate right-leaning chain is still a valid tree for a walk
    for base, keys, size, nil_at in ((0x200000, active_keys, 0x62, 0x61), (0x300000, done_keys, 0x1E, 0x1D)):
        addrs = [base + 0x100 * (i + 1) for i in range(len(keys))]
        blocks[base] = sentinel(addrs[0] if addrs else base, size, nil_at)
        for i, (addr, key) in enumerate(zip(addrs, keys)):
            right = addrs[i + 1] if i + 1 < len(addrs) else base
            extra = bytes(0x16) + steps if size == 0x62 else b''
            blocks[addr] = node(base, base, right, key, size, nil_at, extra)
    return FakeMem(blocks)


class ReadQuest(unittest.TestCase):
    def test_new_alt_without_78(self):
        mem = fake_client([94 << 16], [0, 93, 106, 4022])
        self.assertEqual(read_quest(mem, 78), Quest(False, False, ()))

    def test_active_78_with_steps(self):
        mem = fake_client([94 << 16, 78 << 16], [93], steps=bytes([1, 2, 1]))
        q = read_quest(mem, 78)
        self.assertTrue(q.active and not q.done)
        self.assertEqual(q.steps, (2, 1))

    def test_done_78(self):
        self.assertEqual(read_quest(fake_client([], [93, 78]), 78), Quest(False, True, ()))

    def test_quest_state(self):
        self.assertEqual([quest_state(q) for q in (NONE, ACTIVE, DONE)], [QUEST_NONE, QUEST_ACTIVE, QUEST_DONE])


if __name__ == '__main__':
    unittest.main()
