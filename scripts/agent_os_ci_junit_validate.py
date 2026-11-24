"""Validate one fresh pytest JUnit report without trusting pytest's exit alone."""
from __future__ import annotations

import sys
from pathlib import Path

from agent_os_ci_junit_diff import junit_outcomes, node_ids


def main() -> int:
    if len(sys.argv) != 2:
        return 2
    try:
        data = Path(sys.argv[1]).read_bytes()
        nodes = node_ids(data)
        outcome = junit_outcomes(data)
    except (OSError, ValueError, TypeError):
        return 2
    if not nodes or outcome["tests"] < 1:
        return 2
    return 1 if outcome["failures"] or outcome["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
