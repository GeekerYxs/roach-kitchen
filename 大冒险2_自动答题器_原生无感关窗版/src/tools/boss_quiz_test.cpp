// boss_quiz_test.cpp — controller/boss_quiz.h 的离线测试。
// 样本：2026-10-26/27 录到的 boss 题（0x46F5），题目、选项原样（含「1、」前缀），正确下标是实测答对的。
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
    {2851, u8"冰雹多发生在什么季节？", {u8"1、《咏史》", u8"2、《丹青引赠曹将军霸》", u8"3、夏季", u8"4、《焚书坑》"}, 2},
    {2962, u8"什么是电路？", {u8"1、《尔雅》", u8"2、《说文解字》", u8"3、《切韵》", u8"4、电流通过的路径"}, 3},
    {2983, u8"粽子是用什么做的？", {u8"1、风", u8"2、雷", u8"3、火", u8"4、糯米、粽叶、馅料（肉、枣等）"}, 3},
    {2711, u8"我国的国歌是什么？", {u8"1、前燕和东晋", u8"2、《义勇军进行曲》", u8"3、前秦和东晋", u8"4、后赵和东晋"}, 1},
};

int main() {
    printf("[1] strip_option\n");
    CHECK(bq::strip_option(u8"3、阿拉伯半岛") == u8"阿拉伯半岛", "去掉「3、」");
    CHECK(bq::strip_option(u8"4、2、3、5、7、14、13") == u8"2、3、5、7、14、13", "只去一次编号");
    CHECK(bq::strip_option(u8"2、4 个") == u8"4 个", "「4 个」不被削成「个」");
    CHECK(bq::strip_option(u8"4 个") == u8"4 个", "没有编号时原样");
    CHECK(bq::strip_option("") == "", "空选项");

    printf("[2] 仓库题库 data/boss_bank.tsv + boss_decoys.txt\n");
    bq::Bank repo;
    CHECK(bq::load_files(repo, "../data/boss_bank.tsv", "../data/boss_decoys.txt"), "读得到题库文件");
    CHECK(repo.entries.size() >= 400 && repo.entries.begin()->first == 2601 && repo.decoys.size() > 800,
          "2601 起至少 400 道，干扰项 800+");
    int rule_ok = 0, verified = 0;
    for (auto& kv : repo.entries) {
        if (kv.first >= 2601 && kv.first <= 3000 && kv.second.opt == (int)(kv.first - 2601) / 100) rule_ok++;
        verified += kv.second.verified;
    }
    CHECK(rule_ok == 400, "2601～3000 的下标全部 = (题号-2601)/100（" + std::to_string(rule_ok) + "）");
    CHECK(verified >= 37, "至少 37 道实测（" + std::to_string(verified) + "）");
    for (auto& s : SAMPLES) {
        auto d = bq::decide(repo, s.qno, s.stem, s.options);
        CHECK(d.opt == s.right && d.guess == s.right, std::to_string(s.qno) + " 命中 " + d.why);
    }

    printf("[3] 题库命中：按答案文字找，不怕选项换位置；文字对不上不用旧下标\n");
    {
        auto& s = SAMPLES[5];   // 2866
        std::vector<std::string> shuffled = {u8"1、阿拉伯半岛", u8"2、《诗经》", u8"3、《诗品》", u8"4、《全唐诗》"};
        CHECK(bq::decide(repo, s.qno, s.stem, shuffled).opt == 0, "换位置 -> 0");
        std::vector<std::string> other = {u8"1、甲", u8"2、乙", u8"3、丙", u8"4、丁"};
        auto d = bq::decide(repo, s.qno, s.stem, other);
        CHECK(d.opt == -1 && d.guess >= 0, "题号一样但答案不在选项里 -> 不按旧下标，退到排除法");
    }

    printf("[4] 题库没有的题号：全量干扰项排除后只剩正确项\n");
    for (auto& s : SAMPLES) {
        bq::Bank bank = repo;
        bank.entries.erase(s.qno);
        auto d = bq::decide(bank, s.qno, s.stem, s.options);
        if (s.qno == 2711) CHECK(d.suggest != 1, "2711 答案带书名号，排除法认不出（所以要靠题库）");
        else CHECK(d.opt == -1 && d.suggest == s.right, std::to_string(s.qno) + " 排除法 -> " + std::to_string(d.suggest));
    }
    {
        bq::Bank empty;
        std::vector<std::string> only_books = {u8"1、《诗经》", u8"2、《全唐诗》", u8"3、《诗品》", u8"4、《吴子》", u8""};
        CHECK(bq::decide(empty, 1, u8"随便", only_books).guess == 0, "全是干扰项时退回第一个非空选项");
    }

    printf("[5] 只有下标的旧条目\n");
    {
        bq::Bank bank;
        std::istringstream in("\xEF\xBB\xBF题号\t答案\t下标(0开始)\t题目\n9999\t\t3\t\n");
        bq::parse_bank_tsv(bank, in);
        auto d = bq::decide(bank, 9999, u8"随便", {u8"1、a", u8"2、b", u8"3、c", u8"4、d"});
        CHECK(d.opt == 3 && d.verified, "没有第 5 列 = 实测，按下标 3");
    }

    printf("[6] 答对记表：推算 -> 实测；文件来回\n");
    {
        bq::Bank bank = repo;
        auto& s = SAMPLES[6];   // 2916 推算
        bank.entries[s.qno].verified = false;
        auto d = bq::decide(bank, s.qno, s.stem, s.options);
        CHECK(d.opt == 3 && !d.verified, "2916 推算命中");
        CHECK(bq::record_pass(bank, s.qno, s.stem, s.options, 3) && bank.entries[s.qno].verified, "答对后改成实测");
        CHECK(!bq::record_pass(bank, s.qno, s.stem, s.options, 3), "再记一次没变化");
        std::ostringstream a;
        bq::write_bank_tsv(bank, a);
        bq::Bank back;
        std::istringstream ia(a.str());
        bq::parse_bank_tsv(back, ia);
        bool same = back.entries.size() == bank.entries.size();
        for (auto& kv : bank.entries) {
            auto& b = back.entries[kv.first];
            same = same && b.answer == kv.second.answer && b.opt == kv.second.opt && b.verified == kv.second.verified;
        }
        CHECK(same, "写出再读回一样（含来源）");
        CHECK(back.entries[2934].answer == u8"2、3、5、7、14、13" && back.entries[2771].answer == u8"4 个", "带「、」和空格的答案原样保存");
    }

    printf("\n%s (%d failures)\n", fails == 0 ? "ALL TESTS PASSED" : "TESTS FAILED", fails);
    return fails == 0 ? 0 : 1;
}
