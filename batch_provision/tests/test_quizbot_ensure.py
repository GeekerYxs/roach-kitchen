"""provisioner.quizbot (user 2026-11-05): every line checks 启动答题器 at start and launches it when missing; one per
computer serves them all, and it is never started twice (a start kills the running one first)."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from provisioner import quizbot  # noqa: E402


class Ensure(unittest.TestCase):
    def run_ensure(self, procs_after_launch, up_at_start=False):
        procs = {'explorer.exe'} | ({'启动答题器.exe'} if up_at_start else set())
        launched, said = [], []

        def launch():
            launched.append(1)
            procs.update(procs_after_launch)
        with tempfile.TemporaryDirectory() as d:
            r = quizbot.ensure(say=said.append, list_names=lambda: set(procs), launch=launch, sleep=lambda s: None,
                               wait=3, lock=quizbot._Lock(Path(d) / 'q.lock'))
        return r, launched, said

    def test_running_is_left_alone(self):
        self.assertEqual(self.run_ensure(set(), up_at_start=True), ('running', [], []))

    def test_missing_is_started_once(self):
        r, launched, said = self.run_ensure({'启动答题器.exe'})
        self.assertEqual((r, launched), ('started', [1]))
        self.assertIn('自动启动', said[0])

    def test_never_seen_after_launch(self):
        r, launched, said = self.run_ensure(set())
        self.assertEqual((r, launched), ('failed', [1]))
        self.assertIn('管理员', said[0])

    def test_launch_error(self):
        def boom():
            raise FileNotFoundError('x')
        with tempfile.TemporaryDirectory() as d:
            r = quizbot.ensure(say=lambda s: None, list_names=lambda: set(), launch=boom, sleep=lambda s: None,
                               lock=quizbot._Lock(Path(d) / 'q.lock'))
        self.assertEqual(r, 'failed')

    def test_folder_and_names(self):
        self.assertEqual(quizbot.DIR.name, '大冒险2_自动答题器_原生无感关窗版')
        self.assertTrue((quizbot.DIR / quizbot.EXE).exists())


class Wired(unittest.TestCase):
    def test_every_line_ensures_it(self):
        for f in ('research/shitu/line/__main__.py', 'factory/supervisor.py',
                  'projects/fullcrit_mage_leveling_70/run_level_to_70.py', '../抓宠一级宝宝/runner.py'):
            src = (ROOT / f).read_text(encoding='utf-8')
            self.assertTrue('quizbot.ensure(' in src, f)


if __name__ == '__main__':
    unittest.main()
