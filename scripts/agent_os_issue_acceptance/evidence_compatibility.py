"""Pure cross-generation evidence compatibility projection for Agent OS (#1201).

This module joins caller-supplied immutable evidence only.  It performs no I/O,
reacquisition, routing, execution, lifecycle mutation, retry, or authorization.
Each evidence record names only the canonical bindings that its owning contract
says are compatibility-critical; omitted bindings are treated as not applicable,
not silently inferred.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

EVIDENCE_COMPATIBILITY_SCHEMA_VERSION = "1.0"

_ALLOWED_BINDINGS = frozenset(
    {
        "repository",
        "issue_identity",
        "authorization_id",
        "scope_id",
        "execution_id",
        "candidate_id",
        "head_sha",
        "base_sha",
        "workspace_id",
        "executor_surface",
        "environment_id",
        "dependency_id",
        "lease_generation",
        "command_plan_id",
        "resume_lineage_id",
        "lifecycle_snapshot_id",
    }
)
_AUTHORITY_BINDINGS = frozenset(
    {"repository", "issue_identity", "authorization_id", "scope_id"}
)
_MAX_RECORDS = 32
_MAX_BINDINGS = len(_ALLOWED_BINDINGS)
_MAX_TEXT_BYTES = 512


class CompatibilityContext(str, Enum):
    EXECUTION_DISPATCH = "execution-dispatch"
    READY_FOR_REVIEW = "ready-for-review"


class CompatibilityOutcome(str, Enum):
    COMPATIBLE = "compatible"
    REACQUIRE_REQUIRED = "reacquire-required"
    NEEDS_DECISION = "needs-decision"


def _text(value: object, name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be a built-in string")
    if not value or value != value.strip() or len(value.encode("utf-8")) > _MAX_TEXT_BYTES:
        raise ValueError(f"{name} is outside bounds")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError(f"{name} contains control characters")
    return value


def _bindings(value: object, name: str) -> tuple[tuple[str, str], ...]:
    if type(value) is not tuple:
        raise TypeError(f"{name} must be an exact tuple")
    if len(value) > _MAX_BINDINGS:
        raise ValueError(f"{name} exceeds the binding bound")
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in value:
        if type(item) is not tuple or len(item) != 2:
            raise TypeError(f"{name} entries must be exact name/value tuples")
        binding, binding_value = item
        binding = _text(binding, f"{name} binding")
        binding_value = _text(binding_value, f"{name} value")
        if binding not in _ALLOWED_BINDINGS:
            raise ValueError(f"{name} contains unsupported binding {binding!r}")
        if binding in seen:
            raise ValueError(f"{name} contains duplicate binding {binding!r}")
        seen.add(binding)
        result.append((binding, binding_value))
    return tuple(sorted(result))


def _binding_map(bindings: tuple[tuple[str, str], ...]) -> dict[str, str]:
    return dict(bindings)


@dataclass(frozen=True, slots=True, kw_only=True)
class ExpectedGeneration:
    """Caller-supplied current expected identity for one decision boundary."""

    bindings: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        checked = _bindings(self.bindings, "expected bindings")
        if not checked:
            raise ValueError("expected bindings must not be empty")
        object.__setattr__(self, "bindings", checked)


@dataclass(frozen=True, slots=True, kw_only=True)
class CompatibilityEvidenceRecord:
    """One independently valid record and the bindings its owner makes critical."""

    evidence_id: str
    owner: str
    bindings: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_id", _text(self.evidence_id, "evidence_id"))
        object.__setattr__(self, "owner", _text(self.owner, "owner"))
        checked = _bindings(self.bindings, "evidence bindings")
        if not checked:
            raise ValueError("evidence bindings must not be empty")
        object.__setattr__(self, "bindings", checked)


@dataclass(frozen=True, slots=True, kw_only=True)
class EvidenceCompatibilityDecision:
    schema_version: str = EVIDENCE_COMPATIBILITY_SCHEMA_VERSION
    context: CompatibilityContext
    outcome: CompatibilityOutcome
    reason_codes: tuple[str, ...]
    reacquire_owners: tuple[str, ...]
    decision_id: str
    authority_created: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)


def _decision_id(
    *,
    context: CompatibilityContext,
    expected: ExpectedGeneration,
    records: tuple[CompatibilityEvidenceRecord, ...],
    outcome: CompatibilityOutcome,
    reasons: tuple[str, ...],
    reacquire_owners: tuple[str, ...],
) -> str:
    payload = {
        "schema_version": EVIDENCE_COMPATIBILITY_SCHEMA_VERSION,
        "context": context.value,
        "expected": list(expected.bindings),
        "records": [
            {
                "evidence_id": record.evidence_id,
                "owner": record.owner,
                "bindings": list(record.bindings),
            }
            for record in records
        ],
        "outcome": outcome.value,
        "reason_codes": list(reasons),
        "reacquire_owners": list(reacquire_owners),
        "authority_created": False,
        "side_effects_performed": False,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(b"agent-os-evidence-compatibility:v1\0" + encoded).hexdigest()
    return f"evidence-compatibility:{digest}"


def evaluate_evidence_compatibility(
    *,
    context: CompatibilityContext,
    expected: ExpectedGeneration,
    records: tuple[CompatibilityEvidenceRecord, ...],
) -> EvidenceCompatibilityDecision:
    """Compare independently valid evidence against one current expected generation.

    Every binding explicitly carried by a record must agree with the current
    expected value.  A record omits a binding only when its canonical owner says
    the evidence is reusable/independent across that binding.  Authority/scope/
    subject mismatches require a decision; ordinary generation drift requests
    reacquisition from the smallest supplied evidence owner.
    """

    if type(context) is not CompatibilityContext:
        raise TypeError("context must be an exact CompatibilityContext")
    if type(expected) is not ExpectedGeneration:
        raise TypeError("expected must be an exact ExpectedGeneration")
    if type(records) is not tuple:
        raise TypeError("records must be an exact tuple")
    if not records or len(records) > _MAX_RECORDS:
        raise ValueError("records must contain between 1 and 32 records")
    if any(type(record) is not CompatibilityEvidenceRecord for record in records):
        raise TypeError("records must contain exact CompatibilityEvidenceRecord values")

    canonical_records = tuple(sorted(records, key=lambda item: item.evidence_id))
    if len({record.evidence_id for record in canonical_records}) != len(canonical_records):
        raise ValueError("records contain duplicate evidence_id values")

    expected_map = _binding_map(expected.bindings)
    hard_reasons: set[str] = set()
    drift_reasons: set[str] = set()
    owners: set[str] = set()

    for record in canonical_records:
        for binding, observed in record.bindings:
            current = expected_map.get(binding)
            if current is None:
                hard_reasons.add(f"binding.{binding}.current-unavailable")
                owners.add(record.owner)
                continue
            if current == observed:
                continue
            if binding in _AUTHORITY_BINDINGS:
                hard_reasons.add(f"binding.{binding}.mismatch")
            else:
                drift_reasons.add(f"binding.{binding}.mismatch")
            owners.add(record.owner)

    if hard_reasons:
        outcome = CompatibilityOutcome.NEEDS_DECISION
        reasons = tuple(sorted(hard_reasons | drift_reasons))
        reacquire_owners: tuple[str, ...] = ()
    elif drift_reasons:
        outcome = CompatibilityOutcome.REACQUIRE_REQUIRED
        reasons = tuple(sorted(drift_reasons))
        reacquire_owners = tuple(sorted(owners))
    else:
        outcome = CompatibilityOutcome.COMPATIBLE
        reasons = ("compatible",)
        reacquire_owners = ()

    return EvidenceCompatibilityDecision(
        context=context,
        outcome=outcome,
        reason_codes=reasons,
        reacquire_owners=reacquire_owners,
        decision_id=_decision_id(
            context=context,
            expected=expected,
            records=canonical_records,
            outcome=outcome,
            reasons=reasons,
            reacquire_owners=reacquire_owners,
        ),
    )


def evaluate_execution_dispatch_compatibility(
    *,
    expected: ExpectedGeneration,
    records: tuple[CompatibilityEvidenceRecord, ...],
) -> EvidenceCompatibilityDecision:
    return evaluate_evidence_compatibility(
        context=CompatibilityContext.EXECUTION_DISPATCH,
        expected=expected,
        records=records,
    )


def evaluate_ready_for_review_compatibility(
    *,
    expected: ExpectedGeneration,
    records: tuple[CompatibilityEvidenceRecord, ...],
) -> EvidenceCompatibilityDecision:
    return evaluate_evidence_compatibility(
        context=CompatibilityContext.READY_FOR_REVIEW,
        expected=expected,
        records=records,
    )
