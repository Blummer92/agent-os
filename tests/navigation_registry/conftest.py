"""Path wiring for navigation_registry connector tests (#3254).

The visual-asset-* tooling packages (ingestion coordinator, drive writer,
notion writer) live in 08_Tooling/<pkg>/src and are not on the root
PYTHONPATH that canonical CI uses for root suites. The registration
composition module composes those REAL packages, so their src dirs are
added here (directory-scoped; no name collides with root src packages).
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _pkg in (
    "visual-asset-ingestion-coordinator",
    "visual-asset-drive-writer",
    "visual-asset-notion-writer",
):
    _src = str(_REPO_ROOT / "08_Tooling" / _pkg / "src")
    if _src not in sys.path:
        sys.path.insert(0, _src)
