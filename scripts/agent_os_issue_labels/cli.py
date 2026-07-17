from __future__ import annotations

import argparse
from pathlib import Path

from scripts.agent_os_issue_acceptance.report import exit_code_for

from .checker import evaluate_issue_labels
from .report import render_json, render_label_report


def _read_labels(path: str) -> list[str]:
    return [line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Agent OS issue label checks from local fixture data.")
    parser.add_argument("--issue", required=True, help="Path to issue-form body markdown.")
    parser.add_argument("--labels", required=True, help="Path to newline-delimited existing labels.")
    parser.add_argument("--issue-form", default=".github/ISSUE_TEMPLATE/agent-os-task.yml")
    parser.add_argument("--label-map", default=".github/labeler/agent-os-issue-label-map.yml")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)
    report = evaluate_issue_labels(
        issue_body=Path(args.issue).read_text(encoding="utf-8"),
        existing_labels=_read_labels(args.labels),
        issue_form_path=args.issue_form,
        label_map_path=args.label_map,
    )
    print(render_json(report) if args.format == "json" else render_label_report(report), end="")
    return exit_code_for(report.overall_status)


if __name__ == "__main__":
    raise SystemExit(main())
