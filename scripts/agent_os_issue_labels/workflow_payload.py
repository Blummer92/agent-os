from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.agent_os_issue_acceptance.models import Status

_ALLOWED_ISSUE_ACTIONS = {"opened", "edited", "reopened"}


@dataclass(frozen=True)
class WorkflowPayloadResolution:
    status: Status
    issue_number: int | None
    event_action: str
    manual_review_reasons: tuple[str, ...]
    mutation_performed: bool = False
    write_authorized: bool = False


def resolve_workflow_payload(
    *,
    event_name: str,
    payload: Mapping[str, Any] | None,
    manual_issue_number: str | int | None = None,
) -> WorkflowPayloadResolution:
    normalized_event = event_name.strip()
    if normalized_event == "workflow_dispatch":
        issue_number = _positive_integer(manual_issue_number)
        if issue_number is None:
            return _manual_review(
                event_action="manual",
                reason="workflow_dispatch requires a positive issue_number",
            )
        return WorkflowPayloadResolution(
            status=Status.PASS,
            issue_number=issue_number,
            event_action="manual",
            manual_review_reasons=(),
        )

    if normalized_event != "issues":
        return _manual_review(
            event_action="unknown",
            reason=f"unsupported workflow event: {normalized_event or 'missing'}",
        )

    if not isinstance(payload, Mapping):
        return _manual_review(
            event_action="unknown",
            reason="issue event payload must be a JSON object",
        )

    action = payload.get("action")
    event_action = action if isinstance(action, str) and action else "unknown"
    if event_action not in _ALLOWED_ISSUE_ACTIONS:
        return _manual_review(
            event_action=event_action,
            reason=f"unsupported issue action: {event_action}",
        )

    issue = payload.get("issue")
    if not isinstance(issue, Mapping):
        return _manual_review(
            event_action=event_action,
            reason="issue event payload is missing the issue object",
        )

    issue_number = _positive_integer(issue.get("number"))
    if issue_number is None:
        return _manual_review(
            event_action=event_action,
            reason="issue event payload is missing a valid issue number",
        )

    return WorkflowPayloadResolution(
        status=Status.PASS,
        issue_number=issue_number,
        event_action=event_action,
        manual_review_reasons=(),
    )


def render_payload_resolution(
    resolution: WorkflowPayloadResolution,
    *,
    event_name: str,
    commit_sha: str,
) -> str:
    lines = [
        "Issue Label Dry-Run Payload Resolution",
        f"Event name: {event_name}",
        f"Event action: {resolution.event_action}",
        f"Issue number: {resolution.issue_number or 'unresolved'}",
        f"Tested commit SHA: {commit_sha}",
        f"Outcome: {resolution.status.value}",
        f"Mutation performed: {_yes_no(resolution.mutation_performed)}",
        f"Write authorized: {_yes_no(resolution.write_authorized)}",
        "Manual review reasons:",
        *_bullets(resolution.manual_review_reasons),
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Resolve Agent OS issue-label workflow payloads without mutation."
    )
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--event-path", required=True)
    parser.add_argument("--manual-issue-number")
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--github-output", required=True)
    parser.add_argument("--summary-path", required=True)
    args = parser.parse_args(argv)

    payload, payload_error = _load_payload(Path(args.event_path))
    if payload_error:
        resolution = _manual_review(
            event_action="manual" if args.event_name == "workflow_dispatch" else "unknown",
            reason=payload_error,
        )
    else:
        resolution = resolve_workflow_payload(
            event_name=args.event_name,
            payload=payload,
            manual_issue_number=args.manual_issue_number,
        )

    summary_path = Path(args.summary_path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        render_payload_resolution(
            resolution,
            event_name=args.event_name,
            commit_sha=args.commit_sha,
        ),
        encoding="utf-8",
    )
    _write_github_output(Path(args.github_output), resolution)
    return 0


def _load_payload(path: Path) -> tuple[Mapping[str, Any] | None, str | None]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"workflow payload could not be read as JSON: {exc.__class__.__name__}"
    if not isinstance(loaded, Mapping):
        return None, "workflow payload must be a JSON object"
    return loaded, None


def _write_github_output(path: Path, resolution: WorkflowPayloadResolution) -> None:
    values = {
        "status": resolution.status.value,
        "issue-number": str(resolution.issue_number or ""),
        "event-action": resolution.event_action,
    }
    with path.open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def _positive_integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            parsed = int(stripped)
            return parsed if parsed > 0 else None
    return None


def _manual_review(*, event_action: str, reason: str) -> WorkflowPayloadResolution:
    return WorkflowPayloadResolution(
        status=Status.MANUAL_REVIEW,
        issue_number=None,
        event_action=event_action,
        manual_review_reasons=(reason,),
    )


def _bullets(values: tuple[str, ...]) -> list[str]:
    return [f"- {value}" for value in values] if values else ["- none"]


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


if __name__ == "__main__":
    raise SystemExit(main())
