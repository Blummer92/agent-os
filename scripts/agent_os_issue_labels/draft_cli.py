from __future__ import annotations

import argparse
import sys
from pathlib import Path

from scripts.agent_os_issue_acceptance.models import Status
from scripts.agent_os_issue_acceptance.report import exit_code_for

from .issue_draft import (
    IssueDraftInputError,
    build_issue_draft,
    load_issue_draft_input,
    render_issue_draft_error,
    render_issue_draft_json,
    render_issue_draft_text,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a deterministic, offline Agent OS issue draft preview."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Structured YAML/JSON input path, or '-' to read stdin.",
    )
    parser.add_argument(
        "--issue-form",
        default=".github/ISSUE_TEMPLATE/agent-os-task.yml",
    )
    parser.add_argument(
        "--label-map",
        default=".github/labeler/agent-os-issue-label-map.yml",
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)

    try:
        input_text = (
            sys.stdin.read()
            if args.input == "-"
            else Path(args.input).read_text(encoding="utf-8")
        )
        draft_input = load_issue_draft_input(input_text)
        result = build_issue_draft(
            draft_input,
            issue_form_path=args.issue_form,
            label_map_path=args.label_map,
        )
    except (IssueDraftInputError, OSError, ValueError) as exc:
        print(render_issue_draft_error(str(exc), output_format=args.format), end="")
        return exit_code_for(Status.FAIL)

    rendered = (
        render_issue_draft_json(result)
        if args.format == "json"
        else render_issue_draft_text(result)
    )
    print(rendered, end="")
    return exit_code_for(result.overall_status)


if __name__ == "__main__":
    raise SystemExit(main())
