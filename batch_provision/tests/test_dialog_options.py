import unittest

from provisioner.world import parse_options


class ParseOptionsTest(unittest.TestCase):
    def test_298_opt_attribute(self):
        text = ('#FFFFFF#很高兴见到你！好吧，我现在送你去那个村庄吧？\n#ABB5FC#[URL opt=1]逍遥村[/URL]\n')
        self.assertEqual(parse_options(text), ((1, '逍遥村'),))

    def test_298_opt_numbers_win_over_position(self):
        text = '[URL opt=3]传送服务[/URL][URL opt=7]★平静海岸2区190金币[/URL][URL opt=0]离开[/URL]'
        self.assertEqual(parse_options(text), ((3, '传送服务'), (7, '平静海岸2区190金币'), (0, '离开')))

    def test_297_plain_tags_still_use_position(self):
        text = '[URL]#FF0000#甲[/URL][URL]乙[/URL][URL]离开[/URL]'
        self.assertEqual(parse_options(text), ((1, '甲'), (2, '乙'), (0, '离开')))

    def test_other_attribute_without_opt_uses_position(self):
        self.assertEqual(parse_options('[URL x=5]甲[/URL]'), ((1, '甲'),))

    def test_no_options(self):
        self.assertEqual(parse_options('只是说话，没有链接'), ())


if __name__ == '__main__':
    unittest.main()
