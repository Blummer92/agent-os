"""Bounded MCP-facing projection for finite multi-PR repair continuation (#2487).

This adapter exposes the existing ``batch_repair_continuation`` contract to the
execution-service host. It performs no repair, retry, scheduling, mutation, or
lesson retrieval. Per-candidate evidence is normalized into the canonical
finite-batch projection so item-local blockers advance, repairable shared blockers
route to their canonical repair owner, and only terminal shared blockers halt.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Mapping

from scripts.agent_os_execution_interface.continuation_driver import (
    ContinuationDecision,
    continuation_payload,
)
from scripts.agent_os_issue_acceptance.batch_repair_continuation import (
    RepairCandidateEvidence,
    RepairDisposition,
    RepairRetryBoundaryEvidence,
    evaluate_bulk_repair_continuation,
)


def classify_bulk_repair_continuation(
    *,
    repository: str,
    issue_number: int,
    requested_pull_requests: list[int],
    candidate_evidence: list[dict[str, object]],
) -> dict[str, object]:
    """Project finite repair-batch evidence into the existing continuation model."""

    repo = _repository(repository)
    issue = _issue_number(issue_number)
    requested = _requested_pull_requests(requested_pull_requests)
    evidence = _candidate_evidence(candidate_evidence)

    result = evaluate_bulk_repair_continuation(
        requested_pull_requests=requested,
        evidence=evidence,
    )
    payload = asdict(result)
    payload["repository"] = repo
    payload["issue_number"] = issue

    terminal = result.next_action in {
        "halt-shared-blocker",
        "report-complete-repair-batch",
    }
    blocked = result.next_action == "halt-shared-blocker"
    payload["agent_os_continuation"] = completion_continuation_payload(
        terminal=terminal,
        blocked=blocked,
        next_action=result.next_action,
        reason_codes=result.finite_admission.reason_codes,
    )
    return payload


def _repository(value: object) -> str:
    if type(value) is not str or value.count("/") != 1:
        raise ValueError("repository must use bounded owner/name syntax")
    owner, name = value.split("/", 1)
    if not owner or not name or any(part.strip() != part for part in (owner, name)):
        raise ValueError("repository must use bounded owner/name syntax")
    return value


def _issue_number(value: object) -> int:
    if type(value) is not int or value < 1:
        raise ValueError("issue_number must be a positive built-in integer")
    return value


def _requested_pull_requests(values: object) -> tuple[int, ...]:
    if type(values) is not list or not values:
        raise ValueError("requested_pull_requests must be a non-empty list")
    if any(type(value) is not int or value < 1 for value in values):
        raise ValueError("requested_pull_requests must contain positive built-in integers")
    return tuple(values)


def _candidate_evidence(values: object) -> tuple[RepairCandidateEvidence, ...]:
    if type(values) is not list:
        raise TypeError("candidate_evidence must be a list")
    return tuple(_candidate(item) for item in values)


def _candidate(value: object) -> RepairCandidateEvidence:
    if not isinstance(value, Mapping):
        raise TypeError("candidate evidence entries must be mappings")

    retry_boundary = _retry_boundary(value.get("retry_boundary"))
    try:
        disposition = RepairDisposition(value.get("disposition"))
    except (TypeError, ValueError) as exc:
        raise ValueError("candidate disposition is unsupported") from exc

    return RepairCandidateEvidence(
        pull_request_number=value.get("pull_request_number"),
        disposition=disposition,
        reason_code=value.get("reason_code"),
        shared_blocker=value.get("shared_blocker", False),
        failed_repair_attempt_id=value.get("failed_repair_attempt_id"),
        retry_boundary=retry_boundary,
        retry_mutation_performed=value.get("retry_mutation_performed", False),
        shared_blocker_key=value.get("shared_blocker_key"),
        shared_repair_owner=value.get("shared_repair_owner"),
        shared_repair_available=value.get("shared_repair_available", False),
        shared_repair_completed=value.get("shared_repair_completed", False),
    )


def _retry_boundary(value: object) -> RepairRetryBoundaryEvidence | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TypeError("retry_boundary must be a mapping when supplied")
    reason_codes = value.get("reason_codes")
    if type(reason_codes) is not list:
        raise TypeError("retry_boundary reason_codes must be a list")
    return RepairRetryBoundaryEvidence(
        failed_attempt_id=value.get("failed_attempt_id"),
        mutation_admissible=value.get("mutation_admissible"),
        blocking_attempt_id=value.get("blocking_attempt_id"),
        reason_codes=tuple(reason_codes),
    )
