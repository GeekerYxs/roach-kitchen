// boss_quiz.h — boss「开打」时弹的题（0x46F5）的决策：纯函数，无 Windows 依赖，tools/boss_quiz_test.cpp 离线测试。
// 所有字符串都是 UTF-8（DLL 推上来的事件已经转成 UTF-8）。
//
// 题库两个文本文件（放在 启动答题器.exe 旁边的 data\ 里，记事本就能改）：
//   boss_bank.tsv    每行：题号<TAB>答案文字<TAB>下标(0 开始)<TAB>题目    （第一行是表头）
//   boss_decoys.txt  每行一个「干扰项」文字（以 # 开头的行是注释）
// 规律（BOSS_QUIZ.md 第 5 节，10/10 符合）：题号是固定题库编号；3 个错误选项来自另一类
// （古书、古人、诸子、名句），正确项是唯一和题目沾边的那个。
#pragma once
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <map>
#include <set>
#include <sstream>
#include <string>
#include <vector>

namespace bq {

struct Entry {
    uint32_t qno = 0;
    std::string answer;   // 选项文字（去掉「1、」前缀），空 = 只知道下标
    int opt = -1;         // 答对时的下标（0 开始）
    std::string stem;
};

struct Bank {
    std::map<uint32_t, Entry> entries;
    std::set<std::string> decoys;
};

// 去掉首尾空白。
inline std::string trim(const std::string& s) {
    size_t b = 0, e = s.size();
    while (b < e && (s[b] == ' ' || s[b] == '\t')) b++;
    while (e > b && (s[e - 1] == ' ' || s[e - 1] == '\t' || s[e - 1] == '\r' || s[e - 1] == '\n')) e--;
    return s.substr(b, e - b);
}

// 去掉游戏给选项加的编号「1、」（只去一次：「4、2、3、5」->「2、3、5」），再去首尾空白。
inline std::string strip_option(const std::string& s) {
    size_t i = 0;
    while (i < s.size() && s[i] >= '0' && s[i] <= '9') i++;
    if (i > 0 && s.compare(i, 3, "\xE3\x80\x81") == 0) i += 3;        // 、
    else if (i > 0 && i < s.size() && s[i] == '.') i += 1;
    else i = 0;
    return trim(s.substr(i));
}

// 去掉书名号《》。
inline std::string strip_book_marks(const std::string& s) {
    static const std::string L = "\xE3\x80\x8A", R = "\xE3\x80\x8B";
    std::string t = s;
    if (t.size() >= 6 && t.compare(0, 3, L) == 0 && t.compare(t.size() - 3, 3, R) == 0)
        t = t.substr(3, t.size() - 6);
    return t;
}

inline bool is_decoy(const Bank& bank, const std::string& option_text) {
    std::string t = strip_option(option_text);
    if (t.empty()) return true;
    std::string bare = strip_book_marks(t);
    if (bare != t) return true;                       // 书名一律当干扰项
    return bank.decoys.count(t) > 0 || bank.decoys.count(bare) > 0;
}

// UTF-8 拆成字符（每个汉字一个元素）。
inline std::vector<std::string> utf8_chars(const std::string& s) {
    std::vector<std::string> out;
    for (size_t i = 0; i < s.size();) {
        unsigned char c = (unsigned char)s[i];
        size_t n = c < 0x80 ? 1 : (c >> 5) == 6 ? 2 : (c >> 4) == 14 ? 3 : 4;
        out.push_back(s.substr(i, n));
        i += n;
    }
    return out;
}

// 选项和题目共有几个字（只数汉字和数字，标点不算）。
inline int shared_chars(const std::string& stem, const std::string& option_text) {
    std::set<std::string> in_stem;
    for (auto& ch : utf8_chars(stem)) in_stem.insert(ch);
    std::set<std::string> counted;
    int n = 0;
    for (auto& ch : utf8_chars(strip_option(option_text))) {
        bool cjk = ch.size() == 3 && (unsigned char)ch[0] >= 0xE4 && (unsigned char)ch[0] <= 0xE9;
        bool digit = ch.size() == 1 && ch[0] >= '0' && ch[0] <= '9';
        if ((cjk || digit) && in_stem.count(ch) && counted.insert(ch).second) n++;
    }
    return n;
}

struct Decision {
    int opt = -1;          // 题库命中时直接答的下标；-1 = 题库里没有
    int suggest = -1;      // 题库没有时的建议下标；-1 = 没把握
    int guess = -1;        // 静默模式最后用的下标：opt，否则 suggest，否则「排除干扰项后第一个」，再不行就 0
    std::string why;
};

inline Decision decide_core(const Bank& bank, uint32_t qno, const std::string& stem,
                            const std::vector<std::string>& options) {
    Decision d;
    auto it = bank.entries.find(qno);
    if (it != bank.entries.end()) {
        const Entry& e = it->second;
        if (!e.answer.empty()) {
            for (size_t i = 0; i < options.size(); i++) {
                if (strip_option(options[i]) == e.answer) {
                    d.opt = (int)i;
                    d.why = "题库命中（题号 " + std::to_string(qno) + "，按答案文字找到）";
                    return d;
                }
            }
            d.why = "题库里有这个题号，但答案「" + e.answer + "」不在选项里";
        } else if (e.opt >= 0 && e.opt < (int)options.size()) {
            d.opt = e.opt;
            d.why = "题库命中（题号 " + std::to_string(qno) + "，只记了下标）";
            return d;
        }
    }

    std::vector<int> left;
    for (size_t i = 0; i < options.size(); i++)
        if (!is_decoy(bank, options[i])) left.push_back((int)i);
    if (left.size() == 1) {
        d.suggest = left[0];
        if (d.why.empty()) d.why = "题库没有；排除了 " + std::to_string(options.size() - 1) + " 个干扰项（书名/人名/名句），只剩这一个";
        return d;
    }
    // 排除后还剩几个：挑和题目共有字最多的，并列就不建议
    int best = -1, best_score = 0;
    bool tie = false;
    for (int i : left) {
        int sc = shared_chars(stem, options[i]);
        if (sc > best_score) { best = i; best_score = sc; tie = false; }
        else if (sc == best_score && sc > 0) tie = true;
    }
    if (best >= 0 && !tie) {
        d.suggest = best;
        if (d.why.empty()) d.why = "题库没有；排除后剩 " + std::to_string(left.size()) + " 个，这个和题目共有 " +
                                   std::to_string(best_score) + " 个字";
    } else if (d.why.empty()) {
        d.why = "题库没有，也看不出哪个对";
    }
    return d;
}

// decide_core 再加上静默模式要用的 guess：题库命中 > 建议 > 排除干扰项后第一个 > 第一个非空选项。
inline Decision decide(const Bank& bank, uint32_t qno, const std::string& stem,
                       const std::vector<std::string>& options) {
    Decision d = decide_core(bank, qno, stem, options);
    if (d.opt >= 0) d.guess = d.opt;
    else if (d.suggest >= 0) d.guess = d.suggest;
    else {
        for (size_t i = 0; i < options.size() && d.guess < 0; i++)
            if (!is_decoy(bank, options[i])) d.guess = (int)i;
        for (size_t i = 0; i < options.size() && d.guess < 0; i++)
            if (!strip_option(options[i]).empty()) d.guess = (int)i;
        if (d.guess < 0 && !options.empty()) d.guess = 0;
    }
    return d;
}

// 答对后记表：题号 -> 答案；其余非空选项进干扰项集合。返回 true = 有变化，需要存盘。
inline bool record_pass(Bank& bank, uint32_t qno, const std::string& stem,
                        const std::vector<std::string>& options, int opt) {
    if (opt < 0 || opt >= (int)options.size()) return false;
    bool changed = false;
    Entry e;
    e.qno = qno;
    e.answer = strip_option(options[opt]);
    e.opt = opt;
    e.stem = stem;
    auto it = bank.entries.find(qno);
    if (it == bank.entries.end() || it->second.answer != e.answer || it->second.opt != e.opt ||
        (it->second.stem.empty() && !stem.empty())) {
        bank.entries[qno] = e;
        changed = true;
    }
    for (size_t i = 0; i < options.size(); i++) {
        std::string t = strip_option(options[i]);
        if ((int)i == opt || t.empty()) continue;
        if (bank.decoys.insert(t).second) changed = true;
    }
    return changed;
}

// ---- 文件读写 ----
inline std::vector<std::string> split_tab(const std::string& line) {
    std::vector<std::string> out;
    std::string cur;
    for (char c : line) {
        if (c == '\t') { out.push_back(cur); cur.clear(); }
        else if (c != '\r' && c != '\n') cur += c;
    }
    out.push_back(cur);
    return out;
}

inline std::string strip_bom(const std::string& s) {
    return s.compare(0, 3, "\xEF\xBB\xBF") == 0 ? s.substr(3) : s;
}

inline void parse_bank_tsv(Bank& bank, std::istream& in) {
    std::string line;
    bool first = true;
    while (std::getline(in, line)) {
        if (first) { line = strip_bom(line); first = false; }
        if (line.empty() || line[0] == '#') continue;
        auto f = split_tab(line);
        if (f.empty() || f[0].empty() || !(f[0][0] >= '0' && f[0][0] <= '9')) continue;   // 表头
        Entry e;
        e.qno = (uint32_t)strtoul(f[0].c_str(), nullptr, 10);
        if (f.size() > 1) e.answer = f[1];
        if (f.size() > 2 && !f[2].empty()) e.opt = atoi(f[2].c_str());
        if (f.size() > 3) e.stem = f[3];
        bank.entries[e.qno] = e;
    }
}

inline void parse_decoys(Bank& bank, std::istream& in) {
    std::string line;
    bool first = true;
    while (std::getline(in, line)) {
        if (first) { line = strip_bom(line); first = false; }
        std::string t = trim(line);
        if (t.empty() || t[0] == '#') continue;
        bank.decoys.insert(t);
    }
}

inline void write_bank_tsv(const Bank& bank, std::ostream& out) {
    out << "\xEF\xBB\xBF" << "题号\t答案\t下标(0开始)\t题目\n";
    for (auto& kv : bank.entries) {
        const Entry& e = kv.second;
        out << e.qno << '\t' << e.answer << '\t' << (e.opt >= 0 ? std::to_string(e.opt) : "") << '\t' << e.stem << '\n';
    }
}

inline void write_decoys(const Bank& bank, std::ostream& out) {
    out << "\xEF\xBB\xBF" << "# boss 题的干扰项（错误选项），一行一个；答对后会自动追加\n";
    for (auto& t : bank.decoys) out << t << '\n';
}

// 路径是 std::string（窄字符），控制器里用 _wfopen 时自己转换；这里给测试用。
inline bool load_files(Bank& bank, const std::string& tsv, const std::string& decoys) {
    std::ifstream a(tsv, std::ios::binary), b(decoys, std::ios::binary);
    bool opened = a.is_open();
    if (opened) parse_bank_tsv(bank, a);
    if (b.is_open()) parse_decoys(bank, b);
    return opened;
}

}  // namespace bq
