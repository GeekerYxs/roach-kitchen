"""Unit tests for research/jingu/sell_list.py (no game needed): what the 禁锢 team sells at 钱德勒 (user 2026-10-29).
Known drops and 勋章 always; anything else tradable only when seen dropping in the farm map; 神射之火枪 never."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'jingu'))

import sell_list as sl  # noqa: E402
from factory.items import Item  # noqa: E402
from provisioner.world import BagSlot  # noqa: E402

T = {i.item_id: i for i in (
    Item(11355, 4096, 1, 800, True, False, '黑暗之血'),
    Item(28030, 4096, 1, 2, True, False, '南方联军将领勋章'),
    Item(31899, 0x8000, 1, 2, True, False, '某个不是杂物的东西'),
    Item(50614, 0x821, 1, 50, True, False, '技能石-魔法系-魔力冲击11级'),
    Item(8263, 0x10E, 3, 237576, True, False, '狡猾狐狸之长尾'),
    Item(670, 0x103, 3, 236000, True, True, '神射之火枪'),
    Item(5750, 0x107, 4, 260000, True, True, '鹰王嗜血腿甲'),
    Item(11077, 8192, 1, 2, False, False, '黑暗结晶'),
    Item(99999, 0x8000, 1, 100, True, False, '新消耗品'),
    Item(30001, 0x1000, 1, 242, True, False, '笔杆'),
    Item(30002, 0x823, 3, 3780, True, False, '厚德之头罩'),
    Item(30003, 0x107, 1, 10114, True, False, '粗制的重型腿甲'),
    Item(37793, 0x1000, 1, 500, True, True, '赤炎混沌以太晶石'),
    Item(30004, 0x8000, 1, 40, True, False, '劲爆汽水'),
    Item(31801, 0x400, 1, 2, True, False, '紫金红葫芦'),
    Item(31802, 0x400, 1, 2, True, False, '黄玉葫芦'),
)}


def bag(*ids):
    return tuple(BagSlot(n, i, 1) for n, i in enumerate(ids))


def sold(ids, dropped):
    return sorted(s.item_id for s, _ in sl.to_sell(bag(*ids), T, frozenset(dropped)))


class SellList(unittest.TestCase):
    def test_materials_and_medal_always(self):
        self.assertEqual(sold([11355, 28030], ()), [11355, 28030])

    def test_junk_sold_wherever_it_came_from(self):
        self.assertEqual(sold([30001, 30002, 30003, 50614], ()), [30001, 30002, 30003, 50614])

    def test_gourds_always(self):
        self.assertEqual(sold([31801, 31802], ()), [31801, 31802])

    def test_important_supplies_and_blue_gear_kept_unless_dropped(self):
        self.assertEqual(sold([37793, 30004, 8263, 5750], ()), [])

    def test_anything_tradable_sold_when_dropped_in_map(self):
        ids = [31899, 8263, 5750, 99999]
        self.assertEqual(sold(ids, ()), [])
        self.assertEqual(sold(ids, ids), sorted(ids))

    def test_never_and_untradable_kept(self):
        self.assertEqual(sold([670, 11077], [670, 11077]), [])

    def test_seen_drops_reads_csv(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'drops.csv'
            p.write_text('1793200000,自由一号,50614,技能石-魔法系-魔力冲击11级,1\n1793200030,波大臀圆,11355,黑暗之血,3\n',
                         encoding='utf-8')
            self.assertEqual(sl.seen_drops(p), frozenset({50614, 11355}))
            self.assertEqual(sl.seen_drops(Path(d) / 'none.csv'), frozenset())


if __name__ == '__main__':
    unittest.main()
