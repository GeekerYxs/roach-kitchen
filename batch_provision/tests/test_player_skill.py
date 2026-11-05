"""lunhui15.Caster player skill (user 2026-11-05): 猎人 扫射 803, 方士 天之箭 354, otherwise the first magic slot
(元素使 魔法火焰 206: the game's own F1 cast sent skill 206 lv12, 1504 烈焰爆发 is the pet's and got 「无此魔法」);
nothing found -> normal attack."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'shitu'))

import lunhui15 as L  # noqa: E402
from provisioner.world import Fighter  # noqa: E402


def make(skills, slot):
    c = NS(name='欧皇丨花花乀', mem=None, game=mock.Mock())
    with mock.patch.object(L.w, 'read_skill_level', lambda mem, sid: skills.get(sid, 0)), \
            mock.patch.object(L.w, 'read_assist_skill', return_value=slot), \
            mock.patch.object(L.w, 'read_fighting_pet', return_value=None), \
            mock.patch.object(L.t, 'say'):
        return L.Caster(c)


def battle():
    return NS(me=Fighter(10, 1, False), pet=None, enemies=[3])


def tick(k):
    with mock.patch.object(L.w, 'read_battle', return_value=battle()), \
            mock.patch.object(L.w, 'read_fighting_pet', return_value=None), mock.patch.object(L.t, 'say'):
        k.tick(100.0)


class PlayerSkill(unittest.TestCase):
    def test_hunter_strafe(self):
        k = make({803: 6}, (206, 12))
        self.assertEqual((k.skill_id, k.skill), (803, 6))
        tick(k)
        k.c.game.cast_skill.assert_called_once_with(3, 803, 6)

    def test_scholar_arrow(self):
        k = make({354: 7}, None)
        tick(k)
        k.c.game.cast_magic_skill_captured.assert_called_once_with(3, 354, 7)

    def test_elementalist_magic_fire_from_slot(self):
        k = make({}, (206, 12))
        self.assertEqual((k.skill_id, k.skill), (206, 12))
        tick(k)
        k.c.game.cast_magic_skill_captured.assert_called_once_with(3, 206, 12)
        k.c.game.cast_skill.assert_not_called()

    def test_unknown_slot_skill_attacks(self):
        k = make({}, (1504, 9))                     # the pet's magic is not a player skill
        self.assertEqual(k.skill, 0)
        tick(k)
        k.c.game.fight_command.assert_called_once()
        k.c.game.cast_magic_skill_captured.assert_not_called()

    def test_nothing_readable_attacks(self):
        k = make({}, None)
        tick(k)
        k.c.game.fight_command.assert_called_once()


if __name__ == '__main__':
    unittest.main()
