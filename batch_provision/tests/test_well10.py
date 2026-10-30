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


if __name__ == '__main__':
    unittest.main()
