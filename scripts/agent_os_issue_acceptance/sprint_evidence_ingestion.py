"""Pure normalizer from bounded provider evidence into Sprint schema ``0.1.0``.

This is the acceptance half of #376. It is a thin, pure function over already
collected immutable provider evidence and deliberately owns nothing else.

It performs **no** network access, transport, pagination, retry, credential
access, filesystem read or write, Scheduler work, or GitHub mutation. Provider
evidence is accepted structurally rather than by importing the provider package,
so no transport dependency can reach this module. The only local dependency is
:mod:`.sprint_dashboard`, which owns reporting schema ``0.1.0``; this module adds
no field, alias, coercion, or compatibility shim to that schema.

Schema ``0.1.0`` intentionally does not own repository or correlation identity —
``render_sprint_dashboard`` already takes ``repository`` as a separate argument.
:class:`SprintEvidenceIngestionResult` therefore carries the unmodified schema
record together with the repository and correlation identity the caller needs.
It is a return envelope, not a second reporting, readiness, approval, identity,
pagination, or reason-code model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .sprint_dashboard import (
    SCHEMA_VERSION,
    Compatibility,
    FinalHandoff,
    SourceEvidence,
    SprintLaneEvidence,
    SprintMode,
    SuppliedSprintEvidence,
    ValidationEvidence,
)

SUPPORTED_PROVIDER_CONTRACT_VERSIONS = frozenset({"0.1.0"})
SUPPORTED_REPORTING_SCHEMA_VERSIONS = frozenset({SCHEMA_VERSION})

EVIDENCE_MODE = "connected-read-only"

_FRESHNESS_VALUES = frozenset({"current", "stale", "incomplete", "conflicting"})

#: Evidence gaps that make a lane unworkable rather than merely uncertain.
_BLOCKING_REASONS = frozenset(
    {
        "permission:denied",
        "quota:exhausted-first-page",
        "quota:exhausted-later-page",
        "repository:fork-ambiguous",
        "repository:id-mismatch",
        "repository:identity-unverified",
        "repository:name-mismatch",
        "retry:safe-retry-exhausted",
        "retry:unsafe-signal",
        "source:malformed",
        "source:unavailable",
    }
)

_COLLECTION_ATTRIBUTES = (
    "contract_version",
    "reporting_schema_version",
    "sprint_id",
    "correlation_id",
    "repository",
    "base_branch",
    "collected_at",
    "requested_candidates",
    "candidates",
    "freshness",
    "manual_review_reasons",
    "evidence_mode",
    "execution_authorized",
    "side_effects_performed",
)

_CANDIDATE_ATTRIBUTES = (
    "issue_number",
    "title",
    "state",
    "blockers",
    "linked_pull_request_status",
    "pull_request",
    "freshness",
    "reason_codes",
    "sources",
)

_SOURCE_ATTRIBUTES = (
    "object_type",
    "object_id",
    "repository",
    "retrieved_at",
    "updated_at",
    "result_status",
    "permission_status",
    "pagination_status",
    "evidence_digest",
)


@dataclass(frozen=True, slots=True)
class SprintEvidenceIngestionResult:
    """Unmodified schema ``0.1.0`` record plus its caller-owned identity."""

    sprint_evidence: SuppliedSprintEvidence
    repository: str
    correlation_id: str
    provider_contract_version: str


def _require_attributes(value: object, names: Sequence[str], label: str) -> None:
    missing = [name for name in names if not hasattr(value, name)]
    if missing:
        raise TypeError(f"{label} is missing required evidence: {', '.join(missing)}")


def _require_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value


def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, (tuple, list)):
        raise TypeError(f"{name} must be a sequence of strings")
    for item in value:
        if not isinstance(item, str):
            raise TypeError(f"{name} must be a sequence of strings")
    return tuple(value)


def normalize_sprint_evidence(
    collection: object, *, sprint_goal: str
) -> SprintEvidenceIngestionResult:
    """Normalize immutable provider evidence into reporting schema ``0.1.0``.

    The mapping is deterministic: identical immutable provider evidence always
    produces an identical record, because every observation timestamp is taken
    from the frozen collection rather than from the clock. Unknown evidence is
    preserved as unknown and never becomes empty, current, complete, or passing.
    """

    _require_attributes(collection, _COLLECTION_ATTRIBUTES, "provider evidence")
    _require_text(sprint_goal, "sprint_goal")

    if collection.contract_version not in SUPPORTED_PROVIDER_CONTRACT_VERSIONS:
        raise ValueError("unsupported provider evidence contract version")
    if collection.reporting_schema_version not in SUPPORTED_REPORTING_SCHEMA_VERSIONS:
        raise ValueError("unsupported sprint schema version")
    if collection.evidence_mode != EVIDENCE_MODE:
        raise ValueError("provider evidence is not connected-read-only")
    if collection.execution_authorized is not False:
        raise ValueError("provider evidence must not authorize execution")
    if collection.side_effects_performed is not False:
        raise ValueError("provider evidence must record no side effects")
    if collection.freshness not in _FRESHNESS_VALUES:
        raise ValueError("unsupported freshness value")

    repository = _require_text(collection.repository, "repository")
    candidates = tuple(collection.candidates)
    if not candidates:
        raise ValueError("provider evidence must contain at least one candidate")
    if tuple(collection.requested_candidates) != tuple(
        candidate.issue_number for candidate in candidates
    ):
        raise ValueError("candidate evidence does not match the supplied candidates")

    lanes = tuple(_lane(candidate) for candidate in candidates)
    sources = tuple(
        _source(record, repository)
        for candidate in candidates
        for record in candidate.sources
    )
    if not sources:
        raise ValueError("connected-read-only evidence requires source records")

    manual_review_reasons = tuple(
        sorted(set(_string_tuple(collection.manual_review_reasons, "reason codes")))
    )
    freshness = collection.freshness
    if freshness == "current":
        sprint_state = "active"
    elif all(lane.mode is SprintMode.BLOCKED for lane in lanes):
        sprint_state = "blocked"
    else:
        sprint_state = "review"

    evidence = SuppliedSprintEvidence(
        sprint_id=_require_text(collection.sprint_id, "sprint_id"),
        sprint_goal=sprint_goal,
        sprint_state=sprint_state,
        evidence_mode=EVIDENCE_MODE,
        evaluated_at=collection.collected_at,
        freshness=freshness,
        sources=sources,
        lanes=lanes,
        risks=(),
        decisions=(),
        recommendations=(),
        validation=_validation(candidates, sources),
        final_handoff=_handoff(lanes, manual_review_reasons),
        manual_review_reasons=manual_review_reasons,
    )

    return SprintEvidenceIngestionResult(
        sprint_evidence=evidence,
        repository=repository,
        correlation_id=_require_text(collection.correlation_id, "correlation_id"),
        provider_contract_version=collection.contract_version,
    )


def _lane(candidate: object) -> SprintLaneEvidence:
    _require_attributes(candidate, _CANDIDATE_ATTRIBUTES, "candidate evidence")
    reason_codes = _string_tuple(candidate.reason_codes, "candidate reason codes")
    pull_request = candidate.pull_request

    return SprintLaneEvidence(
        issue=candidate.issue_number,
        # Schema lanes require a non-empty title; unknown stays visibly unknown.
        title=candidate.title if isinstance(candidate.title, str) and candidate.title.strip() else "unknown",
        mode=_mode(candidate, reason_codes, pull_request),
        compatibility=_compatibility(candidate, reason_codes, pull_request),
        reason_codes=reason_codes,
        pull_request=getattr(pull_request, "number", None),
        # Unknown changed-file evidence stays empty here only because the lane
        # also carries the `files:unknown` reason code emitted by the provider.
        files_changed=_known_files(pull_request),
        tests_run=(),
        docs_updated=(),
        blockers=_known_blockers(candidate),
        risk_ids=(),
    )


def _mode(
    candidate: object, reason_codes: Sequence[str], pull_request: object
) -> SprintMode:
    if _BLOCKING_REASONS & set(reason_codes):
        return SprintMode.BLOCKED
    if candidate.state == "closed" or candidate.freshness != "current":
        return SprintMode.REVIEW
    if pull_request is not None:
        return SprintMode.IMPLEMENTATION
    if candidate.linked_pull_request_status == "none":
        return SprintMode.PLANNING_ONLY
    return SprintMode.REVIEW


def _compatibility(
    candidate: object, reason_codes: Sequence[str], pull_request: object
) -> Compatibility:
    if _BLOCKING_REASONS & set(reason_codes):
        return Compatibility.UNKNOWN
    if candidate.freshness != "current" or candidate.state != "open":
        return Compatibility.UNKNOWN
    if pull_request is None and candidate.linked_pull_request_status != "none":
        return Compatibility.UNKNOWN
    return Compatibility.COMPATIBLE


def _known_files(pull_request: object) -> tuple[str, ...]:
    files = getattr(pull_request, "changed_files", None)
    return tuple(files) if files is not None else ()


def _known_blockers(candidate: object) -> tuple[str, ...]:
    blockers = candidate.blockers
    return tuple(blockers) if blockers is not None else ()


def _source(record: object, repository: str) -> SourceEvidence:
    _require_attributes(record, _SOURCE_ATTRIBUTES, "source evidence")
    return SourceEvidence(
        object_type=record.object_type,
        object_id=record.object_id,
        repository=record.repository or repository,
        retrieved_at=record.retrieved_at,
        updated_at=record.updated_at,
        result_status=record.result_status,
        permission_status=record.permission_status,
        pagination_status=record.pagination_status,
        evidence_digest=record.evidence_digest,
    )


def _validation(
    candidates: Sequence[object], sources: Sequence[SourceEvidence]
) -> ValidationEvidence:
    return ValidationEvidence(
        tests_run=(),
        docs_updated=(),
        repository_validation="unknown",
        status_checks=_status_checks(candidates),
        cloud_build_runs=0,
        builds_avoided=None,
        evidence_refs=tuple(
            sorted(
                {f"{source.object_type}:{source.object_id}" for source in sources}
            )
        ),
    )


def _status_checks(candidates: Sequence[object]) -> str:
    """Aggregate check evidence. Unknown or missing never becomes passed."""

    statuses = {
        candidate.pull_request.checks_status
        for candidate in candidates
        if candidate.pull_request is not None
    }
    if not statuses:
        return "not-posted"
    if "failing" in statuses:
        return "failed"
    if "unknown" in statuses:
        return "unknown"
    if "pending" in statuses:
        return "pending"
    return "passed"


def _handoff(
    lanes: Sequence[SprintLaneEvidence], manual_review_reasons: Sequence[str]
) -> FinalHandoff:
    return FinalHandoff(
        files_changed=tuple(
            sorted({name for lane in lanes for name in lane.files_changed})
        ),
        tests_run=(),
        docs_updated=(),
        unresolved_blockers=tuple(manual_review_reasons),
        handoff_recommendations=(),
        remaining_risks=(),
    )
