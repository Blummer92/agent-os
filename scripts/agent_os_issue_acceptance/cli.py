from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .acceptance_report_transport import (
    build_acceptance_report_transport,
    render_transport_summary,
)
from .legacy_preflight import (
    evaluate_legacy_preflight,
    legacy_preflight_to_dict,
    render_legacy_preflight,
)
from .models import AcceptanceInput, LinkedIssueParseStatus
from .policy import evaluate_acceptance
from .report import exit_code_for, render_report


def _read_text(path: str | None) -> str:
    if not path:
        return ""
    return Path(path).read_text(encoding="utf-8")


def _read_bytes(path: str | None) -> bytes:
    if not path:
        return b""
    return Path(path).read_bytes()


def _read_changed_files(path: str | None) -> list[str]:
    text = _read_text(path)
    return [line.strip() for line in text.splitlines() if line.strip()]


def _read_json(path: str) -> object:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Agent OS issue acceptance checks from local fixture data.")
    parser.add_argument("--issue", help="Path to the linked issue body markdown.")
    parser.add_argument("--pr-body", help="Path to the pull request body markdown.")
    parser.add_argument("--changed-files", help="Path to newline-delimited changed files.")
    parser.add_argument("--diff", help="Optional path to unified diff or patch text.")
    parser.add_argument("--pr-title", default="", help="Optional pull request title.")
    parser.add_argument(
        "--legacy-preflight-snapshot",
        help="Optional path to a bounded read-only legacy issue snapshot JSON file.",
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--transport-repository", dest="transport_repository")
    parser.add_argument("--transport-issue-number", type=int, dest="transport_issue_number")
    parser.add_argument("--transport-issue-body", dest="transport_issue_body")
    parser.add_argument("--transport-issue-body-file", dest="transport_issue_body_file")
    parser.add_argument("--transport-issue-body-sha256", dest="transport_issue_body_sha256")
    parser.add_argument(
        "--transport-issue-body-retrieval-failed",
        action="store_true",
        dest="transport_issue_body_retrieval_failed",
    )
    parser.add_argument("--transport-pr-number", type=int, dest="transport_pr_number")
    parser.add_argument("--transport-pr-head-sha", dest="transport_pr_head_sha")
    parser.add_argument("--transport-evaluator-sha", dest="transport_evaluator_sha")
    parser.add_argument("--transport-workflow-run-id", dest="transport_workflow_run_id")
    parser.add_argument(
        "--transport-workflow-run-attempt",
        type=int,
        dest="transport_workflow_run_attempt",
    )
    parser.add_argument("--transport-fresh-issue-body", dest="transport_fresh_issue_body")
    parser.add_argument("--transport-fresh-issue-body-file", dest="transport_fresh_issue_body_file")
    parser.add_argument(
        "--transport-fresh-pr-head-sha",
        dest="transport_fresh_pr_head_sha",
    )
    parser.add_argument("--transport-observed-at", dest="transport_observed_at")
    parser.add_argument(
        "--transport-contract-version",
        dest="transport_contract_version",
        default="agent-os-acceptance-report-transport/v1",
    )
    args = parser.parse_args(argv)

    if args.legacy_preflight_snapshot:
        mixed = [
            name
            for name, value in (
                ("--issue", args.issue),
                ("--pr-body", args.pr_body),
                ("--changed-files", args.changed_files),
                ("--diff", args.diff),
            )
            if value
        ]
        if mixed or args.pr_title:
            parser.error(
                "--legacy-preflight-snapshot cannot be combined with acceptance input arguments"
            )
        try:
            report = evaluate_legacy_preflight(_read_json(args.legacy_preflight_snapshot))
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
            parser.error(f"invalid legacy preflight snapshot: {error}")
        if args.format == "json":
            print(json.dumps(legacy_preflight_to_dict(report), indent=2, sort_keys=True))
        else:
            print(render_legacy_preflight(report), end="")
        return 0

    missing = [
        option
        for option, value in (
            ("--issue", args.issue),
            ("--pr-body", args.pr_body),
            ("--changed-files", args.changed_files),
        )
        if not value
    ]
    if missing:
        parser.error(f"the following arguments are required: {', '.join(missing)}")

    report = evaluate_acceptance(
        AcceptanceInput(
            issue_body=_read_text(args.issue),
            pr_body=_read_text(args.pr_body),
            changed_files=_read_changed_files(args.changed_files),
            diff_text=_read_text(args.diff),
        ),
        pr_title=args.pr_title,
    )

    transport_payload = None
    if any(
        getattr(args, name) not in (None, "")
        for name in (
            "transport_repository",
            "transport_issue_number",
            "transport_issue_body",
            "transport_issue_body_file",
            "transport_issue_body_sha256",
            "transport_pr_number",
            "transport_pr_head_sha",
            "transport_evaluator_sha",
            "transport_workflow_run_id",
            "transport_workflow_run_attempt",
            "transport_issue_body_retrieval_failed",
            "transport_fresh_issue_body",
            "transport_fresh_issue_body_file",
            "transport_fresh_pr_head_sha",
            "transport_observed_at",
        )
    ):
        issue_body = args.transport_issue_body or ""
        if args.transport_issue_body_file:
            issue_body = _read_bytes(args.transport_issue_body_file).decode("utf-8")
        fresh_issue_body = args.transport_fresh_issue_body
        if args.transport_fresh_issue_body_file:
            fresh_issue_body = _read_bytes(args.transport_fresh_issue_body_file).decode("utf-8")
        transport = build_acceptance_report_transport(
            report=report,
            repository=args.transport_repository or "",
            issue_number=args.transport_issue_number,
            issue_body=issue_body,
            issue_body_sha256=args.transport_issue_body_sha256 or "",
            pr_number=args.transport_pr_number,
            pr_head_sha=args.transport_pr_head_sha or "",
            evaluator_sha=args.transport_evaluator_sha or "",
            workflow_run_id=args.transport_workflow_run_id or "",
            workflow_run_attempt=args.transport_workflow_run_attempt or 0,
            fresh_issue_body=fresh_issue_body,
            fresh_pr_head_sha=args.transport_fresh_pr_head_sha,
            issue_body_retrieval_failed=args.transport_issue_body_retrieval_failed,
            contract_version=args.transport_contract_version,
            observed_at=args.transport_observed_at,
        )
        transport_payload = {
            "report": _report_to_dict(report),
            "transport": transport.to_envelope(),
            "transport_summary": render_transport_summary(transport, report),
        }

    if transport_payload is not None:
        if args.format == "json":
            print(json.dumps(transport_payload, indent=2, sort_keys=True))
        else:
            print(render_report(report), end="")
            print(transport_payload["transport_summary"], end="")
    elif args.format == "json":
        print(json.dumps(_report_to_dict(report), indent=2, sort_keys=True))
    else:
        print(render_report(report), end="")
    return exit_code_for(report.overall_status)


def _report_to_dict(report):
    result = report.linked_issue_result
    if result is None:
        linked_issue_status = (
            LinkedIssueParseStatus.RESOLVED.value
            if report.linked_issue is not None
            else LinkedIssueParseStatus.NONE.value
        )
        reasons = []
        candidates = []
    else:
        linked_issue_status = result.status.value
        reasons = result.reasons
        candidates = [
            {
                "issue_number": candidate.issue_number,
                "repository": candidate.repository,
                "keyword": candidate.keyword,
                "source": candidate.source,
                "position": candidate.position,
                "target": candidate.normalized_target,
                "explicit": candidate.explicit,
            }
            for candidate in [*result.explicit_candidates, *result.bare_references]
        ]

    return {
        "linked_issue": report.linked_issue,
        "linked_issue_status": linked_issue_status,
        "linked_issue_reasons": reasons,
        "linked_issue_candidates": candidates,
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
