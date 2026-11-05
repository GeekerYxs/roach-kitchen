"""well10.py: the masters must cast (pet 烈焰爆发) in the well by themselves, not rely on the client's 战斗辅助 switch
(2026-10-30: off after every relog, so the masters' pets only normal-attacked). Source check: the loop needs the game."""
import ast
import unittest
from pathlib import Path

SRC = (Path(__file__).resolve().parent.parent / 'research' / 'shitu' / 'well10.py').read_text(encoding='utf-8')


class WellMastersCast(unittest.TestCase):
    def test_masters_get_a_caster_and_it_ticks_in_battle(self):
        main = next(n for n in ast.walk(ast.parse(SRC)) if isinstance(n, ast.FunctionDef) and n.name == 'main')
        body = ast.unparse(main)
        self.assertIn('from lunhui15 import Caster', body)
        self.assertIn('casters = {n: Caster(cs[n]) for n in HELPERS}', body)
        self.assertIn('casters[n].tick(now)', body)
        self.assertIn('casters[n].reset()', body)


class ApprenticesSendNothing(unittest.TestCase):
    def test_no_member_attack_in_the_well(self):
        # user 2026-11-05: in the well only the masters fight; the apprentices send nothing (as on every other map)
        src = (Path(__file__).resolve().parent.parent / 'research' / 'shitu' / 'well10.py').read_text(encoding='utf-8')
        self.assertNotIn('fight_command(', src)
        self.assertNotIn('FIGHT_ATTACK', src)


if __name__ == '__main__':
    unittest.main()
