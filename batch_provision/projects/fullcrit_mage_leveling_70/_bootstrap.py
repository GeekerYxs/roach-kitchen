"""Make the independent project runnable while resolving shared shitu building blocks."""
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parent
REPO = PROJECT.parents[2]
SHITU = REPO / "batch_provision" / "research" / "shitu"
BATCH = REPO / "batch_provision"

for path in (str(SHITU), str(BATCH)):
    if path not in sys.path:
        sys.path.insert(0, path)
