"""Frozen data models for the exact-issue readiness candidate-packet stage.

This module defines only data shapes (requests, evidence wrappers, results)
plus their canonical serialize/deserialize helpers. It does not reimplement
scanning, IssuePlan current-state projection, readiness evaluation, or
AcceptanceReport serialization -- those live in
``scripts.agent_os_issue_acceptance`` and are reused as-is. AcceptanceReport
payloads specifically are owned by
``acceptance_report_transport.acceptance_report_to_payload`` /
``acceptance_report_from_payload``; this module holds no second serializer.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, Mapping, Protocol

from scripts.agent_os_issue_acceptance.acceptance_report_transport import (
    acceptance_report_from_payload,
    acceptance_report_to_payload,
)
from scripts.agent_os_issue_acceptance.issueplan_current_state import (
    IssuePlanCurrentStateEvidence,
    IssuePlanSourceSnapshot,
)
from scripts.agent_os_issue_acceptance.readiness import ReadinessOutcome, ReadinessResult

STAGE_SCHEMA_VERSION = "1.1"

_HEX_DIGITS = frozenset("0123456789abcdef")
_SHA40_LENGTH = 40
_SHA256_LENGTH = 64
_FORBIDDEN_BRANCH_CHARS = frozenset("*?[")


class IssueReadStatus(str, Enum):
    """Outcome of one read-only, single-issue fetch attempt."""

    OK = "ok"
    NOT_FOUND = "not-found"
    PERMISSION_DENIED = "permission-denied"
    SOURCE_INACCESSIBLE = "source-inaccessible"
    MALFORMED_RESPONSE = "malformed-response"
    API_ERROR = "api-error"


@dataclass(frozen=True, slots=True)
class IssueReadResult:
    """Read-only adapter response for one exact issue fetch."""

    status: IssueReadStatus
    item: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, IssueReadStatus):
            raise TypeError("status must be an IssueReadStatus")
        if self.status == IssueReadStatus.OK and self.item is None:
            raise ValueError("ok status requires an item")
        if self.status != IssueReadStatus.OK and self.item is not None:
            raise ValueError("non-ok status must not carry an item")


class EvidenceStatus(str, Enum):
    """Bounded tri-state (plus failure) outcome for one evidence adapter call."""

    RESOLVED_CLEAR = "resolved-clear"
    RESOLVED_BLOCKED = "resolved-blocked"
    NEEDS_DECISION = "needs-decision"
    UNAVAILABLE = "unavailable"


def _evidence_string(value: object, field_name: str) -> str:
    """Validate one non-empty, control-character-free evidence string."""
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must not contain boolean values")
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must contain only strings")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not contain empty values")
    if any(character < " " or character == "\x7f" for character in normalized):
        raise ValueError(f"{field_name} must not contain control characters")
    return normalized


def _evidence_strings(values: object, field_name: str) -> tuple[str, ...]:
    """Validate a string tuple, preserving supplied order and multiplicity."""
    if values is None:
        return ()
    if isinstance(values, (str, bytes, Mapping)) or not isinstance(values, Iterable):
        raise TypeError(f"{field_name} must be an iterable of strings")
    return tuple(_evidence_string(value, field_name) for value in values)


@dataclass(frozen=True, slots=True)
class DependencyEvidence:
    """Explicit dependency-readiness adapter result. Never a guessed boolean."""

    status: EvidenceStatus
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    details: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.status, EvidenceStatus):
            raise TypeError("status must be an EvidenceStatus")
        object.__setattr__(self, "reason_codes", _evidence_strings(self.reason_codes, "reason_codes"))
        object.__setattr__(self, "details", _evidence_strings(self.details, "details"))


@dataclass(frozen=True, slots=True)
class ValidationEvidence:
    """Explicit validation-readiness adapter result. Never a guessed boolean."""

    status: EvidenceStatus
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    details: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.status, EvidenceStatus):
            raise TypeError("status must be an EvidenceStatus")
        object.__setattr__(self, "reason_codes", _evidence_strings(self.reason_codes, "reason_codes"))
        object.__setattr__(self, "details", _evidence_strings(self.details, "details"))


class DependencyIdentityStatus(str, Enum):
    """Whether canonical dependency identities were supplied, and resolved.

    ``resolved`` and ``absent`` are positive findings from a structured source.
    ``unresolved`` and ``unavailable`` are fail-closed findings: neither ever
    asserts a dependency-identity set.
    """

    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    ABSENT = "absent"
    UNAVAILABLE = "unavailable"


DEPENDENCY_IDENTITY_NOT_SUPPLIED_REASON = "dependency-identity.not-supplied"
DEPENDENCY_IDENTITY_DUPLICATE_COLLAPSED_REASON = (
    "dependency-identity.duplicate-collapsed"
)


def _identity_sequence(
    values: object, field_name: str
) -> tuple[tuple[str, ...], bool]:
    """Return deterministically ordered unique identities plus a duplicate flag."""
    normalized = _evidence_strings(values, field_name)
    unique = tuple(sorted(set(normalized)))
    return unique, len(unique) != len(normalized)


def _context_strings(values: object, field_name: str) -> tuple[str, ...]:
    """Validate exact context strings without trimming or normalization."""
    if (
        isinstance(values, (str, bytes, Mapping, bool))
        or not isinstance(values, Iterable)
    ):
        raise TypeError(f"{field_name} must be an iterable of strings")

    validated: list[str] = []
    for value in values:
        if isinstance(value, bool):
            raise TypeError(f"{field_name} must not contain boolean values")
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must contain only strings")
        if not value or value != value.strip():
            raise ValueError(
                f"{field_name} must contain non-empty canonical strings"
            )
        if any(character < " " or character == "\x7f" for character in value):
            raise ValueError(f"{field_name} must not contain control characters")
        validated.append(value)
    return tuple(validated)


def _canonical_scope(values: object, field_name: str) -> tuple[str, ...]:
    """Return one deterministic, duplicate-free scope tuple."""
    return tuple(sorted(set(_context_strings(values, field_name))))


def _context_string(value: object, field_name: str) -> str:
    """Validate one context string without trimming or other normalization."""
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must not be a boolean")
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty canonical string")
    if any(character < " " or character == "\x7f" for character in value):
        raise ValueError(f"{field_name} must not contain control characters")
    return value


def _repository_name(value: object) -> str:
    repository = _context_string(value, "repository")
    if repository.count("/") != 1:
        raise ValueError("repository must use owner/repository form")
    owner, name = repository.split("/", 1)
    if not owner or not name:
        raise ValueError("repository must use owner/repository form")
    return repository


def _branch_name(value: object) -> str:
    branch = _context_string(value, "base_branch")
    components = branch.split("/")
    if (
        branch.startswith("refs/")
        or branch.startswith(("/", "-"))
        or branch.endswith(("/", "."))
        or "//" in branch
        or branch == "@"
        or "@{" in branch
        or "\\" in branch
        or " " in branch
        or any(character in branch for character in _FORBIDDEN_BRANCH_CHARS)
        or any(token in branch for token in ("..", "~", "^", ":"))
        or any(
            component.startswith(".") or component.endswith(".lock")
            for component in components
        )
    ):
        raise ValueError("base_branch is malformed")
    return branch


def _hex_digest(value: object, field_name: str, length: int) -> str:
    digest = _context_string(value, field_name)
    if len(digest) != length or not _HEX_DIGITS.issuperset(digest):
        raise ValueError(f"{field_name} is malformed")
    return digest


@dataclass(frozen=True, slots=True)
class IssuePlanningContext:
    """Explicit pre-planning repository and implementation-contract context.

    The context is caller supplied and input-only. It never probes Git, a
    worktree, the filesystem, a provider, or a clock. Scope collections are
    canonicalized before readiness projects them into IssuePlan evidence.
    """

    repository: str
    base_branch: str
    evaluated_repository_sha: str
    implementation_contract_fingerprint: str
    allowed_files: tuple[str, ...] = field(default_factory=tuple)
    forbidden_paths: tuple[str, ...] = field(default_factory=tuple)
    required_tests: tuple[str, ...] = field(default_factory=tuple)
    provenance: tuple[str, ...] = field(default_factory=tuple)
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "repository", _repository_name(self.repository))
        object.__setattr__(self, "base_branch", _branch_name(self.base_branch))
        object.__setattr__(
            self,
            "evaluated_repository_sha",
            _hex_digest(
                self.evaluated_repository_sha,
                "evaluated_repository_sha",
                _SHA40_LENGTH,
            ),
        )
        object.__setattr__(
            self,
            "implementation_contract_fingerprint",
            _hex_digest(
                self.implementation_contract_fingerprint,
                "implementation_contract_fingerprint",
                _SHA256_LENGTH,
            ),
        )
        object.__setattr__(
            self, "allowed_files", _canonical_scope(self.allowed_files, "allowed_files")
        )
        object.__setattr__(
            self,
            "forbidden_paths",
            _canonical_scope(self.forbidden_paths, "forbidden_paths"),
        )
        object.__setattr__(
            self,
            "required_tests",
            _canonical_scope(self.required_tests, "required_tests"),
        )
        if isinstance(self.provenance, (set, frozenset)):
            raise TypeError("provenance must preserve caller order")
        provenance = _context_strings(self.provenance, "provenance")
        if not provenance:
            raise ValueError("provenance must contain at least one value")
        object.__setattr__(self, "provenance", provenance)


@dataclass(frozen=True, slots=True)
class DependencyIdentityEvidence:
    """Immutable canonical dependency-identity evidence for one issue.

    Identities are only ever supplied explicitly by a caller that already holds
    them in structured form. Nothing here parses issue prose, ``Depends on:``
    text, comments, PR titles or bodies, labels, reason codes, or diagnostic
    details to obtain them, and no repository-wide graph guess is ever made. A
    caller without structured identities produces ``absent`` or ``unavailable``
    evidence instead of inventing one.

    ``dependency_ids`` is deterministically ordered and carries no duplicates.
    Only ``resolved`` evidence may assert identities at all; every other status
    keeps the tuple empty so a partial set can never read as a complete one.
    """

    status: DependencyIdentityStatus
    dependency_ids: tuple[str, ...] = field(default_factory=tuple)
    provenance: tuple[str, ...] = field(default_factory=tuple)
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.status, DependencyIdentityStatus):
            raise TypeError("status must be a DependencyIdentityStatus")

        identities, collapsed = _identity_sequence(
            self.dependency_ids, "dependency_ids"
        )
        reason_codes = set(_evidence_strings(self.reason_codes, "reason_codes"))
        if collapsed:
            reason_codes.add(DEPENDENCY_IDENTITY_DUPLICATE_COLLAPSED_REASON)
        object.__setattr__(self, "dependency_ids", identities)
        object.__setattr__(
            self, "provenance", _evidence_strings(self.provenance, "provenance")
        )
        object.__setattr__(self, "reason_codes", tuple(sorted(reason_codes)))

        if self.status == DependencyIdentityStatus.RESOLVED:
            if not self.dependency_ids:
                raise ValueError(
                    "resolved dependency identity evidence requires at least one "
                    "dependency id"
                )
            if not self.provenance:
                raise ValueError(
                    "resolved dependency identity evidence requires provenance"
                )
        elif self.dependency_ids:
            raise ValueError(
                f"{self.status.value} dependency identity evidence must not carry "
                "dependency ids"
            )

        if self.status == DependencyIdentityStatus.ABSENT and not self.provenance:
            raise ValueError(
                "absent dependency identity evidence requires provenance proving "
                "the structured source reported no dependencies"
            )
        if (
            self.status
            in {
                DependencyIdentityStatus.UNRESOLVED,
                DependencyIdentityStatus.UNAVAILABLE,
            }
            and not self.reason_codes
        ):
            raise ValueError(
                f"{self.status.value} dependency identity evidence requires at "
                "least one reason code"
            )


DEPENDENCY_IDENTITY_NOT_SUPPLIED = DependencyIdentityEvidence(
    status=DependencyIdentityStatus.UNAVAILABLE,
    reason_codes=(DEPENDENCY_IDENTITY_NOT_SUPPLIED_REASON,),
)
"""Canonical fail-closed evidence for a caller that supplied no identities."""


class IssueSourceReader(Protocol):
    """Read-only single-issue reader. No write method exists on this protocol."""

    def read_issue(self, repository: str, issue_number: int) -> IssueReadResult:
        """Return the current state of exactly one issue."""


class RepositoryEvidenceReader(Protocol):
    """Read-only dependency/validation evidence reader. No write methods exist."""

    def read_dependency_evidence(
        self, repository: str, issue_number: int
    ) -> DependencyEvidence:
        """Return dependency-readiness evidence for one issue."""

    def read_validation_evidence(
        self, repository: str, issue_number: int
    ) -> ValidationEvidence:
        """Return validation-readiness evidence for one issue."""


@dataclass(frozen=True, slots=True)
class IssueSnapshot:
    """Exact, preserved snapshot of one fetched GitHub issue."""

    repository: str
    issue_number: int
    url: str
    created_at: str
    updated_at: str
    body: str
    body_sha256: str
    source_revision: str
    retrieved_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.issue_number, int) or isinstance(self.issue_number, bool):
            raise TypeError("issue_number must be an int")
        expected_digest = hashlib.sha256(self.body.encode("utf-8")).hexdigest()
        if self.body_sha256 != expected_digest:
            raise ValueError("body_sha256 does not match body")


class IssueSourceStageStatus(str, Enum):
    RESOLVED = "resolved"
    SOURCE_FAILURE = "source-failure"
    INCOMPLETE_EVIDENCE = "incomplete-evidence"


@dataclass(frozen=True, slots=True)
class IssueSourceStageResult:
    """Result of resolving one exact issue snapshot, fail-closed on any doubt."""

    status: IssueSourceStageStatus
    snapshot: IssueSnapshot | None
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    details: tuple[str, ...] = field(default_factory=tuple)
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.status, IssueSourceStageStatus):
            raise TypeError("status must be an IssueSourceStageStatus")
        if self.status == IssueSourceStageStatus.RESOLVED and self.snapshot is None:
            raise ValueError("resolved status requires a snapshot")
        if self.status != IssueSourceStageStatus.RESOLVED and self.snapshot is not None:
            raise ValueError("non-resolved status must not carry a snapshot")
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))
        object.__setattr__(self, "details", tuple(self.details))


class IssueReadinessStageStatus(str, Enum):
    """Final, distinct stage outcomes -- never inferred from each other."""

    READY = "ready"
    BLOCKED = "blocked"
    NEEDS_DECISION = "needs-decision"
    SOURCE_FAILURE = "source-failure"
    INCOMPLETE_EVIDENCE = "incomplete-evidence"


_READINESS_OUTCOME_MAP = {
    ReadinessOutcome.READY: IssueReadinessStageStatus.READY,
    ReadinessOutcome.BLOCKED: IssueReadinessStageStatus.BLOCKED,
    ReadinessOutcome.NEEDS_DECISION: IssueReadinessStageStatus.NEEDS_DECISION,
}


@dataclass(frozen=True, slots=True)
class IssueReadinessStageRequest:
    """Bounded request describing exactly which issue snapshot to prepare."""

    repository: str
    issue_number: int
    observed_at: str
    freshness_boundary: str = "stage-observation"
    expected_source_revision: str | None = None
    governed_field_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.issue_number, int) or isinstance(self.issue_number, bool):
            raise TypeError("issue_number must be an int")
        object.__setattr__(
            self, "governed_field_names", tuple(self.governed_field_names)
        )


@dataclass(frozen=True, slots=True)
class IssueReadinessStageResult:
    """Round-trippable, read-only candidate-packet readiness stage output."""

    status: IssueReadinessStageStatus
    snapshot: IssueSnapshot | None
    issueplan_current_state_evidence: IssuePlanCurrentStateEvidence | None
    readiness_result: ReadinessResult | None
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    details: tuple[str, ...] = field(default_factory=tuple)
    dependency_identity_evidence: DependencyIdentityEvidence | None = None
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.status, IssueReadinessStageStatus):
            raise TypeError("status must be an IssueReadinessStageStatus")
        resolved = self.status in {
            IssueReadinessStageStatus.READY,
            IssueReadinessStageStatus.BLOCKED,
            IssueReadinessStageStatus.NEEDS_DECISION,
        }
        if resolved and (
            self.snapshot is None
            or self.issueplan_current_state_evidence is None
            or self.readiness_result is None
        ):
            raise ValueError(
                "resolved statuses require a snapshot, IssuePlan current-state "
                "evidence, and a readiness result"
            )
        if not resolved and (
            self.snapshot is not None
            or self.issueplan_current_state_evidence is not None
            or self.readiness_result is not None
        ):
            raise ValueError(
                "unresolved statuses must not carry snapshot, IssuePlan "
                "current-state, or readiness evidence"
            )
        if resolved and self.readiness_result is not None:
            expected = _READINESS_OUTCOME_MAP[self.readiness_result.outcome]
            if expected != self.status:
                raise ValueError("status must match the readiness outcome")
        if resolved:
            identity_evidence = self.dependency_identity_evidence
            if identity_evidence is None:
                # A caller that supplied no structured identities fails closed to
                # explicit unavailable evidence -- never to a guess or a silent
                # empty set that would read as "no dependencies".
                identity_evidence = DEPENDENCY_IDENTITY_NOT_SUPPLIED
            elif not isinstance(identity_evidence, DependencyIdentityEvidence):
                raise TypeError(
                    "dependency_identity_evidence must be a "
                    "DependencyIdentityEvidence"
                )
            object.__setattr__(
                self, "dependency_identity_evidence", identity_evidence
            )
        elif self.dependency_identity_evidence is not None:
            raise ValueError(
                "unresolved statuses must not carry dependency identity evidence"
            )
        object.__setattr__(self, "reason_codes", tuple(sorted(set(self.reason_codes))))
        object.__setattr__(self, "details", tuple(self.details))


# --------------------------------------------------------------------------
# Canonical serialization -- round trip without semantic drift.
# --------------------------------------------------------------------------


def canonical_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


_DEPENDENCY_IDENTITY_PAYLOAD_KEYS = frozenset(
    {
        "status",
        "dependency_ids",
        "provenance",
        "reason_codes",
        "execution_authorized",
        "side_effects_performed",
    }
)

_STAGE_RESULT_PAYLOAD_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "snapshot",
        "issueplan_current_state_evidence",
        "readiness_result",
        "reason_codes",
        "details",
        "dependency_identity_evidence",
        "execution_authorized",
        "side_effects_performed",
    }
)


def _require_exact_payload_keys(
    payload: object, keys: frozenset[str], label: str
) -> Mapping[str, Any]:
    """Closed-schema key check, mirroring the AcceptanceReport transport rule."""
    if not isinstance(payload, Mapping):
        raise ValueError(f"{label} must be a mapping")
    supplied = set(payload)
    missing = sorted(keys - supplied)
    if missing:
        raise ValueError(f"{label} is missing field(s): " + ", ".join(missing))
    unsupported = sorted(supplied - keys)
    if unsupported:
        raise ValueError(f"{label} has unsupported field(s): " + ", ".join(unsupported))
    return payload


def _payload_list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return value


def dependency_identity_evidence_to_dict(
    evidence: DependencyIdentityEvidence,
) -> dict[str, Any]:
    return {
        "status": evidence.status.value,
        "dependency_ids": list(evidence.dependency_ids),
        "provenance": list(evidence.provenance),
        "reason_codes": list(evidence.reason_codes),
        "execution_authorized": False,
        "side_effects_performed": False,
    }


def dependency_identity_evidence_from_dict(
    payload: Mapping[str, Any],
) -> DependencyIdentityEvidence:
    """Reconstruct dependency-identity evidence, failing closed on any drift."""
    label = "dependency identity evidence"
    _require_exact_payload_keys(payload, _DEPENDENCY_IDENTITY_PAYLOAD_KEYS, label)
    if payload["execution_authorized"] is not False:
        raise ValueError("execution_authorized must be false")
    if payload["side_effects_performed"] is not False:
        raise ValueError("side_effects_performed must be false")
    raw_status = payload["status"]
    if not isinstance(raw_status, str) or isinstance(raw_status, bool):
        raise ValueError(f"{label} status must be a string")
    try:
        status = DependencyIdentityStatus(raw_status)
    except ValueError as error:
        raise ValueError(f"{label} has an unsupported status") from error
    return DependencyIdentityEvidence(
        status=status,
        dependency_ids=_payload_list(payload["dependency_ids"], "dependency_ids"),
        provenance=_payload_list(payload["provenance"], "provenance"),
        reason_codes=_payload_list(payload["reason_codes"], "reason_codes"),
    )


def issue_snapshot_to_dict(snapshot: IssueSnapshot) -> dict[str, Any]:
    return {
        "repository": snapshot.repository,
        "issue_number": snapshot.issue_number,
        "url": snapshot.url,
        "created_at": snapshot.created_at,
        "updated_at": snapshot.updated_at,
        "body": snapshot.body,
        "body_sha256": snapshot.body_sha256,
        "source_revision": snapshot.source_revision,
        "retrieved_at": snapshot.retrieved_at,
    }


def issue_snapshot_from_dict(payload: Mapping[str, Any]) -> IssueSnapshot:
    return IssueSnapshot(
        repository=payload["repository"],
        issue_number=payload["issue_number"],
        url=payload["url"],
        created_at=payload["created_at"],
        updated_at=payload["updated_at"],
        body=payload["body"],
        body_sha256=payload["body_sha256"],
        source_revision=payload["source_revision"],
        retrieved_at=payload["retrieved_at"],
    )


def readiness_result_to_dict(result: ReadinessResult) -> dict[str, Any]:
    return {
        "outcome": result.outcome.value,
        "report": acceptance_report_to_payload(result.report),
    }


def readiness_result_from_dict(payload: Mapping[str, Any]) -> ReadinessResult:
    return ReadinessResult(
        outcome=ReadinessOutcome(payload["outcome"]),
        report=acceptance_report_from_payload(payload["report"]),
    )


def _issueplan_source_snapshot_to_dict(
    snapshot: IssuePlanSourceSnapshot,
) -> dict[str, Any]:
    return {
        "source_locator": snapshot.source_locator,
        "source_family": snapshot.source_family,
        "source_revision": snapshot.source_revision,
        "retrieval_status": snapshot.retrieval_status,
        "completeness_status": snapshot.completeness_status,
        "metadata_status": snapshot.metadata_status,
        "governed_fields": [list(item) for item in snapshot.governed_fields],
        "omitted_fields": list(snapshot.omitted_fields),
        "provenance_references": list(snapshot.provenance_references),
        "candidate_set_fingerprint": snapshot.candidate_set_fingerprint,
        "scanner_result_fingerprint": snapshot.scanner_result_fingerprint,
        "reason_codes": list(snapshot.reason_codes),
    }


def _issueplan_source_snapshot_from_dict(
    payload: Mapping[str, Any],
) -> IssuePlanSourceSnapshot:
    return IssuePlanSourceSnapshot(
        source_locator=payload["source_locator"],
        source_family=payload["source_family"],
        source_revision=payload["source_revision"],
        retrieval_status=payload["retrieval_status"],
        completeness_status=payload["completeness_status"],
        metadata_status=payload["metadata_status"],
        governed_fields=tuple(
            tuple(item) for item in payload.get("governed_fields", [])
        ),
        omitted_fields=tuple(payload.get("omitted_fields", [])),
        provenance_references=tuple(payload.get("provenance_references", [])),
        candidate_set_fingerprint=payload["candidate_set_fingerprint"],
        scanner_result_fingerprint=payload["scanner_result_fingerprint"],
        reason_codes=tuple(payload.get("reason_codes", [])),
    )


def issueplan_current_state_evidence_to_dict(
    evidence: IssuePlanCurrentStateEvidence,
) -> dict[str, Any]:
    return {
        "schema_version": evidence.schema_version,
        "evidence_id": evidence.evidence_id,
        "observed_at": evidence.observed_at,
        "freshness_boundary": evidence.freshness_boundary,
        "source_snapshot": _issueplan_source_snapshot_to_dict(evidence.source_snapshot),
        "source_snapshot_fingerprint": evidence.source_snapshot_fingerprint,
        "scanner_result_fingerprint": evidence.scanner_result_fingerprint,
        "entity_ids": list(evidence.entity_ids),
        "candidate_revisions": list(evidence.candidate_revisions),
        "repository": evidence.repository,
        "base_branch": evidence.base_branch,
        "evaluated_repository_sha": evidence.evaluated_repository_sha,
        "implementation_contract_fingerprint": (
            evidence.implementation_contract_fingerprint
        ),
        "allowed_files": list(evidence.allowed_files),
        "forbidden_paths": list(evidence.forbidden_paths),
        "required_tests": list(evidence.required_tests),
        "graph_reference": evidence.graph_reference,
        "planning_result_reference": evidence.planning_result_reference,
        "handoff_reference": evidence.handoff_reference,
        "supplied_node_ids": list(evidence.supplied_node_ids),
        "reason_codes": list(evidence.reason_codes),
        "execution_authorized": False,
    }


def issueplan_current_state_evidence_from_dict(
    payload: Mapping[str, Any],
) -> IssuePlanCurrentStateEvidence:
    return IssuePlanCurrentStateEvidence(
        schema_version=payload["schema_version"],
        evidence_id=payload["evidence_id"],
        observed_at=payload["observed_at"],
        freshness_boundary=payload["freshness_boundary"],
        source_snapshot=_issueplan_source_snapshot_from_dict(
            payload["source_snapshot"]
        ),
        source_snapshot_fingerprint=payload["source_snapshot_fingerprint"],
        scanner_result_fingerprint=payload["scanner_result_fingerprint"],
        entity_ids=tuple(payload.get("entity_ids", [])),
        candidate_revisions=tuple(payload.get("candidate_revisions", [])),
        repository=payload.get("repository"),
        base_branch=payload.get("base_branch"),
        evaluated_repository_sha=payload.get("evaluated_repository_sha"),
        implementation_contract_fingerprint=payload.get(
            "implementation_contract_fingerprint"
        ),
        allowed_files=tuple(payload.get("allowed_files", [])),
        forbidden_paths=tuple(payload.get("forbidden_paths", [])),
        required_tests=tuple(payload.get("required_tests", [])),
        graph_reference=payload.get("graph_reference"),
        planning_result_reference=payload.get("planning_result_reference"),
        handoff_reference=payload.get("handoff_reference"),
        supplied_node_ids=tuple(payload.get("supplied_node_ids", [])),
        reason_codes=tuple(payload.get("reason_codes", [])),
    )


def issue_readiness_stage_result_to_dict(
    result: IssueReadinessStageResult,
) -> dict[str, Any]:
    return {
        "schema_version": STAGE_SCHEMA_VERSION,
        "status": result.status.value,
        "snapshot": (
            None if result.snapshot is None else issue_snapshot_to_dict(result.snapshot)
        ),
        "issueplan_current_state_evidence": (
            None
            if result.issueplan_current_state_evidence is None
            else issueplan_current_state_evidence_to_dict(
                result.issueplan_current_state_evidence
            )
        ),
        "readiness_result": (
            None
            if result.readiness_result is None
            else readiness_result_to_dict(result.readiness_result)
        ),
        "reason_codes": list(result.reason_codes),
        "details": list(result.details),
        "dependency_identity_evidence": (
            None
            if result.dependency_identity_evidence is None
            else dependency_identity_evidence_to_dict(
                result.dependency_identity_evidence
            )
        ),
        "execution_authorized": False,
        "side_effects_performed": False,
    }


def issue_readiness_stage_result_from_dict(
    payload: Mapping[str, Any],
) -> IssueReadinessStageResult:
    """Reconstruct one stage result, rejecting legacy and unknown-field payloads.

    Schema ``1.0`` payloads predate canonical dependency-identity evidence and
    are rejected outright by the version check rather than being reinterpreted:
    a legacy payload cannot prove whether identities were absent or merely
    never captured, so accepting one would silently invent that distinction.
    """
    if not isinstance(payload, Mapping):
        raise ValueError("readiness stage result must be a mapping")
    if payload.get("schema_version") != STAGE_SCHEMA_VERSION:
        raise ValueError("unsupported stage schema_version")
    _require_exact_payload_keys(
        payload, _STAGE_RESULT_PAYLOAD_KEYS, "readiness stage result"
    )
    if payload["execution_authorized"] is not False:
        raise ValueError("execution_authorized must be false")
    if payload["side_effects_performed"] is not False:
        raise ValueError("side_effects_performed must be false")
    snapshot = payload["snapshot"]
    evidence = payload["issueplan_current_state_evidence"]
    readiness = payload["readiness_result"]
    identity_evidence = payload["dependency_identity_evidence"]
    return IssueReadinessStageResult(
        status=IssueReadinessStageStatus(payload["status"]),
        snapshot=None if snapshot is None else issue_snapshot_from_dict(snapshot),
        issueplan_current_state_evidence=(
            None
            if evidence is None
            else issueplan_current_state_evidence_from_dict(evidence)
        ),
        readiness_result=(
            None if readiness is None else readiness_result_from_dict(readiness)
        ),
        reason_codes=tuple(_payload_list(payload["reason_codes"], "reason_codes")),
        details=tuple(_payload_list(payload["details"], "details")),
        dependency_identity_evidence=(
            None
            if identity_evidence is None
            else dependency_identity_evidence_from_dict(identity_evidence)
        ),
    )
