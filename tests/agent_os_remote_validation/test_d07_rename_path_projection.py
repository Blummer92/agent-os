"""Regression for the actual filters in the validation workflow."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/agent-os-validation.yml"
_FILE_FILTERS = re.compile(r"""/files\?per_page=100"\s+(?:\\\s+)?--jq '([^']+)'""")


def _project(filter_: str, entries: list[dict[str, str]]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("jq", "-r", filter_),
        input=json.dumps(entries),
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.skipif(shutil.which("jq") is None, reason="workflow filter requires jq")
def test_validation_workflow_preserves_both_rename_endpoints():
    filters = _FILE_FILTERS.findall(_WORKFLOW.read_text(encoding="utf-8"))
    assert len(filters) == 2
    assert filters[0] == filters[1]
    changes = [
        {
            "filename": "suite-b/src/file.py",
            "status": "renamed",
            "previous_filename": "suite-a/src/file.py",
        },
        {"filename": "notes space.md", "status": "modified", "previous_filename": "ignored"},
        {"filename": "suite-a/old.py", "status": "removed"},
    ]
    projected = _project(filters[0], changes)
    assert projected.returncode == 0, projected.stderr
    assert projected.stdout.splitlines() == [
        "suite-b/src/file.py", "suite-a/src/file.py", "notes space.md", "suite-a/old.py",
    ]
    for invalid in (
        {"filename": "suite-b/new.py", "status": "renamed"},
        {"filename": "invalid\nname.py", "status": "modified"},
    ):
        assert _project(filters[0], [invalid]).returncode != 0
