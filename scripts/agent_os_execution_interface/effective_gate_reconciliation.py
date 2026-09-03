"""Deterministic stale-gate reconciliation for execution preflight/resume (#1235).

Consumes already-fetched canonical evidence. It performs no GitHub I/O and grants
no authority. Callers resolve explicit evidence owners and supply bounded evidence;
this contract only decides whether newer applicable evidence supersedes older
status metadata before a stop is surfaced.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Sequence

class EffectiveGateState(str, Enum):
    SATISFIED = "satisfied"
    BLOCKED = "blocked"
    MANUAL_REVIEW = "manual-review"

class EvidenceDisposition(str, Enum):
    SATISFIED = "satisfied"
    BLOCKED = "blocked"

@dataclass(frozen=True, slots=True, kw_only=True)
class GateIdentity:
    repository: str
    issue_number: int
    pull_request_number: int | None = None
    sha: str | None = None

@dataclass(frozen=True, slots=True, kw_only=True)
class GateMarker:
    gate_id: str
    recorded_at: str
    evidence_owner: str | None
    source_ref: str

@dataclass(frozen=True, slots=True, kw_only=True)
class GateEvidence:
    gate_id: str
    recorded_at: str
    evidence_owner: str
    source_ref: str
    disposition: EvidenceDisposition
    identity: GateIdentity
    authoritative: bool

@dataclass(frozen=True, slots=True, kw_only=True)
class EffectiveGateResult:
    state: EffectiveGateState
    selected_evidence_refs: tuple[str, ...]
    ignored_evidence_refs: tuple[str, ...]
    reason_codes: tuple[str, ...]
    repository_implementation_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    issue_closure_authorized: Literal[False] = field(default=False, init=False)
    protected_setting_authorized: Literal[False] = field(default=False, init=False)
    production_authorized: Literal[False] = field(default=False, init=False)
    external_writes_authorized: Literal[False] = field(default=False, init=False)

def _instant(value: str) -> datetime:
    if type(value) is not str or not value.endswith("Z"):
        raise ValueError("recorded_at must be an RFC3339 UTC timestamp ending in Z")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.tzinfo != timezone.utc:
        raise ValueError("recorded_at must be UTC")
    return parsed

def _identity_matches(expected: GateIdentity, actual: GateIdentity) -> bool:
    if actual.repository != expected.repository or actual.issue_number != expected.issue_number:
        return False
    if expected.pull_request_number is not None and actual.pull_request_number != expected.pull_request_number:
        return False
    if expected.sha is not None and actual.sha != expected.sha:
        return False
    return True

def reconcile_effective_gate(*, marker: GateMarker, expected_identity: GateIdentity, evidence: Sequence[GateEvidence]) -> EffectiveGateResult:
    """Reconcile one stale-capable marker against bounded canonical evidence."""
    marker_time = _instant(marker.recorded_at)
    if marker.evidence_owner is None:
        return EffectiveGateResult(state=EffectiveGateState.BLOCKED, selected_evidence_refs=(), ignored_evidence_refs=tuple(sorted({item.source_ref for item in evidence})), reason_codes=("no-linked-evidence-owner",))
    applicable: list[tuple[datetime, GateEvidence]] = []
    ignored: set[str] = set()
    seen: set[tuple[object, ...]] = set()
    for item in evidence:
        item_time = _instant(item.recorded_at)
        fingerprint = (item.gate_id, item.recorded_at, item.evidence_owner, item.source_ref, item.disposition.value, item.identity.repository, item.identity.issue_number, item.identity.pull_request_number, item.identity.sha, item.authoritative)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        if item.gate_id != marker.gate_id or not item.authoritative or item.evidence_owner != marker.evidence_owner or not _identity_matches(expected_identity, item.identity) or item_time <= marker_time:
            ignored.add(item.source_ref)
            continue
        applicable.append((item_time, item))
    if not applicable:
        return EffectiveGateResult(state=EffectiveGateState.BLOCKED, selected_evidence_refs=(), ignored_evidence_refs=tuple(sorted(ignored)), reason_codes=("no-newer-applicable-authoritative-evidence",))
    newest_time = max(item[0] for item in applicable)
    newest = [item for instant, item in applicable if instant == newest_time]
    dispositions = {item.disposition for item in newest}
    refs = tuple(sorted({item.source_ref for item in newest}))
    if len(dispositions) != 1:
        return EffectiveGateResult(state=EffectiveGateState.MANUAL_REVIEW, selected_evidence_refs=refs, ignored_evidence_refs=tuple(sorted(ignored)), reason_codes=("conflicting-newest-authoritative-evidence",))
    state = EffectiveGateState.SATISFIED if next(iter(dispositions)) is EvidenceDisposition.SATISFIED else EffectiveGateState.BLOCKED
    return EffectiveGateResult(state=state, selected_evidence_refs=refs, ignored_evidence_refs=tuple(sorted(ignored)), reason_codes=("newer-applicable-authoritative-evidence",))
