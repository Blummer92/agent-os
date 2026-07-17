from __future__ import annotations

import argparse
import json
from pathlib import Path

from .models import AcceptanceInput
from .policy import evaluate_acceptance
from .report import exit_code_for, render_report


def _read_text(path: str | None) -> str:
    if not path:
        return ""
    return Path(path).read_text(encoding="utf-8")


def _read_changed_files(path: str | None) -> list[str]:
    text = _read_text(path)
    return [line.strip() for line in text.splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Agent OS issue acceptance checks from local fixture data.")
    parser.add_argument("--issue", required=True, help="Path to the linked issue body markdown.")
    parser.add_argument("--pr-body", required=True, help="Path to the pull request body markdown.")
    parser.add_argument("--changed-files", required=True, help="Path to newline-delimited changed files.")
    parser.add_argument("--diff", help="Optional path to unified diff or patch text.")
    parser.add_argument("--pr-title", default="", help="Optional pull request title.")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)

    report = evaluate_acceptance(
        AcceptanceInput(
            issue_body=_read_text(args.issue),
            pr_body=_read_text(args.pr_body),
            changed_files=_read_changed_files(args.changed_files),
            diff_text=_read_text(args.diff),
        ),
        pr_title=args.pr_title,
    )

    if args.format == "json":
        print(json.dumps(_report_to_dict(report), indent=2, sort_keys=True))
    else:
        print(render_report(report), end="")
    return exit_code_for(report.overall_status)


def _report_to_dict(report):
    return {
        "linked_issue": report.linked_issue,
        "overall_status": report.overall_status.value,
        "checks": [
            {
                "name": check.name,
                "status": check.status.value,
                "message": check.message,
                "evidence": check.evidence,
            }
            for check in report.checks
        ],
        "manual_review_items": report.manual_review_items,
        "evidence": report.evidence,
        "blockers": report.blockers,
        "remaining_risks": report.remaining_risks,
    }


if __name__ == "__main__":
    raise SystemExit(main())
