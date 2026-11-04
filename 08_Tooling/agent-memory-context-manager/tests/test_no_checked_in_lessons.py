"""Selection-path source holds no per-lesson identity or registry data (#1729).

Lessons live only in Notion and are discovered through CKR6. The writer catalog
(scripts/agent_os_notion_lessons_write) is out of scope here: it registers
reviewed write authorizations, not selection data.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
SOURCES = (
    ROOT / "08_Tooling/agent-memory-context-manager/src",
    ROOT / "08_Tooling/agent-os-execution-service/src",
)
PER_LESSON = re.compile(r"\b(?:LL|lesson)-[0-9]+\b")


def test_selection_path_source_holds_no_per_lesson_identity_or_registry_data():
    offenders = [
        str(path.relative_to(ROOT))
        for base in SOURCES
        for path in sorted(base.rglob("*"))
        if "__pycache__" not in path.parts
        and path.suffix in {".py", ".json"}
        and (PER_LESSON.search(path.read_text(encoding="utf-8"))
             or (path.suffix == ".json" and "lesson" in path.name.lower()))
    ]
    assert offenders == []
