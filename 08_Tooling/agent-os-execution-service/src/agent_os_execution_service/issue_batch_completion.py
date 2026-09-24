"""Finite PR-or-no-PR completion proof for bounded multi-issue missions (#2607).

This is a thin host projection over the existing #2220 single-issue mission
completion admission. It creates no scheduler, persistence, retry, readiness,
or write authority. PR-required lanes delegate to the canonical single-issue
gate; no-PR lanes terminate only from finite caller-supplied canonical evidence.
"""
from __future__ import annotations

from typing import Mapping

from scripts.agent_os_execution_interface.continuation_driver import (
    completion_continuation_payload,
)
from scripts.agent_os_execution_interface.mission_completion_admission import (
    evaluate_mission_completion_admission,
)

_REPOSITORY_GAP = {"yes", "no", "unknown"}
_PR_REQUIRED = {"yes", "no", "unknown"}
_NO_PR_REASONS = {
    "current-main-satisfies",
    "external-only",
    "excluded-surface",
    "authorization-blocked",
    "no-repository-seam",
    "capability-blocked",
    "material-decision-required",
    "duplicate-consolidated",
}


def classify_issue_batch_completion(
    *,
    repository: str,
    issue_number: int,
    lane_evidence: list[dict[str, object]],
) -> dict[str, object]:
    """Require a canonical PR or finite evidence-backed no-PR proof per lane."""
    repo = _repository(repository)
    batch_issue = _issue_number(issue_number, "issue_number")
    if type(lane_evidence) is not list or not lane_evidence:
        raise ValueError("lane_evidence must be a non-empty list")

    lanes = tuple(_classify_lane(repo, value) for value in lane_evidence)
    lane_numbers = tuple(int(item["issue_number"]) for item in lanes)
    if len(set(lane_numbers)) != len(lane_numbers):
        raise ValueError("lane issue numbers must be unique")

    terminal = all(bool(item["terminal"]) for item in lanes)
    unfinished = tuple(item["issue_number"] for item in lanes if not item["terminal"])
    reasons = (
        ("all-selected-lanes-terminal",)
        if terminal
        else tuple(f"lane-{number}-not-terminal" for number in unfinished)
    )
    return {
        "repository": repo,
        "issue_number": batch_issue,
        "lanes": list(lanes),
        "terminal": terminal,
        "unfinished_issue_numbers": list(unfinished),
        "reason_codes": list(reasons),
        "agent_os_continuation": completion_continuation_payload(
            terminal=terminal,
            blocked=False,
            next_action="continue-incomplete-issue-lanes",
            reason_codes=reasons,
        ),
        "github_writes_authorized": False,
        "merge_authorized": False,
        "issue_closure_authorized": False,
        "workflow_authorized": False,
        "production_authorized": False,
        "external_system_write_authorized": False,
    }


def _classify_lane(repository: str, value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("lane evidence entries must be mappings")
    issue = _issue_number(value.get("issue_number"), "lane issue_number")
    current_state = _text(value.get("current_state"), "current_state")
    repository_gap = _finite(value.get("repository_gap"), _REPOSITORY_GAP, "repository_gap")
    implementation_authorized = _bool(value.get("implementation_authorized"), "implementation_authorized")
    pr_required = _finite(value.get("pr_required"), _PR_REQUIRED, "pr_required")
    remaining_owner = _optional_text(value.get("remaining_owner"), "remaining_owner")

    result: dict[str, object] = {
        "issue_number": issue,
        "current_state": current_state,
        "repository_gap": repository_gap,
        "implementation_authorized": implementation_authorized,
        "pr_required": pr_required,
        "pr_number": None,
        "no_pr_reason": None,
        "remaining_owner": remaining_owner,
        "terminal": False,
        "reason_codes": [],
    }

    if repository_gap == "unknown" or pr_required == "unknown":
        result["reason_codes"] = ["lane-terminal-classification-unknown"]
        return result

    if pr_required == "yes":
        if repository_gap != "yes" or not implementation_authorized:
            result["reason_codes"] = ["pr-required-classification-inconsistent"]
            return result
        pr_number = value.get("pr_number")
        if type(pr_number) is not int or pr_number < 1:
            result["reason_codes"] = ["canonical-pr-not-proven"]
            return result
        admission = evaluate_mission_completion_admission(
            repository=repository,
            issue_number=issue,
            branch_exists=_bool(value.get("branch_exists"), "branch_exists"),
            implementation_commit_count=_nonnegative_int(
                value.get("implementation_commit_count"), "implementation_commit_count"
            ),
            draft_pr_exists=_bool(value.get("draft_pr_exists"), "draft_pr_exists"),
            canonical_pr_readback_verified=_bool(
                value.get("canonical_pr_readback_verified"),
                "canonical_pr_readback_verified",
            ),
            capable_route_available=_bool(
                value.get("capable_route_available"), "capable_route_available"
            ),
            subordinate_writes_only=_bool(
                value.get("subordinate_writes_only"), "subordinate_writes_only"
            ),
        )
        result["pr_number"] = pr_number
        result["terminal"] = admission.completion_admissible
        result["reason_codes"] = list(admission.reason_codes)
        return result

    if repository_gap == "yes" and implementation_authorized:
        result["reason_codes"] = ["authorized-repository-gap-cannot-use-no-pr-terminal"]
        return result

    no_pr_reason = value.get("no_pr_reason")
    if type(no_pr_reason) is not str or no_pr_reason not in _NO_PR_REASONS:
        result["reason_codes"] = ["finite-no-pr-reason-not-proven"]
        return result
    canonical_evidence_verified = _bool(
        value.get("canonical_no_pr_evidence_verified"),
        "canonical_no_pr_evidence_verified",
    )
    if not canonical_evidence_verified:
        result["reason_codes"] = ["canonical-no-pr-evidence-not-proven"]
        return result
    if remaining_owner is None:
        result["reason_codes"] = ["remaining-owner-not-proven"]
        return result

    result["no_pr_reason"] = no_pr_reason
    result["terminal"] = True
    result["reason_codes"] = [f"no-pr-terminal:{no_pr_reason}"]
    return result


def _repository(value: object) -> str:
    if type(value) is not str or value.count("/") != 1:
        raise ValueError("repository must use bounded owner/name syntax")
    owner, name = value.split("/", 1)
    if not owner or not name or owner.strip() != owner or name.strip() != name:
        raise ValueError("repository must use bounded owner/name syntax")
    return value


def _issue_number(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} must be a positive built-in integer")
    return value


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value.strip() or value.strip() != value:
        raise ValueError(f"{name} must be non-empty exact text")
    return value


def _optional_text(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _finite(value: object, allowed: set[str], name: str) -> str:
    if type(value) is not str or value not in allowed:
        raise ValueError(f"{name} is unsupported")
    return value


def _bool(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{name} must be built-in bool")
    return value


def _nonnegative_int(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative built-in integer")
    return value


__all__ = ["classify_issue_batch_completion"]
