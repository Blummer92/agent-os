"""Run the fixed developer-loop validation plan required by #1511.

This entrypoint accepts no caller-supplied arguments. It executes only the
repository-owned focused pytest target and structural validator required by the
semantic-ownership advisory issue.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTEST_TARGET = "tests/test_registry_consistency.py"
STRUCTURE_VALIDATOR = "07_Agent_Tests/validate-repo-structure.sh"


def _run(argv: tuple[str, ...]) -> int:
    completed = subprocess.run(argv, cwd=ROOT, check=False)
    return completed.returncode


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if arguments:
        print("semantic-ownership advisory validation accepts no arguments", file=sys.stderr)
        return 2

    pytest_exit = _run((sys.executable, "-m", "pytest", PYTEST_TARGET))
    if pytest_exit != 0:
        return pytest_exit

    structure_exit = _run(("bash", STRUCTURE_VALIDATOR))
    if structure_exit != 0:
        return structure_exit

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
