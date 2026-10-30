# -*- coding: utf-8 -*-
"""gen_boss_bank.py — 从 400 题观察数据生成 boss 题库 data/boss_bank.tsv 和干扰项 data/boss_decoys.txt。

    python -X utf8 gen_boss_bank.py          重新生成；已有的「实测」行保留，和推算冲突就报错、不写文件

规律（2026-10-30，docs/BOSS_QUESTION_COLLECTION_20261030.md）：
  正确下标 = (题号 - 2601) // 100，即 2601～2700 第 1 项、2701～2800 第 2 项、2801～2900 第 3 项、2901～3000 第 4 项。
  生成时 37 道实测全部符合；400 题里这个位置都是唯一和题目沾边的选项，其余 3 个是古书 / 古人 / 名句。
boss_bank.tsv 第 5 列「来源」：实测（游戏里答对过）/ 推算（按规律）。答题器答对推算的题后自动改成实测。
boss_decoys.txt = 400 题的全部错误选项，只在遇到题库里没有的新题号时用来排除。
题目有变化时：更新观察数据 JSON，再跑本脚本。
"""
import json
import re
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent.parent / "data"
SRC = DATA / "boss_questions_0x46f5_20261030.json"
BANK = DATA / "boss_bank.tsv"
DECOYS = DATA / "boss_decoys.txt"
FIRST, BLOCK = 2601, 100


def strip_option(s):
    m = re.match(r'^\d+(、|\.)', s)
    return (s[m.end():] if m else s).strip()


def answer_index(qno):
    return (qno - FIRST) // BLOCK


def read_bank():
    """-> {题号: (答案, 下标, 题目, 实测?)}；没有第 5 列的旧行算实测。"""
    out = {}
    if BANK.is_file():
        for line in BANK.read_text(encoding="utf-8-sig").splitlines():
            f = line.split("\t") + [""] * 5
            if f[0].strip().isdigit():
                out[int(f[0])] = (f[1].strip(), int(f[2]) if f[2].strip() else -1, f[3], f[4].strip() != "推算")
    return out


def main():
    questions = json.loads(SRC.read_text(encoding="utf-8"))
    old = read_bank()
    rows, answers, wrong, conflicts = {}, set(), set(), []
    for q in questions:
        qno = q["qno"]
        if len(q["variants"]) != 1:
            conflicts.append(f"{qno}: {len(q['variants'])} 个版本，规则没覆盖")
            continue
        v = q["variants"][0]
        opts = [strip_option(o) for o in v["options"]]
        i = answer_index(qno)
        if not 0 <= i < len(opts) or not opts[i]:
            conflicts.append(f"{qno}: 下标 {i} 没有选项")
            continue
        verified = False
        if qno in old and old[qno][3]:
            ans, opt = old[qno][0], old[qno][1]
            if (ans and ans != opts[i]) or (opt >= 0 and opt != i):
                conflicts.append(f"{qno}: 实测「{ans}」/{opt}，推算「{opts[i]}」/{i}")
            verified = True
        rows[qno] = (opts[i], i, v["stem"], verified)
        answers.add(opts[i])
        wrong.update(o for j, o in enumerate(opts) if j != i and o)
    if conflicts:
        print("和实测题库冲突，没写文件：\n  " + "\n  ".join(conflicts))
        return 1
    for qno, row in old.items():               # 观察数据以外的实测行原样保留
        if qno not in rows and row[3]:
            rows[qno] = row
    BANK.write_text("﻿题号\t答案\t下标(0开始)\t题目\t来源\n" +
                    "".join(f"{q}\t{a}\t{o}\t{s}\t{'实测' if v else '推算'}\n" for q, (a, o, s, v) in sorted(rows.items())),
                    encoding="utf-8", newline="\n")
    decoys = sorted(wrong - answers)
    DECOYS.write_text("﻿# boss 题干扰项：400 题的全部错误选项（gen_boss_bank.py 生成），只给题库里没有的新题号用\n" +
                      "".join(t + "\n" for t in decoys), encoding="utf-8", newline="\n")
    n_ver = sum(1 for r in rows.values() if r[3])
    print(f"boss_bank.tsv {len(rows)} 道（实测 {n_ver}、推算 {len(rows) - n_ver}）；boss_decoys.txt {len(decoys)} 个")
    return 0


if __name__ == "__main__":
    sys.exit(main())
