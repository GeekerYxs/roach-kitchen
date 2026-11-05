"""r4_util.close_dialogs (user 2026-11-05): a dialog left open stops walking / scrolling, so home(), leave() (the
cleanup before an in-place rerun) and ops.home_village close every open dialog first."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

HERE = Path(__file__).resolve().parent.parent / 'research' / 'shitu'
sys.path.insert(0, str(HERE))

import r4_util  # noqa: E402


class Close(unittest.TestCase):
    def test_only_open_ones_and_errors_do_not_stop(self):
        picked = []
        cs = [NS(name='a', dialog=lambda: 'dlg', game=NS(select_dialog=lambda o: picked.append(('a', o)))),
              NS(name='b', dialog=lambda: None, game=NS(select_dialog=lambda o: picked.append(('b', o)))),
              NS(name='c', dialog=mock.Mock(side_effect=AttributeError('offline')), game=NS(select_dialog=None))]
        with mock.patch.object(r4_util.t, 'say', lambda s: None):
            r4_util.close_dialogs(cs)
        self.assertEqual(picked, [('a', 0)])

    def test_wired(self):
        src = (HERE / 'r4_util.py').read_text(encoding='utf-8')
        for fn in ('def home():', 'def leave('):
            body = src[src.index(fn):]
            self.assertLess(body.index('close_dialogs(cs)'), body.index('team_leave()'), fn)
        ops = (HERE / 'line' / 'ops.py').read_text(encoding='utf-8')
        self.assertIn('close_dialogs(cs)', ops[ops.index('def home_village'):ops.index('def q94')])


if __name__ == '__main__':
    unittest.main()
