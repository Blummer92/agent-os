from __future__ import annotations

import argparse
import json
from pathlib import Path

from .planner import application_plan_to_dict, plan_label_application, render_application_plan


def _read_lines(path: str) -> list[str]:
    return [line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plan safe Agent OS issue-label additions without mutating GitHub.")
    parser.add_argument("--issue", required=True, help="Path to issue-form body markdown.")
    parser.add_argument("--labels", required=True, help="Path to newline-delimited existing labels.")
    parser.add_argument("--available-labels", required=True, help="Path to newline-delimited repository labels.")
    parser.add_argument("--issue-number", required=True, type=int)
    parser.add_argument("--event-type", required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--issue-form", default=".github/ISSUE_TEMPLATE/agent-os-task.yml")
    parser.add_argument("--label-map", default=".github/labeler/agent-os-issue-label-map.yml")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)
    if args.issue_number <= 0:
        parser.error("--issue-number must be a positive integer")

    plan = plan_label_application(
        issue_body=Path(args.issue).read_text(encoding="utf-8"),
        existing_labels=_read_lines(args.labels),
        available_labels=_read_lines(args.available_labels),
        issue_form_path=args.issue_form,
        label_map_path=args.label_map,
    )
    if args.format == "json":
        payload = application_plan_to_dict(plan)
        payload.update(
            {
                "issue_number": args.issue_number,
                "event_type": args.event_type,
                "commit_sha": args.commit_sha,
                "exit_status": 0,
            }
        )
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            render_application_plan(
                plan,
                issue_number=args.issue_number,
                event_type=args.event_type,
                commit_sha=args.commit_sha,
                exit_status=0,
            ),
            end="",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
