from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .draft import IssueDraftInput, build_issue_draft
from .validation import (
    DraftExitCode,
    render_validation_preview,
    validate_issue_draft,
    validation_exit_code,
    validation_result_to_dict,
)


class _UsageError(ValueError):
    pass


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _UsageError(message)


def _read_input(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        description="Validate an offline Agent OS issue draft without writing to GitHub."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to a structured JSON draft input, or - to read JSON from stdin.",
    )
    parser.add_argument(
        "--issue-form",
        default=".github/ISSUE_TEMPLATE/agent-os-task.yml",
    )
    parser.add_argument(
        "--label-map",
        default=".github/labeler/agent-os-issue-label-map.yml",
    )
    parser.add_argument(
        "--available-label",
        action="append",
        default=None,
        help="Optional locally supplied repository label. Repeat to provide a complete label set.",
    )
    parser.add_argument(
        "--candidate-summary",
        action="append",
        default=[],
        help="Optional local issue title or summary for advisory duplicate evidence.",
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except _UsageError as exc:
        parser.print_usage(sys.stderr)
        print(f"{parser.prog}: error: {exc}", file=sys.stderr)
        return int(DraftExitCode.INVALID_INPUT_OR_USAGE)

    try:
        payload = json.loads(_read_input(args.input))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"unable to read structured draft input: {exc}", file=sys.stderr)
        return int(DraftExitCode.INVALID_INPUT_OR_USAGE)
    if not isinstance(payload, dict):
        print("structured draft input must be a JSON object", file=sys.stderr)
        return int(DraftExitCode.INVALID_INPUT_OR_USAGE)

    try:
        source_input = IssueDraftInput.from_mapping(payload)
        draft = build_issue_draft(
            payload=source_input,
            issue_form_path=args.issue_form,
            label_map_path=args.label_map,
        )
        result = validate_issue_draft(
            draft,
            source_input,
            args.issue_form,
            available_labels=args.available_label,
            local_issue_summaries=tuple(args.candidate_summary),
        )
    except (OSError, ValueError) as exc:
        print(f"unable to validate structured draft input: {exc}", file=sys.stderr)
        return int(DraftExitCode.INVALID_INPUT_OR_USAGE)

    if args.format == "json":
        print(
            json.dumps(
                validation_result_to_dict(result),
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
        )
    else:
        print(render_validation_preview(result), end="")
    return validation_exit_code(result)


if __name__ == "__main__":
    raise SystemExit(main())
