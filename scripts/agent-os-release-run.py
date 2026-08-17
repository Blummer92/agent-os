#!/usr/bin/env python3
"""Deterministic, offline release-run state evaluator for Agent OS."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from agent_os_issue_acceptance.validation_failure_classifier import (
    EvidenceState,
    RequirementResult,
    ValidationFailureClassification,
    ValidationFailureEvidence,
    classify_validation_failure,
)

SCHEMA_NAME = "agent-os-release-run"
SCHEMA_VERSION = "1.2.0"
CLASSIFICATIONS = {"READY_FOR_MERGE_AUTHORIZATION", "NEEDS_FIX", "BLOCKED"}
SUCCESS_CHECKS = {"success"}
MERGE_METHODS = {"merge", "squash", "rebase"}
BRANCH_STATES = {"current", "behind", "conflicted", "unknown"}
PR_LIFECYCLE_STATES = {"draft", "ready", "merged", "closed"}
REQUIRED_REFRESH_INVALIDATIONS = {
    "branch-freshness",
    "lifecycle-reconciliation",
    "merge-authorization",
    "ready-for-review",
    "tested-sha",
}


@dataclass
class ReleaseRunState:
    schema_name: str = SCHEMA_NAME
    schema_version: str = SCHEMA_VERSION
    repository: str = ""
    pull_request_number: int = 0
    issue_number: int = 0
    expected_head_sha: str = ""
    observed_head_sha: str = ""
    current_main_sha: str = ""
    validation_head_sha: str = ""
    branch_state: str = "unknown"
    phase: str = "preflight"
    classification: str = "BLOCKED"
    pr_state: str = "open"
    pr_lifecycle_state: str = "draft"
    issue_state: str = "open"
    checkpoint_phase: str | None = None
    checkpoint_head_sha: str | None = None
    checkpoint_pr_lifecycle_state: str | None = None
    external_transition: str | None = None
    changed_files: list[str] = field(default_factory=list)
    required_checks: dict[str, str] = field(default_factory=dict)
    canonical_required_checks: list[str] = field(default_factory=list)
    authoritative_aggregate_check: str = ""
    authorized_merge_method: str = ""
    validation_failure_classification: str | None = None
    review_thread_summary: dict[str, int] = field(default_factory=dict)
    ready_for_review_authorized: bool = False
    merge_authorized: bool = False
    issue_closure_authorized: bool = False
    lifecycle_reconciliation_status: str | None = None
    lifecycle_invocation_reason: str | None = None
    next_action: str = "stop"
    blockers: list[str] = field(default_factory=list)
    side_effects_performed: list[str] = field(default_factory=list)


def evaluate_release_run(evidence: dict[str, Any]) -> ReleaseRunState:
    """Project fresh caller-supplied release evidence into one governed next state."""
    lifecycle = evidence.get("lifecycle_reconciliation")
    if lifecycle is not None and not isinstance(lifecycle, dict):
        raise TypeError("lifecycle_reconciliation must be object or null")

    state = ReleaseRunState(
        repository=str(evidence.get("repository", "")),
        pull_request_number=_int_or_zero(evidence.get("pull_request_number")),
        issue_number=_int_or_zero(evidence.get("issue_number")),
        expected_head_sha=str(evidence.get("expected_head_sha", "")),
        observed_head_sha=str(evidence.get("observed_head_sha", "")),
        current_main_sha=str(evidence.get("current_main_sha", "")),
        validation_head_sha=str(evidence.get("validation_head_sha", "")),
        branch_state=str(evidence.get("branch_state", "unknown")),
        pr_state=str(evidence.get("pr_state", "open")),
        pr_lifecycle_state=str(evidence.get("pr_lifecycle_state", "draft")),
        issue_state=str(evidence.get("issue_state", "open")),
        checkpoint_phase=_optional_string(evidence.get("checkpoint_phase")),
        checkpoint_head_sha=_optional_string(evidence.get("checkpoint_head_sha")),
        checkpoint_pr_lifecycle_state=_optional_string(
            evidence.get("checkpoint_pr_lifecycle_state")
        ),
        changed_files=_sorted_strings(evidence.get("changed_files", [])),
        required_checks=_sorted_string_map(evidence.get("required_checks", {})),
        canonical_required_checks=_sorted_strings(
            evidence.get("canonical_required_checks", [])
        ),
        authoritative_aggregate_check=str(
            evidence.get("authoritative_aggregate_check", "")
        ),
        authorized_merge_method=str(evidence.get("authorized_merge_method", "")),
        review_thread_summary=_sorted_int_map(
            evidence.get("review_thread_summary", {})
        ),
        ready_for_review_authorized=_exact_bool(
            evidence.get("ready_for_review_authorized", False)
        ),
        merge_authorized=_exact_bool(evidence.get("merge_authorized", False)),
        issue_closure_authorized=_exact_bool(
            evidence.get("issue_closure_authorized", False)
        ),
        lifecycle_reconciliation_status=(
            str(lifecycle.get("reconciliation_status", "")) if lifecycle else None
        ),
        lifecycle_invocation_reason=(
            str(lifecycle.get("invocation_reason", "")) if lifecycle else None
        ),
        side_effects_performed=_ordered_strings(
            evidence.get("side_effects_performed", [])
        ),
    )

    allowed = set(_sorted_strings(evidence.get("allowed_changed_files", [])))
    if not state.repository or not state.pull_request_number or not state.issue_number:
        state.blockers.append("missing release-run identity")
    if state.pr_state not in {"open", "merged", "closed"}:
        state.blockers.append(f"unsupported PR state: {state.pr_state}")
    if state.pr_lifecycle_state not in PR_LIFECYCLE_STATES:
        state.blockers.append(
            f"unsupported PR lifecycle state: {state.pr_lifecycle_state}"
        )
    if state.expected_head_sha != state.observed_head_sha:
        state.blockers.append("exact-head drift")
    if allowed and not set(state.changed_files).issubset(allowed):
        state.blockers.append("changed-file scope drift")
    if state.authorized_merge_method not in MERGE_METHODS:
        state.blockers.append("authorized merge method is missing or unsupported")

    external_terminal = _detect_external_transition(state, evidence)
    if external_terminal:
        return state

    if state.pr_state == "open":
        _validate_branch_freshness(state, evidence)
        _validate_refresh_receipt(state, evidence.get("branch_refresh_result"))
        _validate_validation_head(state)
        _validate_lifecycle_receipt(state, lifecycle)

    _validate_authoritative_checks(state)
    _classify_failed_validation(state, evidence.get("validation_failure_evidence"))

    if evidence.get("prior_head_only_green", False) is True:
        state.blockers.append("prior-head checks cannot satisfy current head")
    if evidence.get("requested_changes", False) is True:
        state.blockers.append("requested-changes review is unresolved")
    if int(state.review_thread_summary.get("blocking_unresolved", 0)) > 0:
        state.blockers.append("blocking review conversation is unresolved")

    if state.blockers:
        state.phase = "release-review"
        state.classification = (
            "NEEDS_FIX"
            if state.validation_failure_classification
            == ValidationFailureClassification.PR_REGRESSION.value
            else "BLOCKED"
        )
        if "branch is behind current main" in state.blockers:
            state.next_action = "route-through-gh-life3-1187"
        elif any(item.startswith("managed-label reconciliation") for item in state.blockers):
            state.next_action = "reconcile-managed-labels-via-gh-life2-1038"
        elif state.external_transition:
            state.next_action = "reacquire-and-reclassify-external-transition"
        else:
            state.next_action = (
                "repair-within-authorized-scope-and-revalidate"
                if state.classification == "NEEDS_FIX"
                else "resolve-or-reacquire-blocking-evidence"
            )
        return state

    if state.pr_state == "merged":
        if (
            evidence.get("merge_commit_verified", False) is not True
            or evidence.get("main_verified", False) is not True
        ):
            state.phase = "post-merge-verification"
            state.classification = "BLOCKED"
            state.blockers.append("post-merge verification incomplete")
            state.next_action = "verify-merge-and-main"
        elif not state.issue_closure_authorized:
            state.phase = "issue-closure-authorization-pause"
            state.classification = "BLOCKED"
            state.next_action = "request-issue-closure-authorization"
        elif "completion-comment" not in state.side_effects_performed:
            state.phase = "issue-closure"
            state.classification = "BLOCKED"
            state.next_action = "post-completion-comment-before-closure"
        else:
            state.phase = "issue-closure"
            state.classification = "READY_FOR_MERGE_AUTHORIZATION"
            state.next_action = "close-issue"
        return state

    if state.pr_state == "closed":
        state.phase = "external-transition"
        state.classification = "BLOCKED"
        state.external_transition = "closed"
        state.blockers.append("pull request is closed")
        state.next_action = "terminal-external-transition-closed"
        return state

    if state.pr_lifecycle_state == "draft":
        state.phase = "ready-for-review"
        state.classification = "BLOCKED"
        if not state.ready_for_review_authorized:
            state.next_action = "request-ready-for-review-authorization"
        else:
            state.next_action = "perform-ready-for-review-at-exact-head"
        return state

    if not state.merge_authorized:
        state.phase = "merge-authorization-pause"
        state.classification = "READY_FOR_MERGE_AUTHORIZATION"
        state.next_action = "request-merge-authorization"
    else:
        state.phase = "merge"
        state.classification = "READY_FOR_MERGE_AUTHORIZATION"
        state.next_action = (
            f"merge-at-expected-head-with-{state.authorized_merge_method}"
        )
    return state


def _detect_external_transition(state: ReleaseRunState, evidence: dict[str, Any]) -> bool:
    checkpoint_state = state.checkpoint_pr_lifecycle_state
    if checkpoint_state and checkpoint_state not in PR_LIFECYCLE_STATES:
        state.blockers.append("checkpoint lifecycle state is unsupported")
        return False

    refresh = evidence.get("branch_refresh_result")
    refresh_proves_head = _refresh_proves_head_transition(
        refresh, state.checkpoint_head_sha, state.observed_head_sha
    )
    if (
        state.checkpoint_head_sha
        and state.checkpoint_head_sha != state.observed_head_sha
        and not refresh_proves_head
    ):
        state.phase = "external-transition"
        state.classification = "BLOCKED"
        state.external_transition = "unexpected-head-movement"
        state.blockers.append("unexpected head movement since checkpoint")
        state.next_action = "reacquire-and-reclassify-external-transition"
        return True

    if (
        checkpoint_state == "draft"
        and state.pr_lifecycle_state == "ready"
        and "ready-for-review" not in state.side_effects_performed
    ):
        state.phase = "external-transition"
        state.classification = "BLOCKED"
        state.external_transition = "draft-to-ready"
        state.blockers.append("Draft to Ready occurred outside current governed operation")
        state.next_action = "reacquire-and-reclassify-current-ready-state"
        return True

    if (
        state.pr_state == "merged"
        and checkpoint_state not in {None, "merged"}
        and "merge" not in state.side_effects_performed
    ):
        state.phase = "external-transition"
        state.classification = "BLOCKED"
        state.external_transition = "merged"
        state.blockers.append("pull request was merged outside current governed operation")
        state.next_action = "terminal-external-transition-merged"
        return True

    if (
        state.pr_state == "closed"
        and checkpoint_state not in {None, "closed"}
        and "close-pr" not in state.side_effects_performed
    ):
        state.phase = "external-transition"
        state.classification = "BLOCKED"
        state.external_transition = "closed"
        state.blockers.append("pull request was closed outside current governed operation")
        state.next_action = "terminal-external-transition-closed"
        return True
    return False


def _validate_branch_freshness(state: ReleaseRunState, evidence: dict[str, Any]) -> None:
    if not _is_sha40(state.current_main_sha):
        state.blockers.append("current main SHA is missing or invalid")
    if state.branch_state not in BRANCH_STATES:
        state.blockers.append(f"unsupported branch state: {state.branch_state}")
        return
    if state.branch_state == "behind":
        state.blockers.append("branch is behind current main")
    elif state.branch_state == "conflicted":
        state.blockers.append("branch is conflicted")
    elif state.branch_state == "unknown":
        state.blockers.append("branch freshness is unknown")


def _validate_validation_head(state: ReleaseRunState) -> None:
    if not _is_sha40(state.validation_head_sha):
        state.blockers.append("exact-head validation identity is missing or invalid")
    elif state.validation_head_sha != state.observed_head_sha:
        state.blockers.append("authoritative validation is bound to a stale head")


def _validate_lifecycle_receipt(
    state: ReleaseRunState, lifecycle: dict[str, Any] | None
) -> None:
    if lifecycle is None:
        state.blockers.append("managed-label reconciliation receipt is missing")
        return
    if lifecycle.get("reconciliation_status") != "converged":
        state.blockers.append("managed-label reconciliation is not converged")
    verified_head = lifecycle.get("verified_head_sha")
    if verified_head != state.observed_head_sha:
        state.blockers.append("managed-label reconciliation is bound to a stale head")
    invocation = lifecycle.get("invocation_reason")
    if invocation not in {
        "validation-terminal",
        "draft-ready-transition",
        "branch-state-rechecked",
        "final-state-readback",
    }:
        state.blockers.append("managed-label reconciliation invocation is not release-current")


def _validate_refresh_receipt(state: ReleaseRunState, raw: Any) -> None:
    if raw is None:
        return
    if not isinstance(raw, dict):
        raise TypeError("branch_refresh_result must be object or null")
    if raw.get("status") != "converged":
        state.blockers.append("#1187 refresh result is not converged")
        return
    if raw.get("new_head_sha") != state.observed_head_sha:
        state.blockers.append("#1187 refresh result does not match current head")
    invalidated = raw.get("invalidated_head_evidence", [])
    if not isinstance(invalidated, (list, tuple)):
        state.blockers.append("#1187 invalidation receipt is malformed")
    elif not REQUIRED_REFRESH_INVALIDATIONS.issubset(set(invalidated)):
        state.blockers.append("#1187 refresh did not prove required head-evidence invalidation")
    validation = raw.get("validation")
    if not isinstance(validation, dict):
        state.blockers.append("#1187 refreshed-head validation receipt is missing")
    else:
        if validation.get("head_sha") != state.observed_head_sha:
            state.blockers.append("#1187 refreshed-head validation is stale")
        if validation.get("status") != "green":
            state.blockers.append("#1187 refreshed-head validation is not green")
    lifecycle = raw.get("lifecycle_reconciliation")
    if not isinstance(lifecycle, dict) or lifecycle.get("reconciliation_status") != "converged":
        state.blockers.append("#1187 post-refresh lifecycle reconciliation is not converged")


def _refresh_proves_head_transition(raw: Any, old_head: str | None, new_head: str) -> bool:
    if not isinstance(raw, dict) or raw.get("status") != "converged":
        return False
    return raw.get("old_head_sha") == old_head and raw.get("new_head_sha") == new_head


def _validate_authoritative_checks(state: ReleaseRunState) -> None:
    if not state.canonical_required_checks:
        state.blockers.append("canonical required validation set is unavailable")
        return
    if not state.authoritative_aggregate_check:
        state.blockers.append("authoritative aggregate check identity is unavailable")
        return
    if state.authoritative_aggregate_check not in state.canonical_required_checks:
        state.blockers.append(
            "authoritative aggregate check is not in canonical required validation set"
        )
    for name in state.canonical_required_checks:
        status = state.required_checks.get(name)
        if status is None:
            state.blockers.append(f"required check {name} is missing")
        elif status.lower() not in SUCCESS_CHECKS:
            state.blockers.append(f"required check {name} is {status.lower()}")


def _classify_failed_validation(state: ReleaseRunState, raw: Any) -> None:
    failed_required = [
        name
        for name in state.canonical_required_checks
        if state.required_checks.get(name, "missing").lower() not in SUCCESS_CHECKS
    ]
    if not failed_required or not isinstance(raw, dict):
        return
    try:
        failure = ValidationFailureEvidence(
            pr_head_sha=str(raw["pr_head_sha"]),
            comparison_main_sha=raw.get("comparison_main_sha"),
            command=str(raw["command"]),
            failed_requirement=raw.get("failed_requirement"),
            error_excerpt=raw.get("error_excerpt"),
            exit_code=raw.get("exit_code"),
            source_identifiers=tuple(raw.get("source_identifiers", ())),
            evidence_state=EvidenceState(str(raw.get("evidence_state", "current"))),
            comparable_pr_and_main=_exact_bool(
                raw.get("comparable_pr_and_main", False)
            ),
            same_requirement_executed=_exact_bool(
                raw.get("same_requirement_executed", False)
            ),
            pr_requirement_result=RequirementResult(
                str(raw.get("pr_requirement_result", "fail"))
            ),
            main_requirement_result=RequirementResult(
                str(raw.get("main_requirement_result", "unavailable"))
            ),
            materially_equivalent_failure=_exact_bool(
                raw.get("materially_equivalent_failure", False)
            ),
            pr_scope_attribution_supported=_exact_bool(
                raw.get("pr_scope_attribution_supported", False)
            ),
            infrastructure_configuration_failure_proven=_exact_bool(
                raw.get("infrastructure_configuration_failure_proven", False)
            ),
            infrastructure_authorization_boundary=raw.get(
                "infrastructure_authorization_boundary"
            ),
        )
        result = classify_validation_failure(failure)
    except (KeyError, TypeError, ValueError):
        return
    state.validation_failure_classification = result.classification.value


def _is_sha40(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 40 and all(
        char in "0123456789abcdef" for char in value.lower()
    )


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("optional checkpoint values must be strings or null")
    return value


def _exact_bool(value: Any) -> bool:
    if type(value) is not bool:
        raise TypeError("authorization and evidence flags must be bool")
    return value


def _int_or_zero(value: Any) -> int:
    if value is None:
        return 0
    if type(value) is not int:
        raise TypeError("numeric identity must be int")
    return value


def _sorted_strings(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise TypeError("expected string sequence")
    if any(not isinstance(item, str) for item in value):
        raise TypeError("expected string sequence")
    return sorted(set(value))


def _ordered_strings(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise TypeError("expected string sequence")
    if any(not isinstance(item, str) for item in value):
        raise TypeError("expected string sequence")
    return list(value)


def _sorted_string_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise TypeError("required_checks must be object")
    if any(
        not isinstance(key, str) or not isinstance(item, str)
        for key, item in value.items()
    ):
        raise TypeError("required_checks must map strings to strings")
    return dict(sorted(value.items()))


def _sorted_int_map(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        raise TypeError("review_thread_summary must be object")
    if any(
        not isinstance(key, str) or type(item) is not int
        for key, item in value.items()
    ):
        raise TypeError("review_thread_summary must map strings to ints")
    return dict(sorted(value.items()))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate bounded Agent OS release-run evidence"
    )
    parser.add_argument("evidence", help="Path to JSON evidence file")
    args = parser.parse_args()
    with open(args.evidence, encoding="utf-8") as handle:
        evidence = json.load(handle)
    print(
        json.dumps(
            asdict(evaluate_release_run(evidence)),
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
