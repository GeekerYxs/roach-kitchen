"""Compatibility entry: the 43-70 supervisor is now part of run_level_to_70.py.

The old version sent every apprentice below 48 to 巨石之城东部遗址, so a fresh team would have been taken to a
level-43 map at level 1. run_level_to_70.py picks the stage from the real lowest level for the whole 1-70 line;
from level 43 on it runs exactly the old order 1100 -> 监狱 -> 陷阱囚牢 -> 禁锢之地.
"""
import _bootstrap  # noqa: F401

import trial_run as t
import run_level_to_70

if __name__ == "__main__":
    try:
        run_level_to_70.main()
    except t.Stop as exc:
        run_level_to_70.say(f"停止：{exc}")
        raise SystemExit(1)
