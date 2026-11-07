"""User 2026-11-07: 御通关钥匙 / 御温泉消费券 must survive every junk drop and sell."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'research' / 'shitu'))
import keep_items  # noqa: E402


def it(name, type_=0x1000, quality=1, important=False):
    return NS(name=name, type=type_, quality=quality, important=important, tradable=False)


class KeepItems(unittest.TestCase):
    def test_kept(self):
        for n in ('(御)通关钥匙', '通关钥匙', '(御)温泉消费券', '温泉消费券'):
            self.assertTrue(keep_items.kept(it(n)), n)
        self.assertFalse(keep_items.kept(it('毛皮')))
        self.assertFalse(keep_items.kept(None))

    def test_drop_order_skips(self):
        import r4_util
        items = {1: it('(御)温泉消费券'), 2: it('(御)通关钥匙', important=True), 3: it('毛皮', quality=0)}
        bag = [NS(item_id=i, slot=i) for i in items]
        self.assertEqual([s.item_id for s in r4_util.drop_order(bag, items)], [3])

    def test_farm_junk_skips(self):
        import farm
        self.assertFalse(farm.junk(it('(御)温泉消费券')))
        self.assertFalse(farm.junk(it('(御)通关钥匙', important=True)))
        self.assertTrue(farm.junk(it('毛皮')))


if __name__ == '__main__':
    unittest.main()


class StoneKind(unittest.TestCase):
    def test_at_stone(self):
        import trash
        a = it('技能石-战士系-警惕1级'); a.type = 2081
        b = it('技能石-战士系-警惕2级', important=True); b.type = 2081
        c = it('混沌技能石', important=True)
        got, warn = trash.check_names([('@技能石', False), ('@乱写', False)], {1: a})
        self.assertEqual(got, {'@技能石'}); self.assertEqual(len(warn), 1)
        from unittest import mock
        with mock.patch.object(trash, 'names', lambda *x, **k: frozenset(got)):
            self.assertTrue(trash.is_named(a))
            self.assertFalse(trash.is_named(b))
            self.assertFalse(trash.is_named(c))
