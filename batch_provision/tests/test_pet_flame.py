"""lunhui15.Caster pet rule (user 2026-11-05, from the 70 project; 勇者 / 元素使 / 70 alike): the pet casts 烈焰爆发 as
soon as it has SP, keeps one cast pending until it settles (server 0x4111 for its position, SP change, or its MP
dropping), then casts again at once while SP is left (完美施法 keeps the point 20% of the time). No blind resend while
pending; never a normal attack while it has MP."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'shitu'))

import lunhui15 as L  # noqa: E402
from provisioner.world import Fighter  # noqa: E402

PET_POS = 11


def caster(tap=None):
    c = NS(name='波大臀圆', mem=None, game=mock.Mock())
    k = L.Caster.__new__(L.Caster)
    k.c, k.skill_id, k.skill, k.strict_skill, k.pet_level = c, 0, 0, False, 13
    k.casts, k.reviver, k.tap = 0, None, tap
    k.reset()
    return k


def battle(pet_sp, me_sp=1):
    return NS(me=Fighter(10, me_sp, False), pet=Fighter(PET_POS, pet_sp, False), enemies=[3])


class Tap:
    def __init__(self):
        self.packets = []

    def poll(self):
        out, self.packets = self.packets, []
        return out


class PetFlame(unittest.TestCase):
    def run_tick(self, k, b, now, mp=500):
        with mock.patch.object(L.w, 'read_battle', return_value=b), \
                mock.patch.object(L.w, 'read_fighting_pet', return_value=NS(mp=mp)), \
                mock.patch.object(L.t, 'say'):
            k.tick(now)

    def casts(self, k):
        return k.c.game.cast_pet_magic.call_count

    def test_first_tick_casts(self):
        k = caster()
        self.run_tick(k, battle(2), 100.0)
        k.c.game.cast_pet_magic.assert_called_once_with(3, L.PET_MAGIC, 13)

    def test_no_resend_while_pending(self):
        k = caster()
        self.run_tick(k, battle(1), 100.0)
        for dt in (0.6, 1.2, 2.0, 3.0):                       # the old rule resent every 0.6 s here
            self.run_tick(k, battle(1), 100.0 + dt)
        self.assertEqual(self.casts(k), 1)

    def test_perfect_cast_mp_drop_recasts_at_once(self):
        k = caster()
        self.run_tick(k, battle(1), 100.0, mp=500)
        self.run_tick(k, battle(1), 100.4, mp=337)            # the cast ran, SP kept: 完美施法
        self.assertEqual(self.casts(k), 2)

    def test_sp_change_with_points_left_recasts(self):
        k = caster()
        self.run_tick(k, battle(2), 100.0)
        self.run_tick(k, battle(1), 100.3)
        self.assertEqual(self.casts(k), 2)

    def test_spent_to_zero_waits(self):
        k = caster()
        self.run_tick(k, battle(1), 100.0)
        self.run_tick(k, battle(0), 100.3)
        self.assertEqual(self.casts(k), 1)
        self.run_tick(k, battle(1), 102.8)                    # a new point: cast at once
        self.assertEqual(self.casts(k), 2)

    def test_server_end_packet_settles(self):
        tap = Tap()
        k = caster(tap)
        self.run_tick(k, battle(1), 100.0)
        tap.packets = [(100.2, 'S->C', 0x4111, bytes([PET_POS + 1, 1]), 0)]   # another position: not ours
        self.run_tick(k, battle(1), 100.3)
        self.assertEqual(self.casts(k), 1)
        tap.packets = [(k.pet_sent[2] + 0.1, 'S->C', 0x4111, bytes([PET_POS, 1]), 0)]
        self.run_tick(k, battle(1), 100.4)
        self.assertEqual(self.casts(k), 2)

    def test_mp_drop_ignored_with_tap(self):
        tap = Tap()
        k = caster(tap)
        self.run_tick(k, battle(1), 100.0, mp=500)
        self.run_tick(k, battle(1), 100.2, mp=402)            # cast ran; the settle packet is still to come
        self.assertEqual(self.casts(k), 1)
        tap.packets = [(0, 'S->C', 0x4111, bytes([PET_POS, 1]), 0)]
        self.run_tick(k, battle(1), 100.3, mp=402)
        self.assertEqual(self.casts(k), 2)

    def test_server_zero_beats_stale_memory(self):
        tap = Tap()
        k = caster(tap)
        self.run_tick(k, battle(1), 100.0)
        tap.packets = [(0, 'S->C', 0x4111, bytes([PET_POS, 0]), 0)]       # server: SP 0, memory still 1
        self.run_tick(k, battle(1), 101.3)
        self.run_tick(k, battle(1), 101.5)
        self.assertEqual(self.casts(k), 1)
        self.run_tick(k, battle(2), 104.0)                                 # memory moves on: a real new point
        self.assertEqual(self.casts(k), 2)

    def test_turn_packet_casts_before_memory(self):
        tap = Tap()
        k = caster(tap)
        tap.packets = [(0, 'S->C', 0x4105, bytes([PET_POS]), 0)]           # server: the pet's turn; memory SP 0
        self.run_tick(k, battle(0), 100.0)
        self.assertEqual(self.casts(k), 1)
        self.run_tick(k, battle(0), 100.05)                                 # memory still 0: no settle, no recast
        self.run_tick(k, battle(1), 100.1)                                  # memory catches up: same pending cast
        self.assertEqual(self.casts(k), 1)
        tap.packets = [(0, 'S->C', 0x4111, bytes([PET_POS, 0]), 0)]
        self.run_tick(k, battle(0), 100.3)
        self.assertEqual(self.casts(k), 1)

    def test_player_turn_packet_casts_once(self):
        tap = Tap()
        k = caster(tap)
        k.skill_id, k.skill = 206, 12
        tap.packets = [(0, 'S->C', 0x4105, bytes([10]), 0)]                 # me at position 10 in battle()
        self.run_tick(k, battle(0, me_sp=0), 100.0)
        k.c.game.cast_magic_skill_captured.assert_called_once_with(3, 206, 12)
        self.run_tick(k, battle(0, me_sp=0), 100.05)
        self.run_tick(k, battle(0, me_sp=1), 100.1)
        self.assertEqual(k.c.game.cast_magic_skill_captured.call_count, 1)

    @mock.patch.object(L, 'TURN_PACKET', False)
    def test_turn_packet_off(self):
        tap = Tap()
        k = caster(tap)
        tap.packets = [(0, 'S->C', 0x4105, bytes([PET_POS]), 0)]
        self.run_tick(k, battle(0), 100.0)
        self.assertEqual(self.casts(k), 0)

    def test_fallback_only_without_tap(self):
        k = caster()
        self.run_tick(k, battle(1), 100.0)
        self.run_tick(k, battle(1), 100.0 + L.PET_SETTLE_FALLBACK + 0.01)
        self.assertEqual(self.casts(k), 2)
        k = caster(Tap())
        self.run_tick(k, battle(1), 100.0)
        self.run_tick(k, battle(1), 100.0 + L.PET_SETTLE_FALLBACK + 0.01)
        self.assertEqual(self.casts(k), 1)

    def test_never_a_normal_pet_attack_with_mp(self):
        k = caster()
        now = 100.0
        for _ in range(12):
            self.run_tick(k, battle(2), now)
            now += 1.0
        pet_attacks = [c for c in k.c.game.fight_command.call_args_list if c.kwargs.get('is_pet')]
        self.assertEqual(pet_attacks, [])

    def test_no_sp_no_command(self):
        k = caster()
        self.run_tick(k, battle(0), 100.0)
        k.c.game.cast_pet_magic.assert_not_called()

    @mock.patch.dict('os.environ', {'SHITU_PET_MAGIC_ONLY': ''})    # the 70 project's _bootstrap sets it to 1
    def test_out_of_mp_attacks(self):
        k = caster()
        self.run_tick(k, battle(1), 100.0, mp=L.PET_MP_MIN - 1)
        k.c.game.cast_pet_magic.assert_not_called()
        pet_attacks = [c for c in k.c.game.fight_command.call_args_list if c.kwargs.get('is_pet')]
        self.assertEqual(len(pet_attacks), 1)


if __name__ == '__main__':
    unittest.main()
