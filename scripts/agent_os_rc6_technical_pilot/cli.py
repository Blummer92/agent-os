"""Command-line entry point for the manual RC6 technical pilot."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .runner import (
    DEFAULT_FIXTURE,
    FixtureContractError,
    PilotExecutionError,
    load_frozen_package,
    resolve_git_head,
    run_pilot,
    validate_exact_sha,
    write_artifacts,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run or validate the frozen RC6 technical pilot")
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--frozen-sha", required=True)
    parser.add_argument("--runner-sha", default="unrecorded")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate fixture and SHA inputs without executing T01-T24.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        actual_head = resolve_git_head(args.repository_root)
        validate_exact_sha(args.frozen_sha, actual_head)
        package = load_frozen_package(args.fixture)
        if args.validate_only:
            print(
                json.dumps(
                    {
                        "result": "pass",
                        "mode": "validate-only",
                        "case_total": len(package["cases"]),
                        "tested_sha": actual_head,
                    },
                    sort_keys=True,
                )
            )
            return 0
        if args.output_dir is None:
            raise PilotExecutionError("--output-dir is required unless --validate-only is used")
        run = run_pilot(
            args.repository_root,
            supplied_sha=args.frozen_sha,
            actual_head_sha=actual_head,
            fixture_path=args.fixture,
            runner_sha=args.runner_sha,
        )
        json_path, markdown_path = write_artifacts(run, args.output_dir)
        print(f"result={run.payload['overall_result']}")
        print(f"tested_sha={run.payload['tested_sha']}")
        print(f"case_total={run.payload['case_total']}")
        print(f"case_passed={run.payload['case_passed']}")
        print(f"json_artifact={json_path}")
        print(f"markdown_artifact={markdown_path}")
        return run.exit_code
    except (FixtureContractError, PilotExecutionError, OSError, ValueError) as exc:
        print(f"RC6 technical pilot failed closed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
