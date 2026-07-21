"""Thin JSON-only process adapter for RC4 report-only validation (#494 / #254).

Separate from the discovery command ``agent-os-capabilities``. Exit codes:
``0`` pass/warn report · ``1`` fail report · ``2`` manual-review report or
argparse misuse (distinguished by channel: a report always writes JSON to
stdout with empty stderr) · ``3`` unexpected execution error. It never executes
registered code, runs tests, mutates the registry, or decides readiness/approval.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .models import ValidationSeverity
from .serialization import serialize_validation_report
from .validation import validate_registry

_EXIT_FOR_SEVERITY = {
    ValidationSeverity.PASS: 0,
    ValidationSeverity.WARN: 0,
    ValidationSeverity.FAIL: 1,
    ValidationSeverity.MANUAL_REVIEW: 2,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-os-capability-validate",
        description=(
            "Run offline static report-only validation for the Agent OS reusable "
            "capability registry. It does not execute registered code, run tests, "
            "mutate the registry, or determine readiness, approval, or merge authorization."
        ),
    )
    parser.add_argument("--repository-root", type=Path, default=None, help="Repository root (default: current directory).")
    parser.add_argument("--registry", type=Path, default=None, help="Registry path; relative paths resolve against the root.")
    parser.add_argument("--format", choices=("json",), default="json", help="Output format (JSON only).")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)  # argparse exits 2 on misuse, writing usage to stderr
    try:
        root = args.repository_root if args.repository_root is not None else Path.cwd()
        report = validate_registry(root, args.registry)
    except Exception:  # noqa: BLE001 - unexpected execution error boundary
        print("execution error: validation could not complete", file=sys.stderr)
        return 3
    sys.stdout.write(serialize_validation_report(report))
    return _EXIT_FOR_SEVERITY[report.severity]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
