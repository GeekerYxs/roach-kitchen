"""Unit tests for research/shitu/boss_quiz.py (no game needed): panel text parsing, the answer choice (same rules as
the quizbot's controller/boss_quiz.h) on the repo bank, the 400 questions collected 2026-10-30, and solve()'s
「let the quizbot answer first, otherwise answer here」 flow with a fake panel."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'shitu'))

import boss_quiz as bq  # noqa: E402

# (题号, 题目, 选项原样, 实测答对的下标)
SAMPLES = [
    (2616, '地球自转一周需要多长时间？', ['1、大约 24 小时（一天）', '2、兼爱非攻', '3、仁者爱人', '4、无为而治'], 0),
    (2688, '分数中，分子在上还是分母在上？', ['1、分子在上', '2、汉书', '3、后汉书', '4、三国志'], 0),
    (2703, '月亮会自己发光吗？', ['1、勿以恶小而为之，勿以善小而不为', '2、不会，月亮反射太阳的光', '3、淡泊以明志，宁静以致远',
                          '4、我得孔明，如鱼得水'], 1),
    (2771, '我国的直辖市有几个？', ['1、诗经', '2、4 个', '3、汉乐府', '4、古诗十九首'], 1),
    (2792, '什么工具能测量时间？', ['1、欧阳修', '2、钟表', '3、范仲淹', '4、王安石'], 1),
    (2851, '冰雹多发生在什么季节？', ['1、《咏史》', '2、《丹青引赠曹将军霸》', '3、夏季', '4、《焚书坑》'], 2),
    (2866, '世界上最大的半岛是什么？', ['1、《诗经》', '2、《全唐诗》', '3、阿拉伯半岛', '4、《诗品》'], 2),
    (2916, '太阳系中距离太阳最近的行星是什么？', ['1、关汉卿', '2、王实甫', '3、马致远', '4、水星'], 3),
    (2927, '经常洗澡的好处是什么？', ['1、《南华经》', '2、《道德经》', '3、《黄庭经》', '4、清洁皮肤，预防皮肤病'], 3),
    (2934, '15 以内的质数有哪些？', ['1、《孙子兵法》', '2、《孙膑兵法》', '3、《吴子》', '4、2、3、5、7、14、13'], 3),
    (2962, '什么是电路？', ['1、《尔雅》', '2、《说文解字》', '3、《切韵》', '4、电流通过的路径'], 3),
    (2983, '粽子是用什么做的？', ['1、风', '2、雷', '3、火', '4、糯米、粽叶、馅料（肉、枣等）'], 3),
]

# 伏地魔1 2026-10-27 21:44 [[ui+0x10C8]+0x1CC]+0x108 原文
PANEL_TEXT = ('#FFFFFF#世界上最大的半岛是什么？\n\n#ABB5FC#[URL]1、《诗经》[/URL]\n#ABB5FC#[URL]2、《全唐诗》[/URL]\n'
              '#ABB5FC#[URL]3、阿拉伯半岛[/URL]\n#ABB5FC#[URL]4、《诗品》[/URL]\n#ABB5FC#[URL][/URL]\n')


def learned(samples):
    """A bank holding just these answers, no decoys."""
    return {qno: (bq.strip_option(opts[right]), right) for qno, _stem, opts, right in samples}, set()


def observed():
    """The 400 questions collected 2026-10-30 (data/boss_questions_0x46f5_20261030.json)."""
    data = json.loads((bq.BANK_DIR / 'boss_questions_0x46f5_20261030.json').read_text(encoding='utf-8'))
    return [(q['qno'], q['variants'][0]['stem'], q['variants'][0]['options']) for q in data]


class Parsing(unittest.TestCase):
    def test_panel_text(self):
        stem, options = bq.parse_text(PANEL_TEXT)
        self.assertEqual(stem, '世界上最大的半岛是什么？')
        self.assertEqual(options, ['1、《诗经》', '2、《全唐诗》', '3、阿拉伯半岛', '4、《诗品》'])

    def test_strip_option_only_once(self):
        self.assertEqual(bq.strip_option('4、2、3、5、7、14、13'), '2、3、5、7、14、13')
        self.assertEqual(bq.strip_option('2、4 个'), '4 个')
        self.assertEqual(bq.strip_option('4 个'), '4 个')

    def test_load_bank_files(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'boss_bank.tsv').write_text('题号\t答案\t下标(0开始)\t题目\t来源\n2866\t阿拉伯半岛\t2\t世界上最大的半岛是什么？\t实测\n'
                                                '2916\t水星\t3\t?\t推算\n2932\t\t3\t\n', encoding='utf-8-sig')
            Path(d, 'boss_decoys.txt').write_text('# 注释\n《诗经》\n王安石\n', encoding='utf-8-sig')
            entries, decoys = bq.load_bank(d)
        self.assertEqual(entries, {2866: ('阿拉伯半岛', 2), 2916: ('水星', 3), 2932: ('', 3)})
        self.assertEqual(decoys, {'《诗经》', '王安石'})

    def test_missing_bank_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(bq.load_bank(d), ({}, set()))


class Decide(unittest.TestCase):
    def test_repo_bank_answers_all_400(self):
        bank = bq.load_bank()
        self.assertEqual(sorted(q for q in bank[0] if 2601 <= q <= 3000), list(range(2601, 3001)))
        for qno, stem, opts in observed():
            opt, why = bq.decide(bank, qno, stem, opts)
            self.assertEqual(opt, (qno - 2601) // 100, (qno, why))
            self.assertIn('题库命中', why)
        for qno, stem, opts, right in SAMPLES:
            self.assertEqual(bq.decide(bank, qno, stem, opts)[0], right, qno)

    def test_new_qno_falls_back_to_decoys(self):
        """Pretend each observed question is unknown: the full decoy list leaves only the right option for 395/400.
        The rest: 2711 (answer in 《》, which counts as a decoy), 2736 / 2878 / 2666 (a wrong option like 北京 is
        another question's answer, so it is not in the decoy list) - only a guess, never a confident wrong pick."""
        entries, decoys = bq.load_bank()
        sure = 0
        for qno, stem, opts in observed():
            opt, why = bq.decide(({}, decoys), qno, stem, opts)
            if '猜' not in why:
                self.assertEqual(opt, (qno - 2601) // 100, (qno, why))
                sure += 1
        self.assertGreaterEqual(sure, 395)

    def test_bank_hit_survives_shuffle(self):
        bank = learned(SAMPLES)
        opt, why = bq.decide(bank, 2866, '世界上最大的半岛是什么？', ['1、阿拉伯半岛', '2、《诗经》', '3、《诗品》', '4、《全唐诗》'])
        self.assertEqual(opt, 0)
        self.assertIn('题库命中', why)

    def test_changed_question_does_not_reuse_index(self):
        opt, why = bq.decide(learned(SAMPLES), 2866, '?', ['1、甲', '2、乙', '3、丙', '4、丁'])
        self.assertIn('不在选项里', why)

    def test_index_only_entry(self):
        self.assertEqual(bq.decide(({2932: ('', 3)}, set()), 2932, '?', ['1、a', '2、b', '3、c', '4、d'])[0], 3)

    def test_always_picks_something(self):
        opt, why = bq.decide(({}, set()), 1, '随便', ['1、《诗经》', '2、《全唐诗》', '3、《诗品》', '4、《吴子》'])
        self.assertEqual(opt, 0)
        self.assertIn('猜', why)


class Solve(unittest.TestCase):
    def panel(self, visible=True, qno=2866, chosen=-1):
        stem, options = bq.parse_text(PANEL_TEXT)
        return bq.Panel(0x1000, visible, qno, chosen, 1, stem, options)

    def run_solve(self, panels, bank=None):
        c = SimpleNamespace(name='欧皇', mem=None)
        seq = iter(panels)
        last = [None]

        def fake_read(_mem):
            last[0] = next(seq, last[0])
            return last[0]
        with mock.patch.object(bq, 'read_panel', fake_read), \
                mock.patch.object(bq, 'load_bank', lambda: bank or ({}, set())), \
                mock.patch.object(bq, 'submit') as submit:
            report = bq.solve(c, grace=0.05, say=lambda *_: None)
        return report, submit

    def test_no_panel(self):
        report, submit = self.run_solve([None])
        self.assertIsNone(report)
        submit.assert_not_called()

    def test_closed_panel(self):
        report, submit = self.run_solve([self.panel(visible=False)])
        self.assertIsNone(report)
        submit.assert_not_called()

    def test_quizbot_answers_first(self):
        report, submit = self.run_solve([self.panel(), self.panel(visible=False, chosen=2)])
        submit.assert_not_called()
        self.assertIn('答题器已经答了', report)

    def test_answers_itself_when_panel_stays_open(self):
        open_panel = self.panel()
        report, submit = self.run_solve([open_panel, open_panel, self.panel(visible=False)])
        submit.assert_called_once()
        self.assertEqual(submit.call_args[0][2], 2)          # 3、阿拉伯半岛
        self.assertIn('自己答了', report)


class Kicked(unittest.TestCase):
    """User 2026-10-30: a wrong answer = the server closes the connection; the boss scripts must notice and exit."""
    def test_uses_the_runners_offline_check(self):
        c = SimpleNamespace(name='伏地魔2')
        for state in (True, False):
            fake = SimpleNamespace(offline=mock.Mock(return_value=state))
            with mock.patch.dict(sys.modules, {'r4_util': fake}):
                self.assertIs(bq.kicked(c, wait=0), state)
            fake.offline.assert_called_once_with('伏地魔2')


if __name__ == '__main__':
    unittest.main()
