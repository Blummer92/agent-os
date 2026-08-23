"""Focused regression for #1309-O: Markdown line count is advisory, not a gate.

Exercises the real `07_Agent_Tests/validate-repo-structure.sh` against this
repository. Line count alone must never fail the structural validator once a
frequently loaded governance Markdown file exceeds the ~200-line target; it
is surfaced only as a non-blocking advisory note.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "07_Agent_Tests" / "validate-repo-structure.sh"


def _run() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_structural_validator_exits_zero_on_current_repository() -> None:
    result = _run()
    assert result.returncode == 0, result.stdout + result.stderr


def test_markdown_line_count_check_never_fails() -> None:
    result = _run()
    assert "PASS - Markdown line-count advisory reviewed" in result.stdout
    assert "FAIL - Markdown" not in result.stdout
    assert "FAIL - All non-exempt Markdown files" not in result.stdout


def test_a_file_over_the_target_is_surfaced_as_advisory_not_a_failure() -> None:
    with tempfile.NamedTemporaryFile(
        dir=ROOT, suffix=".md", prefix="_tmp_advisory_probe_", mode="w"
    ) as handle:
        handle.write("\n".join(f"line {i}" for i in range(250)))
        handle.flush()
        result = _run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ADVISORY - Markdown files over the ~200-line target" in result.stdout
    assert handle.name.split("/")[-1] in result.stdout
    assert "FAIL" not in "\n".join(
        line for line in result.stdout.splitlines() if "Markdown" in line
    )
