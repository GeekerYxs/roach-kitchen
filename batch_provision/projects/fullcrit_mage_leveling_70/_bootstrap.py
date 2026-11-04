"""Make the independent project runnable while resolving shared shitu building blocks.

Also loads the single team config (team.toml, or SHITU_TEAM_CONFIG) into SHITU_* environment variables
*before* any shared module is imported: lunhui15 / common read the leader and apprentices at import time, so a
stage script started on its own would otherwise drive the shared defaults (伏地魔1 + 十万1..3).
Variables already set in the environment win over the file.
"""
import os
from pathlib import Path
import sys
import tomllib

PROJECT = Path(__file__).resolve().parent
REPO = PROJECT.parents[2]
SHITU = REPO / "batch_provision" / "research" / "shitu"
BATCH = REPO / "batch_provision"

for path in (str(SHITU), str(BATCH)):
    if path not in sys.path:
        sys.path.insert(0, path)


def load_team(path=None):
    path = Path(path or os.environ.get("SHITU_TEAM_CONFIG") or PROJECT / "team.toml")
    with open(path, "rb") as f:
        return tomllib.load(f)


def env_from_team(cfg, environ=os.environ):
    leader = cfg["leader"]
    apprentices = [n for n in cfg["apprentices"] if n]
    if not leader or not apprentices:
        raise SystemExit(f"team config needs leader and apprentices: {cfg}")
    revive = int(cfg.get("revive_item", 0) or 0)
    values = {
        "SHITU_LEADER": leader,
        "SHITU_MASTERS": leader,
        "SHITU_CASTERS": leader,
        "SHITU_APPRENTICES": ",".join(apprentices),
        "SHITU_PLAYER_SKILL": str(cfg.get("player_skill", 354)),
        "SHITU_PLAYER_SKILL_LEVEL": str(cfg.get("player_skill_level", 7)),
        "SHITU_STAT": cfg.get("talent_stat", "敏捷"),
        "SHITU_PET_MAGIC_ONLY": "1",
        "SHITU_MAX_FALLS": str(cfg.get("max_falls", 1)),
        "SHITU_MAX_FALLS_WITH_REVIVE": str(cfg.get("max_falls_with_revive", 3)),
        "SHITU_REVIVE_CANDIDATE": str(revive),
        "SHITU_SELL_WORN_WHITE": "1" if cfg.get("sell_worn_white") else "0",
        "SHITU_SHOE_WAIT_MAX": str(cfg.get("shoe_wait_max_seconds", 600)),
    }
    for key, value in values.items():
        environ.setdefault(key, value)
    return values


env_from_team(load_team())
