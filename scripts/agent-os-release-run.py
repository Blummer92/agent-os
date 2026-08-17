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
SCHEMA_VERSION = "1.1.0"
CLASSIFICATIONS = {"READY_FOR_MERGE_AUTHORIZATION", "NEEDS_FIX", "BLOCKED"}
SUCCESS_CHECKS = {"success"}
MERGE_METHODS = {"merge", "squash", "rebase"}


@dataclass
class ReleaseRunState:
    schema_name: str = SCHEMA_NAME
    schema_version: str = SCHEMA_VERSION
    repository: str = ""
    pull_request_number: int = 0
    issue_number: int = 0
    expected_head_sha: str = ""
    observed_head_sha: str = ""
    phase: str = "preflight"
    classification: str = "BLOCKED"
    pr_state: str = "open"
    issue_state: str = "open"
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
    next_action: str = "stop"
    blockers: list[str] = field(default_factory=list)
    side_effects_performed: list[str] = field(default_factory=list)


def evaluate_release_run(evidence: dict[str, Any]) -> ReleaseRunState:
    """Project fresh caller-supplied release evidence into one governed next state."""
    state = ReleaseRunState(
        repository=str(evidence.get("repository", "")),
        pull_request_number=_int_or_zero(evidence.get("pull_request_number")),
        issue_number=_int_or_zero(evidence.get("issue_number")),
        expected_head_sha=str(evidence.get("expected_head_sha", "")),
        observed_head_sha=str(evidence.get("observed_head_sha", "")),
        pr_state=str(evidence.get("pr_state", "open")),
        issue_state=str(evidence.get("issue_state", "open")),
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
        side_effects_performed=_ordered_strings(
            evidence.get("side_effects_performed", [])
        ),
    )
    allowed = set(_sorted_strings(evidence.get("allowed_changed_files", [])))
    if not state.repository or not state.pull_request_number or not state.issue_number:
        state.blockers.append("missing release-run identity")
    if state.pr_state not in {"open", "merged"}:
        state.blockers.append(f"unsupported PR state: {state.pr_state}")
    if state.expected_head_sha != state.observed_head_sha:
        state.blockers.append("exact-head drift")
    if allowed and not set(state.changed_files).issubset(allowed):
        state.blockers.append("changed-file scope drift")
    if state.authorized_merge_method not in MERGE_METHODS:
        state.blockers.append("authorized merge method is missing or unsupported")

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

    if not state.ready_for_review_authorized:
        state.phase = "ready-for-review"
        state.classification = "BLOCKED"
        state.next_action = "request-ready-for-review-authorization"
    elif not state.merge_authorized:
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
