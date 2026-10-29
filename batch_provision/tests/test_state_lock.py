"""bai_shi.mark from parallel processes: no lost marks, no half-written file (round 6, 23:42 JSONDecodeError)."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SHITU = Path(__file__).resolve().parent.parent / 'research' / 'shitu'
sys.path.insert(0, str(SHITU))

import bai_shi  # noqa: E402

CHILD = '''
import sys
sys.path.insert(0, {shitu!r})
from pathlib import Path
import bai_shi
for i in range(15):
    bai_shi.mark(sys.argv[1], f"s{{i}}", path=Path({path!r}))
    bai_shi.load_state(Path({path!r}))
'''


class StateLock(unittest.TestCase):
    def test_parallel_marks_all_kept(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'state.json'
            code = CHILD.format(shitu=str(SHITU), path=str(path))
            procs = [subprocess.Popen([sys.executable, '-c', code, f'n{k}']) for k in range(6)]
            self.assertEqual([p.wait(60) for p in procs], [0] * 6)
            s = bai_shi.load_state(path)
            self.assertEqual(sorted(s), [f'n{k}' for k in range(6)])
            self.assertTrue(all(len(v) == 15 for v in s.values()))
            self.assertFalse(list(Path(d).glob('*.lock')) + list(Path(d).glob('*.tmp')))


if __name__ == '__main__':
    unittest.main()
