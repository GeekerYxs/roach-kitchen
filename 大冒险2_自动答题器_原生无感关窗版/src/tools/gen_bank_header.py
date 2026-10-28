# -*- coding: utf-8 -*-
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BANK_PATH = ROOT.parent / "data" / "bank.json"   # 答题器包里的 data/bank.json
OUT_PATH = ROOT / "dll" / "bank_data.h"

def c_escape(s):
    out = ""
    for c in s:
        if c == '"': out += '\\"'
        elif c == '\\': out += '\\\\'
        elif c == '\n': out += '\\n'
        elif c == '\r': out += '\\r'
        elif c == '\t': out += '\\t'
        else: out += c
    return out

def generate():
    with open(BANK_PATH, "r", encoding="utf-8") as f:
        bank = json.load(f)

    lines = [
        "#pragma once",
        "#include <string>",
        "#include <vector>",
        "",
        "struct BankQA {",
        "    std::string stem;",
        "    std::string answer;",
        "    int fallback_opt;",
        "};",
        "",
        "inline const std::vector<BankQA>& get_embedded_bank() {",
        "    static const std::vector<BankQA> s_bank = {"
    ]

    for k, v in bank.items():
        stem_str = c_escape(k)
        ans_str = ""
        fallback_opt = -1
        if isinstance(v, str):
            ans_str = c_escape(v)
        elif isinstance(v, dict):
            ans_str = c_escape(str(v.get("note", "")))
            opt = v.get("answer") if v.get("answer") is not None else v.get("opt", -1)
            fallback_opt = opt if opt is not None else -1

        lines.append(f'        {{ "{stem_str}", "{ans_str}", {fallback_opt} }},')

    lines.extend([
        "    };",
        "    return s_bank;",
        "}",
        ""
    ])

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"[OK] Generated {OUT_PATH} with {len(bank)} entries")

if __name__ == "__main__":
    generate()
