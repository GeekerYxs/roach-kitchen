"""Gemini test machine 2026-11-06 report, the three stalls our main still had:
  - bai_shi.team_master_lead invited from ~283 px without walking over; now it goes through teamwalk.regroup.
  - r4_util.restock sent lv < 10 apprentices to the 自由市场 portal (needs lv 10); now they are skipped.
  - trial_run.open_menu clicked 糊涂博士 once; now a left-open dialog is closed (and logged) and the click repeated."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'shitu'))

import bai_shi  # noqa: E402
import r4_util  # noqa: E402
import teamwalk  # noqa: E402
import trial_run  # noqa: E402


class Role:
    def __init__(self, name, cid, x, y, map_id=1):
        self.name, self.char_id, self.members = name, cid, ()
        self.pos = NS(map_id=map_id, x=x, y=y)
        self.game = NS(team_leave=self.leave, team_invite=mock.Mock(), team_accept=mock.Mock())

    def leave(self):
        self.members = ()

    def team(self):
        return self.members

    def world(self):
        return self.pos


class TeamMasterLead(unittest.TestCase):
    def run_lead(self, m, a):
        calls = []

        def regroup(lead, members):
            calls.append((lead.name, [c.name for c in members], teamwalk.MAP))
            lead.members = members[0].members = (lead.char_id, members[0].char_id)
        with mock.patch.object(teamwalk, 'regroup', regroup), mock.patch.object(bai_shi.t, 'say', lambda s: None):
            bai_shi.team_master_lead(m, a)
        return calls

    def test_far_apart_goes_through_regroup(self):
        m, a = Role('伏地魔', 1, 1370, 1336), Role('魔徒E12', 2, 1328, 1056)
        self.assertEqual(self.run_lead(m, a), [('伏地魔', ['魔徒E12'], 1)])
        m.game.team_invite.assert_not_called()          # no bare invite from 283 px
        self.assertEqual(a.team(), (1, 2))

    def test_already_together_is_left_alone(self):
        m, a = Role('伏地魔', 1, 0, 0), Role('魔徒E12', 2, 0, 0)
        m.members = a.members = (1, 2)
        self.assertEqual(self.run_lead(m, a), [])

    def test_other_map_stops(self):
        m, a = Role('伏地魔', 1, 0, 0), Role('魔徒E12', 2, 0, 0, map_id=300)
        with self.assertRaises(bai_shi.t.Stop):
            self.run_lead(m, a)


class Restock(unittest.TestCase):
    def test_low_level_skipped(self):
        levels = {'a2': 2, 'a10': 10}
        roles = {n: NS(name=n, mem=n, world=lambda: NS(map_id=1)) for n in levels}
        gates, bought = [], []
        with mock.patch.object(r4_util, 'APPRENTICES', tuple(levels)), \
                mock.patch.object(r4_util.t, 'Client', lambda n: roles[n]), \
                mock.patch.object(r4_util.t, 'each', lambda names, fn: [fn(n) for n in names]), \
                mock.patch.object(r4_util.t, 'say', lambda s: None), \
                mock.patch.object(r4_util.w, 'read_level', lambda mem: levels[mem]), \
                mock.patch.object(r4_util.buy_scroll, 'count', lambda c: 0), \
                mock.patch.object(r4_util.buy_scroll, 'buy', lambda c, n: bought.append(c.name)), \
                mock.patch.object(r4_util, 'gate', lambda c, *a: gates.append(c.name)):
            r4_util.restock(20)
        self.assertEqual(bought, ['a10'])
        self.assertNotIn('a2', gates)


def page(*labels, text='x'):
    return NS(text=text, options=[(0, '离开')] + [(i + 1, l) for i, l in enumerate(labels)])


class OpenMenu(unittest.TestCase):
    def run_menu(self, reads):
        """reads: what app.dialog() returns, one per call (the last one repeats)."""
        log, said = [], []
        reads = list(reads)

        def dialog():
            return reads.pop(0) if len(reads) > 1 else reads[0]
        app = NS(name='魔徒E09', dialog=dialog,
                 game=NS(click_npc=lambda npc: log.append('click'), select_dialog=lambda o: log.append(('pick', o))))

        def wait(cond, timeout, what):
            v = cond()
            if not v:
                raise trial_run.Stop(what)
            return v
        with mock.patch.object(trial_run, 'wait', wait), \
                mock.patch.object(trial_run, 'say', said.append), \
                mock.patch.object(trial_run.time, 'sleep', lambda s: None), \
                mock.patch.object(trial_run, 'choose', lambda a, d, o, l: page('考验任务', '准备好了')):
            trial_run.open_menu(app)
        return log, said

    def test_second_click_gets_the_menu(self):
        log, said = self.run_menu([None, None, None, page('师徒任务')])
        self.assertEqual(log.count('click'), 2)
        self.assertTrue(any('再点一次' in s for s in said))

    def test_left_open_dialog_closed_and_logged(self):
        refusal = page(text='到自由市场需要级别不低于10级才可以！')
        refusal.options = [(1, '离开')]
        log, said = self.run_menu([refusal, page('师徒任务')])
        self.assertEqual(log[:2], [('pick', 0), 'click'])
        self.assertTrue(any('自由市场' in s for s in said))

    def test_gives_up_after_three_clicks(self):
        with self.assertRaises(trial_run.Stop):
            self.run_menu([None])


if __name__ == '__main__':
    unittest.main()
