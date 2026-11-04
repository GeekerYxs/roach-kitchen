"""trial_run.each (user 2026-11-01): what each apprentice does for itself runs for all at once; only steps that need
the master or a trade (拜师, 师徒考验, 出师, 补给, 交金币) stay one after another."""
import ast
import sys
import threading
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent / 'research' / 'shitu'
sys.path.insert(0, str(HERE))

import trial_run as t  # noqa: E402


class Each(unittest.TestCase):
    def test_all_at_once(self):
        live, peak, lock, seen = [0], [0], threading.Lock(), []

        def fn(n):
            with lock:
                live[0] += 1
                peak[0] = max(peak[0], live[0])
            time.sleep(0.2)
            with lock:
                live[0] -= 1
                seen.append(n)
        start = time.monotonic()
        t.each(['a', 'b', 'c', 'd'], fn)
        self.assertLess(time.monotonic() - start, 0.6)
        self.assertEqual((peak[0], sorted(seen)), (4, ['a', 'b', 'c', 'd']))

    def test_everybody_finishes_then_the_error(self):
        done = []

        def fn(n):
            if n == 'a':
                raise t.Stop('a 没有对话框')
            time.sleep(0.1)
            done.append(n)
        with self.assertRaises(t.Stop):
            t.each(['a', 'b', 'c'], fn)
        self.assertEqual(sorted(done), ['b', 'c'])

    def test_system_exit_also_fails(self):
        def fn(n):
            raise SystemExit(1)
        with self.assertRaises(SystemExit):
            t.each(['a'], fn)


PARALLEL = {        # file -> the code that must run through t.each
    'yongzhe_take.py': 't.each(sys.argv[1:], take)',
    'drop_prank.py': 't.each(args,', 'eat_items.py': 't.each(args,', 'open_packs.py': 't.each(sys.argv[1:],',
    'wear_best.py': 't.each(names,', 'mail_sell.py': 't.each(args,', 'sell_tradable.py': 't.each(names,',
    'pp_unlock.py': 't.each([n for n in names',
}
SERIAL = ('bai_shi.py', 'trial_run.py', 'trial3_run.py', 'chushi.py', 'give_gold.py')   # the master / a trade


class Scripts(unittest.TestCase):
    def test_own_business_is_parallel(self):
        for f, code in PARALLEL.items():
            self.assertIn(code, (HERE / f).read_text(encoding='utf-8'), f)

    def test_r4_util_and_ops_loops(self):
        for f, funcs in (('r4_util.py', ('restock', 'double', 'space', 'home')),
                         ('line/ops.py', ('q94', 'fairy'))):
            tree = ast.parse((HERE / f).read_text(encoding='utf-8'))
            defs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
            for name in funcs:
                src = ast.unparse(defs[name])
                self.assertIn('t.each(', src, f'{f} {name}')
                top_for = [n for n in defs[name].body if isinstance(n, ast.For)]
                self.assertFalse(any('APPRENTICES' in ast.unparse(n.iter) for n in top_for), f'{f} {name}')

    def test_home_village_apprentices_before_the_master(self):
        """91e7959: a scroll-less apprentice borrows from the master on its map (a trade), so they go one by one and
        the master last."""
        src = (HERE / 'line' / 'ops.py').read_text(encoding='utf-8')
        body = src[src.index('def home_village'):src.index('def q94')]
        self.assertLess(body.index('for c in cs[1:]:'), body.index('one(cs[0])'))

    def test_master_bound_steps_stay_serial(self):
        for f in SERIAL:
            if (HERE / f).exists():
                self.assertNotIn('t.each(', (HERE / f).read_text(encoding='utf-8'), f)


if __name__ == '__main__':
    unittest.main()
