"""Created roles' look and names (user 2026-11-05: 元素使 batch 3 are 女, like the user's hand-made 魔法师09)."""
import struct
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'shitu'))

from provisioner import protocol  # noqa: E402


class Look(unittest.TestCase):
    def body(self, look=None):
        with mock.patch.object(protocol, '_session_body', return_value=bytearray(protocol.CREATE_BODY_SIZE)):
            args = (None, None, 'yss10', '魔法师10') + ((look,) if look else ())
            return protocol.build_create(*args)

    def test_default_is_the_old_male_sample(self):
        b = self.body()
        self.assertEqual(struct.unpack_from('<II', b, 265) + tuple(b[273:275]), (3, 0, 1, 0))

    def test_female_is_the_hand_made_one(self):
        b = self.body(protocol.LOOK_FEMALE)
        self.assertEqual(struct.unpack_from('<II', b, 265) + tuple(b[273:275]), (3, 5, 0, 5))
        self.assertEqual(b[275:275 + len('魔法师10'.encode('gbk'))], '魔法师10'.encode('gbk'))


class Names(unittest.TestCase):
    def test_digits_pad_and_old_teams_unchanged(self):
        from line import plan
        t = plan.Team('m', 0, 10000, names='魔法师', accounts=1, first=9, digits=2, job='术士')
        with mock.patch.dict(plan.TEAMS, {'x': t}), mock.patch.object(plan, 'aliases', return_value={}):
            self.assertEqual(plan.batch_names('x', 1), ['魔法师09', '魔法师10', '魔法师11', '魔法师12'])
        old = plan.Team('m', 0, 10000, names='亿万J', accounts=1)
        with mock.patch.dict(plan.TEAMS, {'x': old}), mock.patch.object(plan, 'aliases', return_value={}):
            self.assertEqual(plan.batch_names('x', 2), ['亿万J5', '亿万J6', '亿万J7', '亿万J8'])


if __name__ == '__main__':
    unittest.main()
