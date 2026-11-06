"""Path + team setup for the 5-man boss-gear line (user 2026-11-06).

The shared shitu modules (lunhui15 / common) read the team from SHITU_* at import time, so set them before any
of those is imported. Variables already in the environment win.
"""
import os
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parent
BATCH = PROJECT.parents[1]
SHITU = BATCH / "research" / "shitu"

for path in (str(SHITU), str(BATCH)):
    if path not in sys.path:
        sys.path.insert(0, path)

# user 2026-11-06: 伏地魔1 leads; the other four 70s are members. No apprentices here: nothing is sold or dropped.
LEADER = os.environ.setdefault("SHITU_LEADER", "伏地魔1")
os.environ.setdefault("SHITU_MASTERS", LEADER)
os.environ.setdefault("SHITU_CASTERS", LEADER)
MEMBERS = tuple(os.environ.setdefault("SHITU_APPRENTICES", "伏地魔2,伏地魔3,伏地魔4,欧皇丨花花乀").split(","))
ROLES = (LEADER,) + MEMBERS
