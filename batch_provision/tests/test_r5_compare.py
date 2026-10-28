"""Unit tests for research/shitu/r5_compare.py (step durations from the v5 checkpoints)."""
import sys
import tempfile
import unittest
from pathlib import Path

SHITU = Path(__file__).resolve().parent.parent / 'research' / 'shitu'
sys.path.insert(0, str(SHITU))

import r5_compare as C  # noqa: E402


class StepTimes(unittest.TestCase):
    def test_durations_follow_the_checkpoints(self):
        ev = ['10-28 14:58:40 批次开始', '10-28 14:59:01 close_prev 完成', '10-28 15:00:12 make 完成（第 2 次）',
              '10-28 15:01:00 bai_shi 失败（rc=1），第 1 次重跑，先 leave', '10-28 15:02:00 bai_shi 完成']
        start = C.batch_start('x', ev)
        st = C.step_times(ev, start)
        self.assertEqual(st['close_prev'][1] - st['close_prev'][0], 21)
        self.assertEqual(st['make'][1] - st['make'][0], 71)
        self.assertEqual(st['bai_shi'][1] - st['bai_shi'][0], 108)
        self.assertEqual(C.retries(ev), 1)

    def test_start_from_controller_log(self):
        with tempfile.TemporaryDirectory() as d:
            logs = Path(d)
            (logs / 'line_run5.log').write_text('14:58:40 [a] 第 3 批开始: [...]\n14:59:40 [b] 第 3 批开始\n',
                                                encoding='utf-8')
            s = C.batch_start('r4b_b3', [], 'b', 3, logs)
            self.assertEqual(C.time.strftime('%H:%M:%S', C.time.localtime(s)), '14:59:40')
            self.assertIsNone(C.batch_start('r4c_b3', [], 'c', 3, logs))


if __name__ == '__main__':
    unittest.main()
