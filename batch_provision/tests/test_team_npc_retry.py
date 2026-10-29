"""team_npc.main: an apprentice that gets no dialog is retried after the others, RETRY_PASSES times (round 6)."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'shitu'))

import team_npc  # noqa: E402


class Retry(unittest.TestCase):
    def run_main(self, fails):
        """fails: name -> how many talks fail before one works."""
        calls, left = [], dict(fails)

        def talk(c, *a):
            calls.append(c.name)
            if left.get(c.name, 0) > 0:
                left[c.name] -= 1
                raise team_npc.t.Stop(f'{c.name} 没对话框')
        with mock.patch.object(team_npc, 'talk', talk), \
                mock.patch.object(team_npc.t, 'Client', lambda n: NS(name=n, team=lambda: ())), \
                mock.patch.object(team_npc.time, 'sleep', lambda s: None):
            team_npc.main(650, 986, (1, 1), 'x', 181, 'm', ['a', 'b', 'c', 'd'], regroup=False)
        return calls

    def test_last_one_retried_after_the_others(self):
        self.assertEqual(self.run_main({'d': 1}), ['a', 'b', 'c', 'd', 'd'])

    def test_relog_before_the_last_pass(self):
        import r4_util
        relogged = []
        with mock.patch.dict('os.environ', {'PAIRS': 'cap1:a cap2:b cap3:c cap4:d'}),                 mock.patch.object(r4_util, 'relog', lambda acc, names: relogged.append((acc, names))):
            self.assertEqual(self.run_main({'d': 2}), ['a', 'b', 'c', 'd', 'd', 'd'])
        self.assertEqual(relogged, [(['cap1:a', 'cap2:b', 'cap3:c', 'cap4:d'], ['d'])])

    def test_gives_up_after_the_passes(self):
        with self.assertRaises(team_npc.t.Stop):
            self.run_main({'b': 9})


if __name__ == '__main__':
    unittest.main()
