from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parents[2]

_TOOLING_SOURCE_DIRS = (
    _REPO_ROOT
    / "08_Tooling"
    / "agent-os-execution-service"
    / "src",
)

for source_dir in reversed(_TOOLING_SOURCE_DIRS):
    source_text = str(source_dir)
    if source_text not in sys.path:
        sys.path.insert(0, source_text)
