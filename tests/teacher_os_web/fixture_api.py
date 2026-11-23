"""TEST-ONLY Teacher OS API server with a synthetic curriculum (#2801).

This runs the real ``teacher_os_api`` policy and the real governed
``teacher_os`` reader, but replaces the two things a test must never use for
real: the Notion executor (a deterministic stub returning SYNTHETIC records)
and the admission (a test-only ``NotionReadAdmission`` of the shape the reader
requires). Nothing here is Notion evidence, and every title says so.

Usage (from the repository root or the app directory):

    TEACHER_OS_API_SESSION_SECRET=... python3 -I tests/teacher_os_web/fixture_api.py --port 8791 \
        --allowed-origin http://127.0.0.1:4175
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "teacher_os_api", REPO_ROOT / "08_Tooling" / "teacher-os-web" / "server" / "teacher_os_api.py"
)
assert _spec and _spec.loader
teacher_os_api = importlib.util.module_from_spec(_spec)
sys.modules["teacher_os_api"] = teacher_os_api
_spec.loader.exec_module(teacher_os_api)

from scripts.agent_os_notion_read_request.catalog import load_catalog  # noqa: E402
from scripts.agent_os_notion_read_request.models import NotionReadAdmission  # noqa: E402

CATALOG = load_catalog(sources_only=True)
UNIT_DS = CATALOG.source("canonical-unit").data_source_id
LESSON_DS = CATALOG.source("daily-generation-packet").data_source_id

UNIT_COLOR = "5e0c0000-0000-4000-8000-00000000c010"
UNIT_TYPE = "5e0c0000-0000-4000-8000-00000000c020"
UNIT_DRAFT = "5e0c0000-0000-4000-8000-00000000c030"  # Draft status: must never be listed
UNIT_REVIEW = "5e0c0000-0000-4000-8000-00000000c040"  # review required: must never be listed
UNIT_EMPTY = "5e0c0000-0000-4000-8000-00000000c050"  # approved, no lessons
UNIT_FOREIGN = "5e0c0000-0000-4000-8000-00000000c060"  # approved, but a lesson names another unit


def synthetic_test_admission() -> NotionReadAdmission:
    """TEST-ONLY admission with the shape the reader requires. Never shipped."""
    return NotionReadAdmission(
        status="admitted",
        reason_codes=("admitted",),
        repository="Blummer92/agent-os",
        secret_dispatch_authorized=True,
        required_logical_sources=("canonical-unit", "daily-generation-packet"),
    )


def _rich(text: str) -> dict:
    return {"type": "rich_text", "rich_text": [{"plain_text": text}] if text else []}


def unit_record(page_id: str, title: str, status: str = "Active", review: bool = False) -> dict:
    return {"id": page_id, "url": f"https://www.notion.so/{page_id.replace('-', '')}", "properties": {
        "Canonical Unit Name": {"type": "title", "title": [{"plain_text": title}]},
        "Canonical Status": {"type": "select", "select": {"name": status}},
        "Human Review Required": {"type": "checkbox", "checkbox": review},
    }}


def lesson_record(unit_id: str, n: int, *, focus: str, target: str, vocabulary: str = "", relation: str | None = None) -> dict:
    page_id = f"5e0c1e55-0000-4000-8000-{int(unit_id[-3:], 16):06x}{n:06d}"
    return {"id": page_id, "url": f"https://www.notion.so/{page_id.replace('-', '')}", "properties": {
        "Daily Learning Target": _rich(target),
        "Daily Focus": _rich(focus),
        "Key Vocabulary": _rich(vocabulary),
        "Canonical Unit": {"id": "prop-relation", "type": "relation", "relation": [{"id": relation or unit_id}]},
        "Source Evidence": _rich(f"SYNTHETIC test record {n}; not curriculum evidence."),
        "Day / Lesson Number": _rich(f"Day {n}"),
        "Agent Prompt to Run Next": _rich("internal planning text that must never reach the browser"),
    }}


UNITS = [
    unit_record(UNIT_COLOR, "Synthetic Unit — Color Planning (test data)"),
    unit_record(UNIT_TYPE, "Synthetic Unit — Type Hierarchy (test data)"),
    unit_record(UNIT_DRAFT, "Synthetic Draft Unit (must stay hidden)", status="Draft"),
    unit_record(UNIT_REVIEW, "Synthetic Review-Required Unit (must stay hidden)", review=True),
    unit_record(UNIT_EMPTY, "Synthetic Unit — No Lessons Yet (test data)"),
    unit_record(UNIT_FOREIGN, "Synthetic Unit — Foreign Lesson Guard (test data)"),
]
LESSONS = {
    UNIT_COLOR: [
        lesson_record(UNIT_COLOR, 1, focus="Synthetic focus: compare warm and cool palettes", target="Synthetic target: I can name two palette moods.", vocabulary="hue, value"),
        lesson_record(UNIT_COLOR, 2, focus="Synthetic focus: plan a three-color scheme", target="Synthetic target: I can justify one color choice."),
        lesson_record(UNIT_COLOR, 3, focus="Synthetic focus: critique a peer palette", target=""),
    ],
    UNIT_TYPE: [lesson_record(UNIT_TYPE, 1, focus="Synthetic focus: headline versus body type", target="Synthetic target: I can rank three text sizes.")],
    UNIT_EMPTY: [],
    UNIT_FOREIGN: [lesson_record(UNIT_FOREIGN, 1, focus="Synthetic focus: should never render", target="x", relation=UNIT_COLOR)],
}


class StubExecutor:
    """Deterministic stand-in for the #936 adapter output shape. TEST-ONLY."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.factory_calls = 0

    def factory(self):
        self.factory_calls += 1
        return self.execute

    def execute(self, payload):
        self.calls.append(copy.deepcopy(dict(payload)))
        if payload["data_source_id"] == UNIT_DS:
            records = UNITS
        elif payload["data_source_id"] == LESSON_DS:
            records = LESSONS.get(payload["filter"]["relation"]["contains"], [])
        else:
            raise AssertionError("unexpected data source")
        return {"status": "success", "output": {"results": copy.deepcopy(records), "has_more": False, "next_cursor": None}}


def build_api(port: int, secret: str, allowed_origins=frozenset(), stub: StubExecutor | None = None, admission=synthetic_test_admission):
    stub = stub or StubExecutor()
    return teacher_os_api.TeacherOsApi(
        session_secret=secret, port=port, allowed_origins=frozenset(allowed_origins),
        admission_provider=admission, factory_provider=lambda: stub.factory,
        # Test-only: browser suites run two device projects against one server.
        budget=teacher_os_api.ReadBudget(limit=600),
    ), stub


def main() -> int:
    parser = argparse.ArgumentParser(description="TEST-ONLY synthetic Teacher OS API")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--allowed-origin", action="append", default=[])
    args = parser.parse_args()
    secret = os.environ.pop(teacher_os_api.SECRET_ENV, "")
    api, _ = build_api(args.port, secret, args.allowed_origin)
    server = teacher_os_api.serve(api)
    sys.stderr.write(f"TEST-ONLY synthetic teacher-os-api on http://127.0.0.1:{args.port}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
