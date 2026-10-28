"""Unit tests for the 师徒 line v5 (research/shitu/line): plan, route rules, the runner's recovery ladder (no game)."""
import ast
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SHITU = Path(__file__).resolve().parent.parent / 'research' / 'shitu'
sys.path.insert(0, str(SHITU))

from line import plan, route as R  # noqa: E402
from line.runner import Runner  # noqa: E402


class Plan(unittest.TestCase):
    def r4_env(self, team, batch, skip=''):
        out = subprocess.run(['bash', '-c', f'BATCH={batch} SKIP="{skip}"; . ./r4_env.sh {team}; '
                              'echo "$SHITU_APPRENTICES|$PAIRS|$LOGID|$SHITU_MASTERS|$SHITU_GOLD|$SHITU_STATE"'],
                             cwd=SHITU, capture_output=True, text=True, encoding='utf-8').stdout.strip()
        return out.split('|')

    def test_agrees_with_r4_env(self):
        for team, batch, skip in [('a', 1, []), ('b', 2, []), ('d', 3, ['亿万13', '亿万48']), ('c', 4, ['亿万58'])]:
            e = plan.Batch(team, batch, skip).env()
            self.assertEqual(self.r4_env(team, batch, ' '.join(skip)),
                             [e['SHITU_APPRENTICES'], e['PAIRS'], e['LOGID'], e['SHITU_MASTERS'], e['SHITU_GOLD'],
                              e['SHITU_STATE']], (team, batch, skip))

    def test_skip_and_prev(self):
        self.assertEqual(plan.plan_skip('d', 3, ['亿万13']), ['亿万13', '亿万48'])
        b = plan.Batch('a', 3)
        self.assertEqual(b.prev_names, ['亿万17', '亿万18', '亿万19', '亿万20'])
        self.assertEqual(plan.Batch('a', 1).prev_names, [])


SCRIPTS_OK = {'U', 'ops'}


class Route(unittest.TestCase):
    def test_names_unique_and_old_from_names_kept(self):
        self.assertEqual(len(R.NAMES), len(set(R.NAMES)))
        for old in ['start', 'bazhen', 'cave', 'q224', 'snake', 'tower1', 'end', 'packs', 'tower2', 'q181', 'quan',
                    'wulong', 'tree', 'crystal', 'dew', 'pour', 'q183', 'corpse', 'king', 'fairy', 'chushi', 'finish']:
            self.assertIn(old, R.NAMES)
        stages = [s.stage for s in R.ROUTE]
        self.assertEqual(stages, sorted(stages, key=['make', 'early', 'mid', 'late'].index))

    def test_every_script_exists_and_nothing_runs_from_logs(self):
        for s in R.ROUTE:
            for c in s.cmds:
                head = c.args[0]
                if head not in SCRIPTS_OK:
                    self.assertTrue((SHITU / head).exists(), f'{s.name}: {head} missing')
                self.assertFalse(any('logs/' in a or 'logs\\' in a for a in c.args), f'{s.name}: runs from logs/')

    def test_ops_and_conditions_exist(self):
        src = (SHITU / 'line' / 'ops.py').read_text(encoding='utf-8')
        tree = ast.parse(src)
        main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
        ops = {k.value for d in ast.walk(main) if isinstance(d, ast.Dict) for k in d.keys} | {'when', 'level'}
        conds = {'lv_lt', 'lv_ge', 'master_on', 'kills5'}
        for s in R.ROUTE:
            if s.unless:
                self.assertIn(s.unless.split()[0], conds)
            for c in s.cmds:
                if c.args[0] == 'ops':
                    self.assertIn(c.args[1], ops, f'{s.name}: ops {c.args[1]}')
                if c.when:
                    self.assertIn(c.when.split()[0], conds)

    def test_no_regroup_before_going_home(self):
        """User 2026-10-28: 回城 breaks the team anyway, so a step part followed by home never regroups first."""
        for s in R.ROUTE:
            for i, c in enumerate(s.cmds):
                if c.args[0] == 'team_npc.py' and R.HOME in s.cmds[i + 1:]:
                    self.assertIn('--no-regroup', c.args, s.name)

    def test_late_quest_steps_end_with_a_gate(self):
        for s in R.ROUTE:
            if s.stage == 'late' and s.env.get('SHITU_QID') and s.name not in ('dew', 'fairy'):
                last_need = [c for c in s.cmds if c.args[:2] == ('U', 'need')]
                self.assertTrue(last_need, f'{s.name} has no `U need` gate')
                self.assertEqual(last_need[-1].args[2], s.env['SHITU_QID'], s.name)

    def test_quest_item_steps_free_bag_slots_first(self):
        """A full bag loses quest items silently (round 4): space before dew / king / corpse / tree pick-ups."""
        for name in ('tree', 'dew', 'corpse', 'king'):
            cmds = R.step(name).cmds
            self.assertEqual(cmds[0].args[:2], ('U', 'space'), name)

    def test_expand(self):
        b = plan.Batch('d', 3, ['亿万13', '亿万48'])
        self.assertEqual(R.expand(R.C('scorpion_king.py', '{A0}', '{M}', '{REST}'), b, python=()),
                         [['scorpion_king.py', '亿万45', '伏地魔4', '亿万46', '亿万47']])
        self.assertEqual(R.expand(R.C('dew_team.py', '{M}', '{APPS:0}'), b, python=()),
                         [['dew_team.py', '伏地魔4', '亿万45:0', '亿万46:0', '亿万47:0']])
        self.assertEqual(R.expand(R.C('take224.py', '{A}'), b, python=('py',)),
                         [['py', 'take224.py', '亿万45'], ['py', 'take224.py', '亿万46'], ['py', 'take224.py', '亿万47']])
        self.assertEqual(R.expand(R.C('U', 'need', '181', '3'), b, python=())[0], ['r4_util.py', 'need', '181', '3'])
        self.assertEqual(R.expand(R.C('ops', 'q94'), b, python=())[0], ['-m', 'line.ops', 'q94'])


class FakeGame:
    """Executor: answers each argv by the first matching rule (substring of the joined argv -> list of rcs, consumed
    one per call, the last one repeats). Records every call."""
    def __init__(self, rules=None, logs=None, short=None):
        self.rules = rules or {}
        self.calls = []
        self.logs, self.short = logs, short

    def __call__(self, argvs, env):
        rc = 0
        for a in argvs:
            line = ' '.join(a)
            self.calls.append((line, env['SHITU_APPRENTICES']))
            for k, rcs in self.rules.items():
                if k in line:
                    r = rcs.pop(0) if len(rcs) > 1 else rcs[0]
                    if r and self.short and 'need' in line:
                        (self.logs / f'{env["LOGID"]}_short.txt').write_text(self.short, encoding='utf-8')
                    rc = rc or r
                    break
        return rc


class Ladder(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.logs = Path(self.dir.name)
        self.sleeps = []

    def tearDown(self):
        self.dir.cleanup()

    def runner(self, game, batch=None, **kw):
        b = batch or plan.Batch('a', 3)
        return Runner(b, logs=self.logs, execute=game, sleep=self.sleeps.append, say=lambda m: None, **kw)

    def steps_run(self, game, name):
        return sum(1 for line, _ in game.calls if name in line)

    def test_clean_run_checkpoints_every_step(self):
        game = FakeGame({'when': [1]})                 # no condition holds: nothing skipped
        res = self.runner(game).run()
        self.assertTrue(res.ok)
        p = json.loads((self.logs / 'r4a_b3_line.json').read_text(encoding='utf-8'))
        self.assertEqual(p['done'], R.NAMES)
        self.assertEqual(self.sleeps, [])

    def test_resume_skips_done_steps(self):
        game = FakeGame({'when': [1], 'dts.py': [1]})
        r = self.runner(game, retries=0, recover_tries=0)
        self.assertFalse(r.run().ok)
        game2 = FakeGame({'when': [1]})
        self.assertTrue(self.runner(game2).run().ok)
        self.assertEqual(self.steps_run(game2, 'make_apprentices.py'), 0)
        self.assertEqual(self.steps_run(game2, 'dts.py'), 1)

    def test_unless_skips_leveling(self):
        game = FakeGame({'when lv_ge 25': [0], 'when': [1]})
        self.assertTrue(self.runner(game).run('bazhen', 'bazhen').ok)
        self.assertEqual(self.steps_run(game, 'bazhen25.py'), 0)

    def test_when_false_skips_cmd_soft_failure_goes_on(self):
        game = FakeGame({'when': [1], 'open_packs.py': [1]})
        self.assertTrue(self.runner(game).run('packs', 'packs').ok)
        self.assertEqual(self.steps_run(game, 'wear_best.py'), 1)
        game = FakeGame({'when': [1]})
        self.runner(game).run('cave', 'cave')
        self.assertEqual(self.steps_run(game, 'cave_train.py'), 0)

    def test_retry_ladder_then_park(self):
        game = FakeGame({'when': [1], 'dts.py': [1]})
        res = self.runner(game, retries=3, recover_tries=2, recover_wait=300).run('snake', 'snake')
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, 'STEP snake')
        self.assertEqual(self.steps_run(game, 'dts.py'), 6)            # 1 + 3 retries + 2 recoveries
        self.assertEqual(self.sleeps, [5, 5, 5, 300, 300])
        self.assertEqual(self.steps_run(game, 'r4_util.py leave'), 3)   # snake cleans up with leave
        self.assertEqual(self.steps_run(game, 'r4_util.py home'), 2)    # recoveries always go home

    def test_recovers_on_second_try(self):
        game = FakeGame({'when': [1], 'dts.py': [1, 0]})
        self.assertTrue(self.runner(game).run('snake', 'snake').ok)
        self.assertEqual(self.steps_run(game, 'dts.py'), 2)

    def test_gate_short_names_are_excluded_rest_continue(self):
        game = FakeGame({'when': [1], 'need 181 3': [1, 1, 1, 1, 1, 1, 0]}, logs=self.logs, short='亿万34')
        r = self.runner(game, retries=3, recover_tries=2)
        res = r.run('quan', 'wulong')
        self.assertTrue(res.ok)
        self.assertEqual(res.excluded, ('亿万34',))
        self.assertEqual(game.calls[-1][1], '亿万33,亿万35,亿万36')   # later steps without the excluded one
        p = json.loads((self.logs / 'r4a_b3_line.json').read_text(encoding='utf-8'))
        self.assertEqual(p['excluded'], ['亿万34'])
        r2 = self.runner(FakeGame({'when': [1]}))                      # a restart keeps the exclusion
        self.assertNotIn('亿万34', r2.b.apprentices)

    def test_master_down_parks_at_once(self):
        game = FakeGame({'when': [1], 'windows': [2]})
        res = self.runner(game).run('snake', 'snake')
        self.assertEqual(res.reason, 'MASTER_DOWN')
        self.assertEqual(self.steps_run(game, 'dts.py'), 0)

    def test_make_stage_checks_only_the_master(self):
        game = FakeGame({'when': [1]})
        self.runner(game).run('make', 'make')
        self.assertEqual(self.steps_run(game, 'master_up'), 1)
        self.assertEqual(self.steps_run(game, 'windows'), 0)

    def test_window_check_failing_waits_then_parks(self):
        game = FakeGame({'when': [1], 'windows': [1]})
        res = self.runner(game).run('snake', 'snake')
        self.assertEqual(res.reason, 'WINDOWS')
        self.assertEqual(self.sleeps, [60] * 10)


class Watchdog(unittest.TestCase):
    """runner.run_procs with real processes: exit codes, parallel runs, a silent process killed as hung."""
    def run_procs(self, codes, silent=30):
        from line.runner import run_procs
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / 'x.log'
            log.touch()
            return run_procs([[sys.executable, '-c', c] for c in codes], None, log, silent, poll=0.2),                 log.read_text(encoding='utf-8', errors='replace')

    def test_exit_codes(self):
        self.assertEqual(self.run_procs(['print(1)', 'print(2)'])[0], 0)
        self.assertEqual(self.run_procs(['print(1)', 'raise SystemExit(3)'])[0], 3)

    def test_silent_process_is_killed(self):
        rc, log = self.run_procs(['import time; time.sleep(60)'], silent=1)
        self.assertEqual(rc, -9)
        self.assertIn('判定卡死', log)


class Controller(unittest.TestCase):
    def test_next_batch_and_config(self):
        from line.__main__ import load_config, next_batch
        cfg = load_config()
        self.assertEqual(cfg['batches'], [3, 4])
        self.assertEqual(next_batch(cfg, {'done': [2]}), 3)
        self.assertEqual(next_batch(cfg, {'done': [3, 4]}), None)

    def test_dry_run_prints_every_step(self):
        out = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'line', '--dry-run', '--teams', 'd'], cwd=SHITU,
                             capture_output=True, text=True, encoding='utf-8').stdout
        for name in R.NAMES:
            self.assertIn(f'/{name}', out)


if __name__ == '__main__':
    unittest.main()
