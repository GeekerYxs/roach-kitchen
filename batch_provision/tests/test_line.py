"""Unit tests for the 师徒 line v5 (research/shitu/line): plan, route rules, the runner's recovery ladder (no game)."""
import ast
import json
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

SHITU = Path(__file__).resolve().parent.parent / 'research' / 'shitu'
sys.path.insert(0, str(SHITU))

from line import plan, route as R  # noqa: E402
from line.runner import Result, Runner  # noqa: E402


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

    def test_teams_from_config(self):
        self.assertEqual(plan.TEAMS['fei'].master, '飞天把你射成蜂窝')
        self.assertEqual(plan.TEAMS['tian'].master, '舔尊')
        b = plan.Batch('fei', 3)                       # slot 2 = team c's accounts and names, its own LOGID
        self.assertEqual(b.apprentices, ['亿万41', '亿万42', '亿万43', '亿万44'])
        self.assertEqual(b.pairs[0], 'cap29:亿万41')
        self.assertEqual(b.prev_names, ['亿万25', '亿万26', '亿万27', '亿万28'])
        self.assertEqual(b.env()['SHITU_MASTERS'], '飞天把你射成蜂窝')
        self.assertEqual(b.env()['SHITU_GOLD'], '50000')
        self.assertEqual(b.logid, 'r4fei_b3')
        self.assertEqual(plan.Batch('tian', 3).pairs[-1], 'cap36:亿万48')

    def test_check_teams(self):
        plan.check_teams(['a', 'b', 'fei', 'tian'])
        with self.assertRaises(ValueError):
            plan.check_teams(['c', 'fei'])                 # same accounts
        with self.assertRaises(ValueError):
            plan.check_teams(['a', 'zz'])                  # unknown team
        T = plan.Team
        with self.assertRaises(ValueError):
            plan.check_teams(['x', 'y'], {'x': T('m', 0, 1), 'y': T('m', 1, 1)})   # one master twice

    def test_load_teams_rejects_bad_slot(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'l.toml'
            p.write_text('[team.x]\nmaster = "m"\nslot = 4\n', encoding='utf-8')
            with self.assertRaises(ValueError):
                plan.load_teams(p)
            p.write_text('[team.x]\nmaster = "m"\nslot = 1\n', encoding='utf-8')
            self.assertEqual(plan.load_teams(p)['x'], plan.Team('m', 1, 50000))

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
        for s in R.ROUTE + R.ROUTE_BPLUS:
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
        conds = {'lv_lt', 'lv_ge', 'exp_ge', 'lacks', 'master_on', 'master_off', 'kills5'}
        for s in R.ROUTE + R.ROUTE_BPLUS:
            if s.unless:
                self.assertIn(s.unless.split()[0], conds)
            for c in s.cmds:
                if c.args[0] == 'ops':
                    self.assertIn(c.args[1], ops, f'{s.name}: ops {c.args[1]}')
                if c.when:
                    self.assertIn(c.when.split()[0], conds)

    def test_no_regroup_before_going_home(self):
        """User 2026-10-28: 回城 breaks the team anyway, so a step part followed by home never regroups first."""
        for s in R.ROUTE + R.ROUTE_BPLUS:
            for i, c in enumerate(s.cmds):
                if c.args[0] == 'team_npc.py' and R.HOME in s.cmds[i + 1:]:
                    self.assertIn('--no-regroup', c.args, s.name)

    def test_late_quest_steps_end_with_a_gate(self):
        for s in R.ROUTE + R.ROUTE_BPLUS:
            if s.stage == 'late' and s.env.get('SHITU_QID') and s.name not in ('dew', 'fairy'):
                last_need = [c for c in s.cmds if c.args[:2] == ('U', 'need')]
                self.assertTrue(last_need, f'{s.name} has no `U need` gate')
                self.assertEqual(last_need[-1].args[2], s.env['SHITU_QID'], s.name)

    def test_quest_item_steps_free_bag_slots_first(self):
        """A full bag loses quest items silently (round 4): space before dew / king / corpse / tree pick-ups."""
        for name in ('tree', 'dew', 'corpse', 'king', 'crystal', 'pour'):
            cmds = R.step(name).cmds
            self.assertEqual(cmds[0].args[:2], ('U', 'space'), name)

    def test_relogs_accept_any_map_new_roles_do_not(self):
        """2026-10-29 亿万60 relogged fine in map 1000 but make_apprentices called it a failure (only 逍遥村 = ok)."""
        self.assertNotIn('--anywhere', R.step('make').cmds[0].args)
        src = (SHITU / 'r4_util.py').read_text(encoding='utf-8')
        self.assertIn("'make_apprentices.py', '--anywhere'", src)

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
        self.assertEqual(p['done'], [s.name for s in R.route_of(plan.Batch('a', 3))])   # B+ since 2026-10-30
        self.assertEqual(self.sleeps, [])

    def test_step_marker_and_batch_start_event(self):
        """Round 5: `self.execute is self._execute` never held, the `== STEP` markers were never written."""
        r = Runner(plan.Batch('a', 3), logs=self.logs, say=lambda m: None)
        r.stage_log = 'line_make'
        r._marker(R.step('make'))
        self.assertIn('== STEP make ', (self.logs / 'r4a_b3_line_make.log').read_text(encoding='utf-8'))
        self.runner(FakeGame({'when': [1]})).run('snake', 'snake')     # a FROM run is no batch start
        self.assertNotIn('批次开始', (self.logs / 'r4a_b3_line.json').read_text(encoding='utf-8'))
        (self.logs / 'r4a_b3_line.json').unlink()
        self.runner(FakeGame({'when': [1]})).run()
        ev = json.loads((self.logs / 'r4a_b3_line.json').read_text(encoding='utf-8'))['events']
        self.assertTrue(ev[0].endswith(' 批次开始'))

    def test_resume_skips_done_steps(self):
        game = FakeGame({'when': [1], 'dts.py': [1]})
        r = self.runner(game, retries=0, recover_tries=0)
        self.assertFalse(r.run().ok)
        game2 = FakeGame({'when': [1]})
        self.assertTrue(self.runner(game2).run().ok)
        self.assertEqual(self.steps_run(game2, 'make_apprentices.py'), 0)
        self.assertEqual(self.steps_run(game2, 'dts.py'), 1)

    def test_unless_skips_leveling(self):
        game = FakeGame({'when lv_ge 23': [0], 'when': [1]})                  # B+: 八阵图 left at 23
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
        self.assertEqual(self.steps_run(game, 'r4_util.py relog cap21:亿万33'), 2)   # ... after relogging everybody

    def test_snake_redoes_the_trip_only_when_not_there(self):
        on_20 = FakeGame({'master_off 20 750': [1], 'master_on 20': [0], 'when': [1]})    # normal: at 无尽2路口
        self.assertTrue(self.runner(on_20).run('snake', 'snake').ok)
        self.assertEqual(self.steps_run(on_20, 'r4_util.py home'), 0)
        self.assertEqual(self.steps_run(on_20, 'pp_chain.py'), 0)
        home = FakeGame({'master_off 20 750': [0], 'master_on 1': [0], 'master_on 20': [0], 'when': [1]})
        self.assertTrue(self.runner(home).run('snake', 'snake').ok)
        for s in ('r4_util.py home', 'pp_chain.py', 'take224.py', 'go_cave.py'):
            self.assertGreaterEqual(self.steps_run(home, s), 1, s)

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

    def test_master_down_parks_when_relog_fails(self):
        game = FakeGame({'when': [1], 'windows': [2], 'master_login.py': [1]})
        res = self.runner(game).run('snake', 'snake')
        self.assertEqual(res.reason, 'MASTER_DOWN')
        self.assertEqual(self.steps_run(game, 'dts.py'), 0)
        self.assertEqual(self.steps_run(game, 'master_login.py 伏地魔1'), 1)

    def test_master_down_relogs_then_goes_on(self):
        """Round 6: the master drops -> master_login.py, everybody home, the step runs (no parking)."""
        game = FakeGame({'when': [1], 'windows': [2, 0]})
        res = self.runner(game).run('snake', 'snake')
        self.assertTrue(res.ok)
        self.assertEqual(self.steps_run(game, 'master_login.py'), 1)
        self.assertEqual(self.steps_run(game, 'r4_util.py home'), 1)
        self.assertEqual(self.steps_run(game, 'dts.py'), 1)

    def test_master_relogs_are_capped(self):
        game = FakeGame({'when': [1], 'windows': [2]})            # relog "works" but the master never stays up
        res = self.runner(game, master_relogs=3).run('snake', 'snake')
        self.assertEqual(res.reason, 'MASTER_DOWN')
        self.assertEqual(self.steps_run(game, 'master_login.py'), 3)

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


class Tower1Target(unittest.TestCase):
    def test_team_tower1_in_cmd_and_unless(self):
        cmd = next(c for c in R.step('tower1').cmds if c.args[0] == 'tower28.py')
        b = plan.Batch('b', 4)
        self.assertEqual(R.expand(cmd, b, python=())[0], ['tower28.py', str(plan.TEAMS['b'].tower1)])
        calls = []
        r = Runner(b, logs=tempfile.mkdtemp(), execute=lambda a, e: calls.append(' '.join(a[0])) or 0,
                   sleep=lambda s: None, say=lambda m: None)
        r.check(R.step('tower1').unless, R.step('tower1'))
        self.assertTrue(calls[-1].endswith(f'when lv_ge {b.tower1}'))
        self.assertEqual(plan.Team('m', 0, 1).tower1, 35)             # user 2026-10-30: every team to 35 for now


class OwnAccountsAndLevels(unittest.TestCase):
    """2026-10-29 exp-map trial: teams with their own accounts / name prefix and their own map-leaving levels."""
    def load(self, text):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'l.toml'
            p.write_text(text, encoding='utf-8')
            return plan.load_teams(p)

    def test_accounts_and_names(self):
        teams = self.load('[team.x]\nmaster = "m"\naccounts = 37\nnames = "Opus55A"\n')
        with unittest.mock.patch.object(plan, 'TEAMS', teams):
            b = plan.Batch('x', 1)
            self.assertEqual(b.pairs, ['cap37:Opus55A1', 'cap38:Opus55A2', 'cap39:Opus55A3', 'cap40:Opus55A4'])
            self.assertEqual(plan.Batch('x', 2).all_names[0], 'Opus55A5')
            self.assertEqual(b.logid, 'r4x')

    def test_bad_names_and_half_config_rejected(self):
        for text in ('[team.x]\nmaster = "m"\naccounts = 37\nnames = "Opus5.5"\n',        # '.' is not alnum
                     '[team.x]\nmaster = "m"\naccounts = 37\nnames = "一二三四五六七"\n',  # 14 bytes + '16' > 15
                     '[team.x]\nmaster = "m"\naccounts = 37\n',
                     '[team.x]\nmaster = "m"\nslot = 1\nlevels = { tower = 30 }\n',
                     '[team.x]\nmaster = "m"\nslot = 1\nlevels = { cave = 27 }\n'):     # 任务 224 needs 28
            with self.assertRaises(ValueError, msg=text):
                self.load(text)

    def test_overlapping_accounts_rejected(self):
        T = plan.Team
        teams = {'x': T('m1', 0, 1, accounts=37, names='A'), 'y': T('m2', 0, 1, accounts=39, names='B'),
                 'z': T('m3', 0, 1, accounts=41, names='C'), 'old': T('m4', 3, 1)}
        plan.check_teams(['x', 'z', 'old'], teams)
        with self.assertRaises(ValueError):
            plan.check_teams(['x', 'y'], teams)
        with self.assertRaises(ValueError):                                     # cap33-36 vs cap35-38
            plan.check_teams(['old', 'w'], dict(teams, w=T('m5', 0, 1, accounts=35, names='D')))

    def test_levels_default_to_the_route(self):
        t = plan.Team('m', 0, 1)                                        # B+ is the default since 2026-10-30
        self.assertEqual([t.level(k) for k in plan.LEVELS], [12, 16, 23, 23, 28])
        self.assertEqual((t.route, t.tower2), ('bplus', '39+125000'))
        t = plan.Team('m', 0, 1, route='v5')
        self.assertEqual([t.level(k) for k in plan.LEVELS], [15, 19, 23, 25, 28])
        self.assertEqual(t.tower2, '40')
        t = plan.Team('m', 0, 1, levels=(('cave', 27), ('lunhui', 12)), route='v5')
        self.assertEqual((t.level('lunhui'), t.level('maze1'), t.level('cave')), (12, 19, 27))

    def test_route_tokens_and_conditions(self):
        teams = {'g': plan.Team('m', 0, 1, 34, 41, 'Opus55B', (('bazhen', 23), ('cave', 27), ('lunhui', 12),
                                                               ('maze1', 16), ('maze2', 23)))}
        with unittest.mock.patch.object(plan, 'TEAMS', teams):
            b = plan.Batch('g', 1)

            def argv(name, script):
                return next(R.expand(c, b, python=()) for c in R.step(name).cmds if c.args[0] == script)[0]
            self.assertEqual(argv('lunhui', 'lunhui15.py'), ['lunhui15.py', '12'])
            self.assertEqual(argv('maze', 'maze_train.py'), ['maze_train.py', '16', '23'])
            self.assertEqual(argv('bazhen', 'bazhen25.py'), ['bazhen25.py', '23'])
            self.assertEqual(argv('cave', 'cave_train.py'), ['cave_train.py', '27'])
            self.assertEqual(argv('tower1', 'tower28.py'), ['tower28.py', '34'])
            self.assertEqual(R.fill(R.step('bazhen').unless, b), 'lv_ge 23')
            cave = next(c for c in R.step('cave').cmds if c.args[0] == 'cave_train.py')
            self.assertEqual(R.fill(cave.when, b), 'lv_lt 27')
            calls = []
            r = Runner(b, logs=tempfile.mkdtemp(), execute=lambda a, e: calls.append(' '.join(a[0])) or 0,
                       sleep=lambda s: None, say=lambda m: None)
            r.check(R.step('lunhui').unless, R.step('lunhui'))
            self.assertTrue(calls[-1].endswith('when lv_ge 12'))

    def test_v5_teams_keep_their_levels(self):
        b = plan.Batch('oa', 1)                                                 # route = "v5", no levels
        self.assertEqual(R.expand(R.step('maze').cmds[0], b, python=())[0], ['maze_train.py', '19', '23'])
        self.assertEqual(R.fill(R.step('bazhen').unless, b), 'lv_ge 25')

    def test_trial_teams_in_config(self):
        plan.check_teams(['oa', 'ob', 'oc'])
        self.assertEqual(plan.Batch('ob', 1).pairs[0], 'cap41:Opus55B1')


class ParkRetry(unittest.TestCase):
    """Round 6: a parked team waits park_wait and resumes from its checkpoint by itself, park_retries times."""
    def setUp(self):
        from line import __main__ as M
        self.M = M
        self.dir = tempfile.TemporaryDirectory()
        logs = Path(self.dir.name)
        self.patches = [unittest.mock.patch.object(M, 'STATE', logs / 'state.json'),
                        unittest.mock.patch.object(M, 'ALERT', logs / 'alert.log'),
                        unittest.mock.patch.object(M, 'STOP', logs / 'STOP'),
                        unittest.mock.patch.object(M, 'LOGS', logs),
                        unittest.mock.patch.object(M, 'quizbot_running', lambda: True)]
        for x in self.patches:
            x.start()

    def tearDown(self):
        for x in self.patches:
            x.stop()
        self.dir.cleanup()

    def team(self, results):
        M, it = self.M, iter(results)

        class FakeRunner:
            def __init__(self, b, **kw):
                self.b = b

            def run(self):
                return next(it)
        cfg = dict(M.load_config(), teams=['a'], batches=[4], park_retries=2, park_wait=600)
        sleeps = []
        return M.Team('a', cfg, runner=FakeRunner, sleep=sleeps.append), sleeps

    def test_resumes_after_a_park(self):
        team, sleeps = self.team([Result(False, 'STEP snake'), Result(True, 'done')])
        team.line()
        self.assertEqual(sleeps, [600])
        self.assertIn(4, team.data['done'])
        self.assertFalse(team.data['parked'])

    def test_gives_up_after_park_retries(self):
        team, sleeps = self.team([Result(False, 'STEP snake')] * 5)
        team.line()
        self.assertEqual(sleeps, [600, 600])
        self.assertTrue(team.data['parked'])
        self.assertNotIn(4, team.data['done'])


class ReloadBatches(unittest.TestCase):
    def test_batches_added_while_running_are_picked_up(self):
        import line.__main__ as M
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'l.toml'
            p.write_text('batches = [1]\n', encoding='utf-8')
            cfg = dict(M.load_config(), teams=['a'], batches=[1], reload=p)
            ran = []

            class FakeRunner:
                def __init__(self, b, **kw):
                    self.b = b

                def run(self):
                    ran.append(self.b.batch)
                    if self.b.batch == 1:               # the user extends the line while batch 1 runs
                        p.write_text('batches = [1, 2]\n', encoding='utf-8')
                    return Result(True)
            patch = unittest.mock.patch.object
            with patch(M, 'load_state', lambda: {}), patch(M, 'save_team', lambda *a: None), \
                    patch(M, 'quizbot_running', lambda: True), patch(M, 'say', lambda m: None):
                M.Team('a', cfg, runner=FakeRunner).line()
            self.assertEqual(ran, [1, 2])


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
        self.assertEqual(next_batch(dict(cfg, batches=[3, 4]), {'done': [2]}), 3)
        self.assertEqual(next_batch(dict(cfg, batches=[3, 4]), {'done': [3, 4]}), None)
        self.assertIn('park_retries', cfg)

    def test_quizbot_one_bad_read_is_not_an_alert(self):
        from line import __main__ as M
        reads = iter(['', '"启动答题器.exe","13356"'])
        with unittest.mock.patch.object(M.time, 'sleep'):
            self.assertTrue(M.quizbot_running(list_procs=lambda: next(reads)))
            self.assertFalse(M.quizbot_running(list_procs=lambda: 'python.exe'))

    def test_dry_run_prints_every_step(self):
        out = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'line', '--dry-run', '--teams', 'd'], cwd=SHITU,
                             capture_output=True, text=True, encoding='utf-8').stdout
        for name in (s.name for s in R.ROUTE_BPLUS):                         # team d: B+ (default)
            self.assertIn(f'/{name}', out)


class BPlus(unittest.TestCase):
    """Route B+ (2026-10-30): no 23 trip home, all three 考验 at the tower1 -> tower2 visit, 二区 to L+E, top-up."""
    def test_steps(self):
        names = [s.name for s in R.ROUTE_BPLUS]
        self.assertNotIn('start', names)
        self.assertEqual(names[names.index('king') + 1:], ['topup', 'fairy', 'chushi', 'finish'])
        end = [c.args[0] for c in dict(zip(names, R.ROUTE_BPLUS))['end'].cmds]
        self.assertLess(end.index('trial_run.py'), end.index('trial3_run.py'))
        self.assertEqual(R.route_of(plan.Batch('a', 1)), R.ROUTE_BPLUS)    # default since 2026-10-30
        self.assertEqual(R.route_of(plan.Batch('oa', 1)), R.ROUTE)         # the exp-map trial teams stay on v5

    def test_team_bp(self):
        t = plan.TEAMS['bp']
        self.assertEqual((t.master, t.route, t.tower2, t.level('maze2'), t.level('bazhen')),
                         ('伏地魔2', 'bplus', '38+200000', 24, 24))
        b = plan.Batch('bp', 1)
        self.assertEqual(b.pairs[0], 'gm2g01t01u01:Opus55D1')
        self.assertEqual(R.route_of(b), R.ROUTE_BPLUS)
        tw = dict((s.name, s) for s in R.ROUTE_BPLUS)['tower2']
        self.assertEqual(R.fill(tw.unless, b), 'exp_ge 38+200000')
        self.assertEqual(R.expand(tw.cmds[-1], b, python=()), [['tower2_patrol.py', '38+200000']])
        plan.check_teams(['bp', 'oa', 'ob', 'oc'])

    def test_bad_values_rejected(self):
        bad = ('accounts = ["x1", "x2"]\nnames = "N"', 'accounts = 37\nnames = "N"\nroute = "zz"',
               'accounts = 37\nnames = "N"\ntower2 = "38-1"')
        for extra in bad:
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / 'l.toml'
                p.write_text(f'[team.x]\nmaster = "m"\n{extra}\n', encoding='utf-8')
                with self.assertRaises(ValueError, msg=extra):
                    plan.load_teams(p)

    def test_team_batches_win(self):
        from line.__main__ import next_batch
        cfg = {'batches': [1, 2, 3], 'team': {'bp': {'batches': [1]}}}
        self.assertEqual(next_batch(cfg, {'done': []}, 'bp'), 1)
        self.assertIsNone(next_batch(cfg, {'done': [1]}, 'bp'))
        self.assertEqual(next_batch(cfg, {'done': [1]}, 'oa'), 2)

    def test_reached(self):
        from line import ops
        mem = unittest.mock.Mock()
        for lv, exp, want in ((38, 199999, False), (38, 200000, True), (39, 0, True), (37, 900000, False)):
            with unittest.mock.patch.object(ops.w, 'read_level', return_value=lv), \
                    unittest.mock.patch.object(ops, 'read_exp', return_value=exp):
                self.assertEqual(ops.reached(mem, 38, 200000), want, (lv, exp))


if __name__ == '__main__':
    unittest.main()
