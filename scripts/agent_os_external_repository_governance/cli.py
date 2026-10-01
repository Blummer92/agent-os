"""CLI wrapper for the ERG2 offline validator (``scripts/erg2-validate``).

Reads each path as untrusted input and prints one JSON evidence report per
document (plus an ``infrastructure-error`` report for unreadable files).
Stdout carries evidence records only; exit code 0 means the CLI ran, not
that validation passed — every report's own ``verdict`` is authoritative.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent_os_external_repository_governance import (  # noqa: E402
    validate_erg_document,
)
from agent_os_external_repository_governance.models import (  # noqa: E402
    ErgCheck,
    ErgVerdict,
    report_from_checks,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Offline External Repository Governance (ERG) validator. "
            "Evidence only; authorizes nothing."
        )
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help="consumer profile or registry YAML documents to validate",
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        help="repository root for symlink-containment checks",
    )
    parser.add_argument(
        "--schema-dir",
        default=None,
        help="directory containing the #580 contract schemas",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    for path in args.paths:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            report = report_from_checks(
                subject=path,
                document_kind=None,
                contract_version=None,
                checks=[
                    ErgCheck(
                        name="input-read",
                        verdict=ErgVerdict.INFRASTRUCTURE_ERROR,
                        detail=f"could not read input as UTF-8 text: {exc}",
                    )
                ],
                evaluated=(),
                not_evaluated=(
                    "consumer-repository-behavior",
                    "live-runtime-state",
                    "network-or-github-state",
                    "declared-document-existence",
                    "approval-or-readiness",
                ),
            )
        else:
            report = validate_erg_document(
                text,
                source=path,
                repo_root=args.repo_root,
                schema_dir=args.schema_dir,
            )
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
