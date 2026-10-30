# -*- coding: utf-8 -*-
"""gen_boss_seed.py — 从 400 题观察数据推出 boss 题答案，写 data/boss_bank_seed.tsv（推算，未逐题实测）。

    python -X utf8 gen_boss_seed.py          生成 / 覆盖种子文件；和实测题库冲突就报错退出

规律（2026-10-30，docs/BOSS_QUESTION_COLLECTION_20261030.md 的 400 题 + data/boss_bank.tsv 的 37 道实测）：
  正确下标 = (题号 - 2601) // 100，即 2601～2700 第 1 项、2701～2800 第 2 项、2801～2900 第 3 项、2901～3000 第 4 项。
  实测 37/37 符合；400 题里这个位置上都是唯一一个「和题目沾边」的现代常识选项，其余 3 个是古书 / 古人 / 名句。
种子文件和 boss_bank.tsv 同格式。答题器先查 boss_bank.tsv（实测），查不到再按答案文字查种子；
答对后照常记进 boss_bank.tsv，种子文件不改。
"""
import json
import re
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent.parent / "data"
SRC = DATA / "boss_questions_0x46f5_20261030.json"
BANK = DATA / "boss_bank.tsv"
OUT = DATA / "boss_bank_seed.tsv"
FIRST, BLOCK = 2601, 100


def strip_option(s):
    m = re.match(r'^\d+(、|\.)', s)
    return (s[m.end():] if m else s).strip()


def answer_index(qno):
    return (qno - FIRST) // BLOCK


def load_verified():
    out = {}
    if BANK.is_file():
        for line in BANK.read_text(encoding="utf-8-sig").splitlines():
            f = line.split("\t")
            if f and f[0].strip().isdigit():
                out[int(f[0])] = (f[1].strip() if len(f) > 1 else "", int(f[2]) if len(f) > 2 and f[2].strip() else -1)
    return out


def main():
    questions = json.loads(SRC.read_text(encoding="utf-8"))
    verified = load_verified()
    rows, conflicts = [], []
    for q in sorted(questions, key=lambda q: q["qno"]):
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
        if qno in verified:
            ans, opt = verified[qno]
            if (ans and ans != opts[i]) or (opt >= 0 and opt != i):
                conflicts.append(f"{qno}: 实测「{ans}」/{opt}，推算「{opts[i]}」/{i}")
        rows.append(f"{qno}\t{opts[i]}\t{i}\t{v['stem']}")
    if conflicts:
        print("和实测题库冲突，没写文件：\n  " + "\n  ".join(conflicts))
        return 1
    OUT.write_text("﻿题号\t答案\t下标(0开始)\t题目\n" + "\n".join(rows) + "\n", encoding="utf-8", newline="\n")
    hit = sum(1 for r in rows if int(r.split("\t")[0]) in verified)
    print(f"写了 {len(rows)} 条 -> {OUT}（其中 {hit} 条和实测题库一致）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
