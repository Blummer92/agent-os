"""Use canonical source packages for the root pytest developer loop."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for source in (ROOT / "src", ROOT / "08_Tooling/workflow-scheduler/src"):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
