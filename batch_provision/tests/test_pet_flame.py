"""lunhui15.Caster pet rule (user 2026-11-05, from the 70 project; 勇者 / 元素使 / 70 alike): the pet casts 烈焰爆发 at
the start of every battle, recasts at once while SP is left, and never turns to a normal attack while it has MP."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'shitu'))

import lunhui15 as L  # noqa: E402
from provisioner.world import Fighter  # noqa: E402


def caster(pet_mp=500):
    c = NS(name='波大臀圆', mem=None, game=mock.Mock())
    k = L.Caster.__new__(L.Caster)
    k.c, k.skill_id, k.skill, k.strict_skill, k.pet_level = c, 0, 0, False, 13
    k.me, k.pet, k.casts, k.reviver = L.Fight(), L.Fight(), 0, None
    return k, NS(mp=pet_mp)


def battle(pet_sp, me_sp=1):
    return NS(me=Fighter(10, me_sp, False), pet=Fighter(11, pet_sp, False), enemies=[3])


class PetFlame(unittest.TestCase):
    def run_tick(self, k, pet, b, now):
        with mock.patch.object(L.w, 'read_battle', return_value=b), \
                mock.patch.object(L.w, 'read_fighting_pet', return_value=pet), \
                mock.patch.object(L.t, 'say'):
            k.tick(now)

    def test_first_tick_casts(self):
        k, pet = caster()
        self.run_tick(k, pet, battle(2), 100.0)
        k.c.game.cast_pet_magic.assert_called_once_with(3, L.PET_MAGIC, 13)

    def test_same_sp_recasts_after_retry_gap(self):
        k, pet = caster()
        self.run_tick(k, pet, battle(2), 100.0)
        self.run_tick(k, pet, battle(2), 100.0 + L.PET_SP_RETRY / 2)
        self.assertEqual(k.c.game.cast_pet_magic.call_count, 1)
        self.run_tick(k, pet, battle(2), 100.0 + L.PET_SP_RETRY + 0.01)
        self.assertEqual(k.c.game.cast_pet_magic.call_count, 2)

    def test_never_a_normal_pet_attack_with_mp(self):
        k, pet = caster()
        now = 100.0
        for _ in range(12):                          # far past MAX_SKILL_SENDS with SP stuck at 2
            self.run_tick(k, pet, battle(2), now)
            now += L.PET_SP_RETRY + 0.01
        pet_attacks = [c for c in k.c.game.fight_command.call_args_list if c.kwargs.get('is_pet')]
        self.assertEqual(pet_attacks, [])
        self.assertGreater(k.c.game.cast_pet_magic.call_count, 3)

    def test_no_sp_no_command(self):
        k, pet = caster()
        self.run_tick(k, pet, battle(0), 100.0)
        k.c.game.cast_pet_magic.assert_not_called()


if __name__ == '__main__':
    unittest.main()
