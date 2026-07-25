from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scripts.agent_os_issue_acceptance.report import exit_code_for

from .draft import build_issue_draft, draft_result_to_dict, render_draft_preview


def _read_input(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render an offline Agent OS issue draft preview without writing to GitHub."
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
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)

    try:
        payload = json.loads(_read_input(args.input))
    except (OSError, json.JSONDecodeError) as exc:
        parser.error(f"unable to read structured draft input: {exc}")
    if not isinstance(payload, dict):
        parser.error("structured draft input must be a JSON object")

    result = build_issue_draft(
        payload=payload,
        issue_form_path=args.issue_form,
        label_map_path=args.label_map,
    )
    if args.format == "json":
        print(
            json.dumps(
                draft_result_to_dict(result),
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
        )
    else:
        print(render_draft_preview(result), end="")
    return exit_code_for(result.report.overall_status)


if __name__ == "__main__":
    raise SystemExit(main())
