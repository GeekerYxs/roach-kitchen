"""Unit tests for the decision logic of research/shitu/r4_line.py (no game needed)."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SHITU = Path(__file__).resolve().parent.parent / 'research' / 'shitu'
sys.path.insert(0, str(SHITU))

import r4_line  # noqa: E402


def write(path, *lines):
    Path(path).write_text('\n'.join(lines) + '\n', encoding='utf-8')


class Names(unittest.TestCase):
    def test_batch_names_follow_r4_env(self):
        self.assertEqual(r4_line.batch_names('a', 1), ['亿万1', '亿万2', '亿万3', '亿万4'])
        self.assertEqual(r4_line.batch_names('d', 2), ['亿万29', '亿万30', '亿万31', '亿万32'])
        self.assertEqual(r4_line.batch_names('c', 4), ['亿万57', '亿万58', '亿万59', '亿万60'])

    def test_stuck_apprentice_costs_a_slot(self):
        self.assertEqual(r4_line.plan_skip('a', 3, []), [])
        self.assertEqual(r4_line.plan_skip('d', 3, ['亿万13']), ['亿万13', '亿万48'])
        self.assertEqual(r4_line.plan_skip('d', 3, ['亿万13', '亿万31']), ['亿万13', '亿万31', '亿万47', '亿万48'])

    def test_logid(self):
        self.assertEqual(r4_line.logid('b', 1), 'r4b')
        self.assertEqual(r4_line.logid('b', 3), 'r4b_b3')


class Outcome(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.log = Path(self.dir.name) / 'sup.log'

    def tearDown(self):
        self.dir.cleanup()

    def test_missing_log(self):
        self.assertEqual(r4_line.outcome(self.log), (None, None, None))

    def test_done(self):
        write(self.log, '05:13:04 start r4_mid.sh FROM=start', '05:20:33 done r4_late.sh')
        self.assertEqual(r4_line.outcome(self.log)[0], 'done')

    def test_giveup(self):
        write(self.log, '04:24:26 r4_late.sh stopped in step q183 (try 4): x', '04:24:27 SUP_GIVEUP r4_late.sh q183')
        self.assertEqual(r4_line.outcome(self.log), ('giveup', 'r4_late.sh', 'q183'))

    def test_restart_after_giveup_is_running(self):
        write(self.log, '04:24:27 SUP_GIVEUP r4_late.sh q183', '04:25:14 start r4_late.sh FROM=q183')
        self.assertEqual(r4_line.outcome(self.log)[0], 'running')

    def test_make_giveup(self):
        write(self.log, '05:21:01 batch 2 team b: cap25:亿万21', '05:22:00 SUP_GIVEUP make -')
        self.assertEqual(r4_line.outcome(self.log), ('giveup', 'make', '-'))

    def test_master_down(self):
        write(self.log, '06:00:00 SUP_GIVEUP r4_mid.sh MASTER_DOWN')
        self.assertEqual(r4_line.outcome(self.log), ('giveup', 'r4_mid.sh', 'MASTER_DOWN'))


class Resume(unittest.TestCase):
    def test_resume_args(self):
        self.assertEqual(r4_line.resume_args('r4_early.sh', 'x'), ['early'])
        self.assertEqual(r4_line.resume_args('r4_mid.sh', 'tower1'), ['tower1'])
        self.assertEqual(r4_line.resume_args('r4_late.sh', 'king'), ['late', 'king'])

    def test_last_step_takes_newest_stage_log(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            write(d / 'r4a_b3_r4_mid.log', '== STEP start 01:00:00', '== STEP tower2 02:00:00')
            write(d / 'r4a_b3_r4_late.log', '== STEP q181 03:00:00', '== STEP quan 03:10:00')
            old = time.time() - 100
            os.utime(d / 'r4a_b3_r4_mid.log', (old, old))
            self.assertEqual(r4_line.last_step(d, 'r4a_b3'), ('r4_late.sh', 'quan'))
            self.assertEqual(r4_line.last_step(d, 'r4z'), ('r4_early.sh', 'start'))


class Env(unittest.TestCase):
    """r4_env.sh: SKIP and the account pairs (bash)."""
    def env(self, team, batch, skip=''):
        out = subprocess.run(['bash', '-c', f'BATCH={batch} SKIP="{skip}"; . ./r4_env.sh {team}; '
                              'echo "$SHITU_APPRENTICES|$PAIRS|$LOGID"'], cwd=SHITU, capture_output=True,
                             text=True, encoding='utf-8').stdout.strip()
        return out.split('|')

    def test_pairs_follow_slots(self):
        self.assertEqual(self.env('a', 3), ['亿万33,亿万34,亿万35,亿万36',
                                            'cap21:亿万33 cap22:亿万34 cap23:亿万35 cap24:亿万36', 'r4a_b3'])

    def test_skip_keeps_account_of_each_slot(self):
        self.assertEqual(self.env('d', 2, '亿万13 亿万30'), ['亿万29,亿万31,亿万32',
                                                          'cap33:亿万29 cap35:亿万31 cap36:亿万32', 'r4d_b2'])


if __name__ == '__main__':
    unittest.main()
