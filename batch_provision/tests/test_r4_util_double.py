"""r4_util double-exp timing: stop_at picks the earliest due time; yam_due only counts apprentices with a 地瓜 who
already used the 3 小时 (round 5: team a's double ran out mid 通天塔二区 with yams in the bags)."""
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'shitu'))

import r4_util  # noqa: E402


class Double(unittest.TestCase):
    def test_stop_at(self):
        self.assertEqual(r4_util.stop_at(0, 0), 0)
        self.assertEqual(r4_util.stop_at(0, 50), 50)
        self.assertEqual(r4_util.stop_at(70, 50), 50)

    def test_yam_due(self):
        now = time.time()
        ends = {'x': now - 100, 'y': now + 900, 'z': now - 500}
        claimed = {'x': True, 'y': True, 'z': False}       # z still has the 3 小时 to claim: double_due's job
        yams = {'x': 2, 'y': 1, 'z': 3}
        with mock.patch.object(r4_util, 'APPRENTICES', ('x', 'y', 'z')), \
                mock.patch.object(r4_util, 'double_end', lambda n: ends[n]), \
                mock.patch('bai_shi.done', lambda n, k: claimed[n]), \
                mock.patch.object(r4_util.t, 'Client', lambda n: NS(mem=n)), \
                mock.patch.object(r4_util.w, 'read_bag', lambda mem: mem), \
                mock.patch.object(r4_util.w, 'item_count', lambda bag, item: yams[bag]):
            self.assertAlmostEqual(r4_util.yam_due(), now + 60, delta=2)     # x overdue -> in a minute
            yams['x'] = 0
            self.assertAlmostEqual(r4_util.yam_due(), now + 900, delta=2)    # x has no yam: y's end
            yams['y'] = 0
            self.assertEqual(r4_util.yam_due(), 0)


if __name__ == '__main__':
    unittest.main()
