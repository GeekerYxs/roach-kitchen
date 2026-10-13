"""Unit tests for stage 4a (well team forming + 地瓜), no game needed."""
import struct
import unittest
from dataclasses import replace

from factory.phase import POTATO_ITEM, POTATO_RENEW, AltObs, Ledger
from factory.wellteam import (ACCEPT_DELAY, ACTION_POTATO, CONFIRM_WAIT, INVITE_RANGE, INVITE_WAIT, JOIN_WAIT,
                              RENDEZVOUS_RADIUS, SETTLE, SPAWN, Eat, Join, decide_leader, decide_member,
                              decide_potato, pick)
from provisioner.game import team_invite_body
from provisioner.world import BagSlot, Team, WorldState

LEADER = 900
ALT = 7
W = WorldState(char_id=ALT, map_id=1, x=1266.0, y=1174.0, target_x=0.0, target_y=0.0, flags=0, busy=False,
               in_battle=False, nav_active=False, verification=False)
LW = replace(W, char_id=LEADER, x=1300.0)
NO_TEAM = Team((), (), 0)
LEADER_ALONE = Team((), (), 0)


def team_of(*ids, inviter=0):
    return Team(tuple(ids), tuple(1 for _ in ids), inviter)


class Leader(unittest.TestCase):
    def test_ready_at_spawn_standing_still(self):
        self.assertEqual(decide_leader(LW, NO_TEAM, LEADER, set(), SETTLE).kind, 'ready')

    def test_waits_to_settle(self):
        self.assertEqual(decide_leader(LW, NO_TEAM, LEADER, set(), SETTLE - 0.1).kind, 'wait')

    def test_far_walks_unless_already_walking(self):
        far = replace(LW, x=SPAWN[0] + RENDEZVOUS_RADIUS + 50)
        self.assertEqual(decide_leader(far, NO_TEAM, LEADER, set(), 9).kind, 'walk')
        self.assertEqual(decide_leader(replace(far, nav_active=True), NO_TEAM, LEADER, set(), 9).kind, 'wait')

    def test_other_map_fails(self):
        self.assertEqual(decide_leader(replace(LW, map_id=130), NO_TEAM, LEADER, set(), 9).kind, 'fail')

    def test_in_someone_elses_team_fails(self):
        self.assertEqual(decide_leader(LW, team_of(5, LEADER), LEADER, {5}, 9).kind, 'fail')

    def test_stranger_in_own_team_fails_known_alt_is_fine(self):
        self.assertEqual(decide_leader(LW, team_of(LEADER, 42), LEADER, {ALT}, 9).kind, 'fail')
        self.assertEqual(decide_leader(LW, team_of(LEADER, ALT), LEADER, {ALT}, 9).kind, 'ready')


class Pick(unittest.TestCase):
    def test_fills_up_oldest_first_after_adopted(self):
        self.assertEqual(pick([1, 2, 3, 4, 5], adopted=[9], size=4), [1, 2, 3])

    def test_adopted_not_counted_twice(self):
        self.assertEqual(pick([9, 1, 2], adopted=[9], size=2), [1])

    def test_full_team_picks_nobody(self):
        self.assertEqual(pick([1], adopted=[5, 6, 7, 8], size=4), [])


class Member(unittest.TestCase):
    def d(self, world=W, team=NO_TEAM, leader_team=None, memo=None, now=10.0):
        return decide_member(ALT, world, team, LEADER, LW, leader_team or team_of(), memo or Join(), now)

    def test_invites_idle_alt_in_range(self):
        self.assertEqual(self.d().kind, 'invite')

    def test_busy_waits_far_fails(self):
        self.assertEqual(self.d(world=replace(W, in_battle=True)).kind, 'wait')
        self.assertEqual(self.d(world=replace(W, x=LW.x + INVITE_RANGE + 1)).kind, 'fail')

    def test_accepts_only_after_the_invite_shows_and_a_short_delay(self):
        memo = Join(invited_at=10.0)
        invited = team_of(inviter=LEADER)
        self.assertEqual(self.d(team=invited, memo=memo, now=10.0 + ACCEPT_DELAY - 0.1).kind, 'wait')
        self.assertEqual(self.d(team=invited, memo=memo, now=10.0 + ACCEPT_DELAY).kind, 'accept')

    def test_invite_never_arrives(self):
        memo = Join(invited_at=10.0)
        self.assertEqual(self.d(memo=memo, now=10.0 + INVITE_WAIT - 0.1).kind, 'wait')
        self.assertEqual(self.d(memo=memo, now=10.0 + INVITE_WAIT).kind, 'unconfirmed')

    def test_joined_needs_both_rosters(self):
        mine = team_of(LEADER, ALT)
        self.assertEqual(self.d(team=mine, leader_team=team_of(LEADER, ALT)).kind, 'joined')
        memo = Join(invited_at=1.0, accepted_at=10.0)
        self.assertEqual(self.d(team=mine, leader_team=team_of(LEADER), memo=memo, now=10.5).kind, 'wait')

    def test_accept_without_joining_times_out(self):
        memo = Join(invited_at=1.0, accepted_at=10.0)
        self.assertEqual(self.d(memo=memo, now=10.0 + JOIN_WAIT).kind, 'unconfirmed')

    def test_other_team_fails(self):
        self.assertEqual(self.d(team=team_of(55, ALT)).kind, 'fail')


OBS = AltObs(char_id=ALT, map_id=1, level=2, gold=500, team_leader=LEADER, quest='none', potatoes=2)
BAG = (BagSlot(0, 1, 1), BagSlot(4, POTATO_ITEM, 2))


class Potato(unittest.TestCase):
    def d(self, obs=OBS, bag=BAG, ledger=Ledger(), pending=None, memo=None, now=10.0, wall=100000.0):
        return decide_potato(obs, W, bag, ledger, pending, memo or Eat(), now, wall)

    def test_eats_from_the_potato_slot(self):
        d = self.d()
        self.assertEqual((d.kind, d.arg.slot), ('use', 4))

    def test_recently_eaten_is_done(self):
        self.assertEqual(self.d(ledger=Ledger(potato_at=100000.0 - 600)).kind, 'done')

    def test_second_potato_after_renew_time(self):
        self.assertEqual(self.d(ledger=Ledger(potato_at=100000.0 - POTATO_RENEW)).kind, 'use')

    def test_no_potato_or_level_11_skips(self):
        self.assertEqual(self.d(obs=replace(OBS, potatoes=0)).kind, 'skip')
        self.assertEqual(self.d(obs=replace(OBS, level=11)).kind, 'skip')

    def test_count_drop_verifies_else_unconfirmed(self):
        memo = Eat(sent_at=10.0, count_before=2)
        self.assertEqual(self.d(bag=(BagSlot(4, POTATO_ITEM, 1),), memo=memo, now=10.4).kind, 'verified')
        self.assertEqual(self.d(memo=memo, now=10.0 + CONFIRM_WAIT - 0.1).kind, 'wait')
        self.assertEqual(self.d(memo=memo, now=10.0 + CONFIRM_WAIT).kind, 'unconfirmed')

    def test_pending_after_crash_counts_as_eaten(self):
        self.assertEqual(self.d(pending=ACTION_POTATO).kind, 'verified')

    def test_battle_waits(self):
        self.assertEqual(decide_potato(OBS, replace(W, in_battle=True), BAG, Ledger(), None, Eat(), 0, 1e5).kind,
                         'wait')


class InviteBody(unittest.TestCase):
    def test_layout_matches_the_client(self):
        body = team_invite_body(202851, 44, 50, '小强')
        self.assertEqual(len(body), 33)
        self.assertEqual(struct.unpack_from('<4I', body), (202851, 0, 44, 50))
        self.assertEqual(body[16:], '小强'.encode('gbk').ljust(17, b'\0'))

    def test_name_too_long(self):
        with self.assertRaises(ValueError):
            team_invite_body(1, 1, 1, '一二三四五六七八九')


if __name__ == '__main__':
    unittest.main()
