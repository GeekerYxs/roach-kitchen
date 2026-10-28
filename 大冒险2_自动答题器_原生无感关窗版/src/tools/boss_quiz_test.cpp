// boss_quiz_test.cpp — controller/boss_quiz.h 的离线测试。
// 样本：2026-10-26/27 录到的 9 道 boss 题（0x46F5），题目、选项原样（含「1、」前缀），正确下标是实测答对的。
#include <cstdio>
#include <sstream>
#include <string>
#include <vector>
#include "../controller/boss_quiz.h"

static int fails = 0;
#define CHECK(cond, msg) do { \
    if (cond) printf("  PASS  %s\n", std::string(msg).c_str()); \
    else { printf("  FAIL  %s\n", std::string(msg).c_str()); fails++; } \
} while (0)

struct Sample {
    uint32_t qno;
    const char* stem;
    std::vector<std::string> options;
    int right;
};

static const std::vector<Sample> SAMPLES = {
    {2616, u8"地球自转一周需要多长时间？", {u8"1、大约 24 小时（一天）", u8"2、兼爱非攻", u8"3、仁者爱人", u8"4、无为而治"}, 0},
    {2688, u8"分数中，分子在上还是分母在上？", {u8"1、分子在上", u8"2、汉书", u8"3、后汉书", u8"4、三国志"}, 0},
    {2703, u8"月亮会自己发光吗？", {u8"1、勿以恶小而为之，勿以善小而不为", u8"2、不会，月亮反射太阳的光", u8"3、淡泊以明志，宁静以致远", u8"4、我得孔明，如鱼得水"}, 1},
    {2771, u8"我国的直辖市有几个？", {u8"1、诗经", u8"2、4 个", u8"3、汉乐府", u8"4、古诗十九首"}, 1},
    {2792, u8"什么工具能测量时间？", {u8"1、欧阳修", u8"2、钟表", u8"3、范仲淹", u8"4、王安石"}, 1},
    {2866, u8"世界上最大的半岛是什么？", {u8"1、《诗经》", u8"2、《全唐诗》", u8"3、阿拉伯半岛", u8"4、《诗品》"}, 2},
    {2916, u8"太阳系中距离太阳最近的行星是什么？", {u8"1、关汉卿", u8"2、王实甫", u8"3、马致远", u8"4、水星"}, 3},
    {2927, u8"经常洗澡的好处是什么？", {u8"1、《南华经》", u8"2、《道德经》", u8"3、《黄庭经》", u8"4、清洁皮肤，预防皮肤病"}, 3},
    {2934, u8"15 以内的质数有哪些？", {u8"1、《孙子兵法》", u8"2、《孙膑兵法》", u8"3、《吴子》", u8"4、2、3、5、7、14、13"}, 3},
    // 2026-10-27 22:26-22:28 新版答题器上线实测（弹窗确认后按建议答，全部测试通过）
    {2851, u8"冰雹多发生在什么季节？", {u8"1、《咏史》", u8"2、《丹青引赠曹将军霸》", u8"3、夏季", u8"4、《焚书坑》"}, 2},
    {2962, u8"什么是电路？", {u8"1、《尔雅》", u8"2、《说文解字》", u8"3、《切韵》", u8"4、电流通过的路径"}, 3},
    {2983, u8"粽子是用什么做的？", {u8"1、风", u8"2、雷", u8"3、火", u8"4、糯米、粽叶、馅料（肉、枣等）"}, 3},
};

int main() {
    printf("[1] strip_option\n");
    CHECK(bq::strip_option(u8"3、阿拉伯半岛") == u8"阿拉伯半岛", "去掉「3、」");
    CHECK(bq::strip_option(u8"4、2、3、5、7、14、13") == u8"2、3、5、7、14、13", "只去一次编号");
    CHECK(bq::strip_option(u8"2、4 个") == u8"4 个", "「4 个」不被削成「个」");
    CHECK(bq::strip_option(u8"4 个") == u8"4 个", "没有编号时原样");
    CHECK(bq::strip_option("") == "", "空选项");

    printf("[2] 题库为空、干扰项为空：只靠书名号和共有字\n");
    {
        bq::Bank empty;
        int right = 0, wrong = 0, none = 0;
        for (auto& s : SAMPLES) {
            auto d = bq::decide(empty, s.qno, s.stem, s.options);
            CHECK(d.opt == -1, std::to_string(s.qno) + " 题库为空时不直接答");
            if (d.suggest == s.right) right++;
            else if (d.suggest < 0) none++;
            else { wrong++; printf("        wrong suggest %u -> %d (%s)\n", s.qno, d.suggest, d.why.c_str()); }
        }
        printf("        建议对 %d / 没建议 %d / 建议错 %d\n", right, none, wrong);
        CHECK(wrong == 0, "空题库时一个都不建议错");
    }

    printf("[3] 留一法：用其余 8 道的干扰项，猜第 9 道\n");
    for (size_t k = 0; k < SAMPLES.size(); k++) {
        bq::Bank bank;
        for (size_t j = 0; j < SAMPLES.size(); j++)
            if (j != k) bq::record_pass(bank, SAMPLES[j].qno, SAMPLES[j].stem, SAMPLES[j].options, SAMPLES[j].right);
        auto& s = SAMPLES[k];
        auto d = bq::decide(bank, s.qno, s.stem, s.options);
        CHECK(d.opt == -1 && (d.suggest == s.right || d.suggest == -1),
              std::to_string(s.qno) + " 建议=" + std::to_string(d.suggest) + "（对的是 " + std::to_string(s.right) + "）" + d.why);
    }

    printf("[4] 题库命中：按答案文字找，不怕选项换位置\n");
    {
        bq::Bank bank;
        auto s = SAMPLES[5];   // 2866
        bq::record_pass(bank, s.qno, s.stem, s.options, s.right);
        auto d = bq::decide(bank, s.qno, s.stem, s.options);
        CHECK(d.opt == 2, "原顺序 -> 2");
        std::vector<std::string> shuffled = {u8"1、阿拉伯半岛", u8"2、《诗经》", u8"3、《诗品》", u8"4、《全唐诗》"};
        d = bq::decide(bank, s.qno, s.stem, shuffled);
        CHECK(d.opt == 0, "换位置 -> 0");
        std::vector<std::string> other = {u8"1、甲", u8"2、乙", u8"3、丙", u8"4、丁"};
        d = bq::decide(bank, s.qno, s.stem, other);
        CHECK(d.opt == -1, "题号一样但答案不在选项里 -> 不直接答，要人确认");
    }

    printf("[5] 只有下标的条目（2932：题目没录到）\n");
    {
        bq::Bank bank;
        std::istringstream in("\xEF\xBB\xBF题号\t答案\t下标(0开始)\t题目\n2932\t\t3\t\n");
        bq::parse_bank_tsv(bank, in);
        auto d = bq::decide(bank, 2932, u8"随便", {u8"1、a", u8"2、b", u8"3、c", u8"4、d"});
        CHECK(d.opt == 3, "按下标 3");
    }

    printf("[6] 记表 + 文件来回\n");
    {
        bq::Bank bank;
        for (auto& s : SAMPLES) bq::record_pass(bank, s.qno, s.stem, s.options, s.right);
        CHECK(!bq::record_pass(bank, SAMPLES[0].qno, SAMPLES[0].stem, SAMPLES[0].options, SAMPLES[0].right), "重复记同一题 -> 没变化");
        CHECK(bank.entries.size() == SAMPLES.size(), "每道样本一条");
        CHECK(bank.decoys.count(u8"《诗经》") && bank.decoys.count(u8"王安石"), "干扰项进了集合");
        CHECK(!bank.decoys.count(u8"阿拉伯半岛"), "正确答案没进干扰项");
        std::ostringstream a, b;
        bq::write_bank_tsv(bank, a);
        bq::write_decoys(bank, b);
        bq::Bank back;
        std::istringstream ia(a.str()), ib(b.str());
        bq::parse_bank_tsv(back, ia);
        bq::parse_decoys(back, ib);
        CHECK(back.entries.size() == bank.entries.size() && back.decoys == bank.decoys, "写出再读回一样");
        CHECK(back.entries[2934].answer == u8"2、3、5、7、14、13" && back.entries[2771].answer == u8"4 个", "带「、」和空格的答案原样保存");
        for (auto& s : SAMPLES) {
            auto d = bq::decide(back, s.qno, s.stem, s.options);
            CHECK(d.opt == s.right, std::to_string(s.qno) + " 读回后命中");
        }
    }

    printf("[7] 仓库自带的种子文件 data/boss_bank.tsv + boss_decoys.txt\n");
    {
        bq::Bank seed;
        bool ok = bq::load_files(seed, "../data/boss_bank.tsv", "../data/boss_decoys.txt");
        CHECK(ok, "读得到种子文件");
        CHECK(seed.entries.size() >= 9 && !seed.entries.count(2916), "至少 9 条，2916 不在表里（没录到作答）");
        for (auto& s : SAMPLES) {
            auto d = bq::decide(seed, s.qno, s.stem, s.options);
            if (s.qno == 2916) CHECK(d.opt == -1 && d.suggest == 3, "2916 不在表里，靠干扰项建议 水星");
            else if (seed.entries.count(s.qno)) CHECK(d.opt == s.right, std::to_string(s.qno) + " 种子命中");
        }
    }

    printf("[8] 静默模式的 guess：每道题都给出一个下标，且不比 opt / suggest 差\n");
    {
        bq::Bank empty;
        for (auto& s : SAMPLES) {
            auto d = bq::decide(empty, s.qno, s.stem, s.options);
            CHECK(d.guess >= 0 && d.guess < (int)s.options.size(), std::to_string(s.qno) + " 有 guess");
            if (d.suggest >= 0) CHECK(d.guess == d.suggest, std::to_string(s.qno) + " guess = suggest");
        }
        bq::Bank bank;
        for (auto& s : SAMPLES) bq::record_pass(bank, s.qno, s.stem, s.options, s.right);
        for (auto& s : SAMPLES) {
            auto d = bq::decide(bank, s.qno, s.stem, s.options);
            CHECK(d.guess == s.right, std::to_string(s.qno) + " 题库命中时 guess = 正确答案");
        }
        std::vector<std::string> only_books = {u8"1、《诗经》", u8"2、《全唐诗》", u8"3、《诗品》", u8"4、《吴子》", u8""};
        auto d = bq::decide(bank, 1, u8"随便", only_books);
        CHECK(d.guess == 0, "全是干扰项时退回第一个非空选项");
    }

    printf("\n%s (%d failures)\n", fails == 0 ? "ALL TESTS PASSED" : "TESTS FAILED", fails);
    return fails == 0 ? 0 : 1;
}
