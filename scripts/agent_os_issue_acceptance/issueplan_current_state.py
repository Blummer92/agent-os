from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from .issueplan_scanner import AdoptionClass, ScanFinding, ScanResult, SourceEnvelope

ISSUEPLAN_CURRENT_STATE_SCHEMA_VERSION = "1.0"

_SET_LIKE_FIELDS = frozenset(
    {
        "required_files",
        "forbidden_paths",
        "required_tests",
        "required_docs",
        "banned_patterns",
        "manual_review",
    }
)
_FIELD_STATES = frozenset(
    {
        "present",
        "absent",
        "null",
        "intentionally-omitted",
        "unavailable",
        "malformed",
        "unsupported",
        "stale",
        "ambiguous",
        "identity-quarantined",
        "unknown-governed-field",
    }
)
_RETRIEVAL_STATES = frozenset(
    {"present", "absent", "unavailable", "inaccessible", "unsupported", "stale"}
)
_COMPLETENESS_STATES = frozenset(
    {"complete", "partial", "truncated", "unknown-pagination"}
)
_METADATA_STATES = frozenset(
    {
        "present",
        "absent",
        "duplicate-identical",
        "malformed",
        "ambiguous",
        "identity-quarantined",
        "unknown-governed-field",
        "unsupported",
    }
)
_REASON_CODES = frozenset(
    {
        "source.revision-changed",
        "source.freshness-boundary-changed",
        "source.partial",
        "source.inaccessible",
        "source.unsupported",
        "source.unknown-pagination",
        "scanner.multiple-identical",
        "scanner.multiple-conflicting",
        "scanner.malformed-candidate",
        "scanner.unknown-governed-field",
        "identity.quarantined",
        "candidate.changed",
        "contract.scope-changed",
        "contract.allowlist-changed",
        "contract.required-tests-changed",
        "projection.incomplete",
        "projection.lookup-failed",
        "version.unsupported",
    }
)
_NEEDS_DECISION = frozenset(
    {
        "source.partial",
        "source.inaccessible",
        "source.unknown-pagination",
        "scanner.unknown-governed-field",
        "projection.incomplete",
        "projection.lookup-failed",
    }
)
_BLOCKED = frozenset(
    {
        "source.unsupported",
        "scanner.multiple-identical",
        "scanner.multiple-conflicting",
        "scanner.malformed-candidate",
        "identity.quarantined",
    }
)


class IssuePlanCurrentStateOutcome(str, Enum):
    CURRENT = "current"
    STALE = "stale"
    BLOCKED = "blocked"
    INVALID = "invalid"
    NEEDS_DECISION = "needs-decision"


@dataclass(frozen=True)
class IssuePlanSourceSnapshot:
    source_locator: str
    source_family: str
    source_revision: str
    retrieval_status: str
    completeness_status: str
    metadata_status: str
    governed_fields: tuple[tuple[str, str, str | None], ...]
    omitted_fields: tuple[str, ...]
    provenance_references: tuple[str, ...]
    candidate_set_fingerprint: str
    scanner_result_fingerprint: str
    reason_codes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _text(self.source_locator, "source_locator")
        _text(self.source_family, "source_family")
        _text(self.source_revision, "source_revision")
        if self.retrieval_status not in _RETRIEVAL_STATES:
            raise ValueError("unsupported retrieval_status")
        if self.completeness_status not in _COMPLETENESS_STATES:
            raise ValueError("unsupported completeness_status")
        if self.metadata_status not in _METADATA_STATES:
            raise ValueError("unsupported metadata_status")
        fields = tuple(sorted(self.governed_fields, key=lambda item: item[0]))
        if len({item[0] for item in fields}) != len(fields):
            raise ValueError("governed_fields cannot contain duplicate names")
        for name, state, value in fields:
            _text(name, "governed field name")
            if state not in _FIELD_STATES:
                raise ValueError(f"unsupported governed-field state: {state}")
            if state == "present" and value is None:
                raise ValueError("present governed fields require a value")
            if state == "null" and value != "null":
                raise ValueError("null governed fields require canonical null")
            if state not in {"present", "null"} and value is not None:
                raise ValueError("non-value governed-field states cannot contain a value")
        object.__setattr__(self, "governed_fields", fields)
        object.__setattr__(self, "omitted_fields", _strings(self.omitted_fields))
        object.__setattr__(
            self, "provenance_references", _strings(self.provenance_references)
        )
        object.__setattr__(self, "reason_codes", _reasons(self.reason_codes))


@dataclass(frozen=True)
class IssuePlanCurrentStateEvidence:
    schema_version: str
    evidence_id: str
    observed_at: str
    freshness_boundary: str
    source_snapshot: IssuePlanSourceSnapshot
    source_snapshot_fingerprint: str
    scanner_result_fingerprint: str
    entity_ids: tuple[str, ...]
    candidate_revisions: tuple[str, ...]
    repository: str | None = None
    base_branch: str | None = None
    evaluated_repository_sha: str | None = None
    implementation_contract_fingerprint: str | None = None
    allowed_files: tuple[str, ...] = ()
    forbidden_paths: tuple[str, ...] = ()
    required_tests: tuple[str, ...] = ()
    graph_reference: str | None = None
    planning_result_reference: str | None = None
    handoff_reference: str | None = None
    supplied_node_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    execution_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        _text(self.schema_version, "schema_version")
        _text(self.evidence_id, "evidence_id")
        _timestamp(self.observed_at)
        _text(self.freshness_boundary, "freshness_boundary")
        if not isinstance(self.source_snapshot, IssuePlanSourceSnapshot):
            raise TypeError("source_snapshot must be IssuePlanSourceSnapshot")
        object.__setattr__(self, "entity_ids", _strings(self.entity_ids))
        object.__setattr__(
            self, "candidate_revisions", _strings(self.candidate_revisions)
        )
        object.__setattr__(self, "allowed_files", _strings(self.allowed_files))
        object.__setattr__(self, "forbidden_paths", _strings(self.forbidden_paths))
        object.__setattr__(self, "required_tests", _strings(self.required_tests))
        object.__setattr__(
            self, "supplied_node_ids", _strings(self.supplied_node_ids)
        )
        reasons = _reasons(self.reason_codes)
        if not set(self.source_snapshot.reason_codes) <= set(reasons):
            raise ValueError("evidence reason_codes must include snapshot reason_codes")
        object.__setattr__(self, "reason_codes", reasons)


@dataclass(frozen=True)
class IssuePlanCurrentStateComparison:
    expected_evidence_id: str
    current_evidence_id: str
    expected_fingerprint: str
    current_fingerprint: str
    changed_bindings: tuple[str, ...]
    outcome: IssuePlanCurrentStateOutcome
    reason_codes: tuple[str, ...]
    details: tuple[str, ...] = field(default_factory=tuple)
    execution_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, IssuePlanCurrentStateOutcome):
            raise TypeError("outcome must be IssuePlanCurrentStateOutcome")
        object.__setattr__(
            self, "changed_bindings", _strings(self.changed_bindings)
        )
        object.__setattr__(self, "reason_codes", _reasons(self.reason_codes))
        object.__setattr__(self, "details", tuple(str(item) for item in self.details))


def build_issueplan_current_state_evidence(
    envelope: SourceEnvelope,
    scan_result: ScanResult,
    *,
    observed_at: str,
    freshness_boundary: str,
    governed_field_names: Iterable[str] = (),
    field_state_overrides: Mapping[str, str] | None = None,
    omitted_fields: Iterable[str] = (),
    retrieval_status: str | None = None,
    completeness_status: str | None = None,
    metadata_status: str | None = None,
    repository: str | None = None,
    base_branch: str | None = None,
    evaluated_repository_sha: str | None = None,
    implementation_contract_fingerprint: str | None = None,
    allowed_files: Iterable[str] = (),
    forbidden_paths: Iterable[str] = (),
    required_tests: Iterable[str] = (),
    graph_reference: str | None = None,
    planning_result_reference: str | None = None,
    handoff_reference: str | None = None,
    supplied_node_ids: Iterable[str] = (),
    schema_version: str = ISSUEPLAN_CURRENT_STATE_SCHEMA_VERSION,
) -> IssuePlanCurrentStateEvidence:
    if not isinstance(envelope, SourceEnvelope) or not isinstance(
        scan_result, ScanResult
    ):
        raise TypeError("envelope and scan_result must use scanner models")
    if (scan_result.source_locator, scan_result.source_revision) != (
        envelope.source_locator,
        envelope.source_revision,
    ):
        raise ValueError("scan_result source identity does not match envelope")
    if scan_result.execution_authorized is not False:
        raise ValueError("scanner evidence cannot authorize execution")
    _timestamp(observed_at)
    _text(freshness_boundary, "freshness_boundary")

    retrieval = _derive_retrieval(envelope)
    completeness = _derive_completeness(envelope)
    metadata = _derive_metadata(scan_result)
    retrieval = _override_status(
        retrieval, retrieval_status, "present", _RETRIEVAL_STATES
    )
    completeness = _override_status(
        completeness, completeness_status, "complete", _COMPLETENESS_STATES
    )
    metadata = _override_status(
        metadata, metadata_status, "present", _METADATA_STATES
    )

    overrides = dict(field_state_overrides or {})
    for name in omitted_fields:
        overrides.setdefault(name, "intentionally-omitted")
    fields = _field_projection(scan_result, tuple(governed_field_names), overrides)
    candidates = _candidate_payload(scan_result)
    scanner_payload = _scanner_payload(scan_result, candidates)
    candidate_fingerprint = _digest(candidates)
    scanner_fingerprint = _digest(scanner_payload)
    reasons = _state_reasons(
        scan_result, retrieval, completeness, metadata, schema_version
    )
    snapshot = IssuePlanSourceSnapshot(
        source_locator=envelope.source_locator,
        source_family=envelope.source_family,
        source_revision=envelope.source_revision,
        retrieval_status=retrieval,
        completeness_status=completeness,
        metadata_status=metadata,
        governed_fields=fields,
        omitted_fields=tuple(
            name for name, state, _ in fields if state == "intentionally-omitted"
        ),
        provenance_references=tuple(
            item.raw_excerpt_or_reference for item in scan_result.provenance
        ),
        candidate_set_fingerprint=candidate_fingerprint,
        scanner_result_fingerprint=scanner_fingerprint,
        reason_codes=reasons,
    )
    snapshot_fingerprint = _digest(_snapshot_payload(snapshot))
    values = {
        "schema_version": schema_version,
        "freshness_boundary": freshness_boundary,
        "source_snapshot": snapshot,
        "source_snapshot_fingerprint": snapshot_fingerprint,
        "scanner_result_fingerprint": scanner_fingerprint,
        "entity_ids": _candidate_values(scan_result, "entity_id"),
        "candidate_revisions": _candidate_values(scan_result, "revision"),
        "repository": repository,
        "base_branch": base_branch,
        "evaluated_repository_sha": evaluated_repository_sha,
        "implementation_contract_fingerprint": implementation_contract_fingerprint,
        "allowed_files": _strings(allowed_files),
        "forbidden_paths": _strings(forbidden_paths),
        "required_tests": _strings(required_tests),
        "graph_reference": graph_reference,
        "planning_result_reference": planning_result_reference,
        "handoff_reference": handoff_reference,
        "supplied_node_ids": _strings(supplied_node_ids),
        "reason_codes": reasons,
    }
    fingerprint = _digest(_evidence_payload(**values))
    return IssuePlanCurrentStateEvidence(
        evidence_id=f"issueplan-current-state:{fingerprint}",
        observed_at=observed_at,
        **values,
    )


def compute_issueplan_current_state_fingerprint(
    evidence: IssuePlanCurrentStateEvidence,
) -> str:
    if not isinstance(evidence, IssuePlanCurrentStateEvidence):
        raise TypeError("evidence must be IssuePlanCurrentStateEvidence")
    return _digest(
        _evidence_payload(
            schema_version=evidence.schema_version,
            freshness_boundary=evidence.freshness_boundary,
            source_snapshot=evidence.source_snapshot,
            source_snapshot_fingerprint=evidence.source_snapshot_fingerprint,
            scanner_result_fingerprint=evidence.scanner_result_fingerprint,
            entity_ids=evidence.entity_ids,
            candidate_revisions=evidence.candidate_revisions,
            repository=evidence.repository,
            base_branch=evidence.base_branch,
            evaluated_repository_sha=evidence.evaluated_repository_sha,
            implementation_contract_fingerprint=(
                evidence.implementation_contract_fingerprint
            ),
            allowed_files=evidence.allowed_files,
            forbidden_paths=evidence.forbidden_paths,
            required_tests=evidence.required_tests,
            graph_reference=evidence.graph_reference,
            planning_result_reference=evidence.planning_result_reference,
            handoff_reference=evidence.handoff_reference,
            supplied_node_ids=evidence.supplied_node_ids,
            reason_codes=evidence.reason_codes,
        )
    )


def compare_issueplan_current_state(
    expected: IssuePlanCurrentStateEvidence,
    current: IssuePlanCurrentStateEvidence,
) -> IssuePlanCurrentStateComparison:
    if not isinstance(expected, IssuePlanCurrentStateEvidence) or not isinstance(
        current, IssuePlanCurrentStateEvidence
    ):
        raise TypeError("expected and current must be IssuePlanCurrentStateEvidence")
    expected_fingerprint = compute_issueplan_current_state_fingerprint(expected)
    current_fingerprint = compute_issueplan_current_state_fingerprint(current)
    if expected.evidence_id != f"issueplan-current-state:{expected_fingerprint}" or (
        current.evidence_id != f"issueplan-current-state:{current_fingerprint}"
    ):
        return _comparison(
            expected,
            current,
            expected_fingerprint,
            current_fingerprint,
            (),
            ("projection.incomplete",),
            IssuePlanCurrentStateOutcome.INVALID,
        )

    changed = _changed(expected, current)
    reasons = set(current.reason_codes) | set(_change_reasons(changed))
    if "version.unsupported" in reasons:
        outcome = IssuePlanCurrentStateOutcome.INVALID
    elif reasons & _BLOCKED:
        outcome = IssuePlanCurrentStateOutcome.BLOCKED
    elif reasons & _NEEDS_DECISION:
        outcome = IssuePlanCurrentStateOutcome.NEEDS_DECISION
    elif changed or reasons:
        outcome = IssuePlanCurrentStateOutcome.STALE
    else:
        outcome = IssuePlanCurrentStateOutcome.CURRENT
    return _comparison(
        expected,
        current,
        expected_fingerprint,
        current_fingerprint,
        changed,
        tuple(reasons),
        outcome,
    )


def _comparison(
    expected: IssuePlanCurrentStateEvidence,
    current: IssuePlanCurrentStateEvidence,
    expected_fp: str,
    current_fp: str,
    changed: Iterable[str],
    reasons: Iterable[str],
    outcome: IssuePlanCurrentStateOutcome,
) -> IssuePlanCurrentStateComparison:
    changed_tuple = _strings(changed)
    reason_tuple = _reasons(reasons)
    return IssuePlanCurrentStateComparison(
        expected_evidence_id=expected.evidence_id,
        current_evidence_id=current.evidence_id,
        expected_fingerprint=expected_fp,
        current_fingerprint=current_fp,
        changed_bindings=changed_tuple,
        outcome=outcome,
        reason_codes=reason_tuple,
        details=tuple(f"changed:{item}" for item in changed_tuple),
    )


def _candidate_payload(scan_result: ScanResult) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for candidate in scan_result.candidates:
        parsed = None
        if candidate.parsed is not None:
            parsed = {
                key: _field_value(key, candidate.parsed[key])
                for key in sorted(candidate.parsed)
            }
        payload.append(
            {
                "index": candidate.index,
                "parsed": parsed,
                "malformed": candidate.malformed,
                "raw_digest": (
                    hashlib.sha256(candidate.raw.encode("utf-8")).hexdigest()
                    if parsed is None
                    else None
                ),
            }
        )
    return payload


def _scanner_payload(
    scan_result: ScanResult, candidates: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "source_locator": scan_result.source_locator,
        "source_revision": scan_result.source_revision,
        "findings": sorted({item.value for item in scan_result.findings}),
        "adoption_class": scan_result.adoption_class.value,
        "candidates": candidates,
        "provenance": [
            {
                "field_name": item.field_name,
                "value": _field_value(item.field_name, item.normalized_value),
                "source_locator": item.source_locator,
                "source_revision": item.source_revision,
                "source_region_or_block": item.source_region_or_block,
                "raw_excerpt_or_reference": item.raw_excerpt_or_reference,
                "extraction_status": item.extraction_status,
                "profile_classification": item.profile_classification,
            }
            for item in scan_result.provenance
        ],
        "strict_valid": scan_result.strict_valid,
        "execution_authorized": False,
        "evidence": sorted(set(scan_result.evidence)),
    }


def _field_projection(
    scan_result: ScanResult,
    governed_names: tuple[str, ...],
    overrides: Mapping[str, str],
) -> tuple[tuple[str, str, str | None], ...]:
    values: dict[str, list[str]] = {}
    for candidate in scan_result.candidates:
        if candidate.parsed:
            for name, value in candidate.parsed.items():
                values.setdefault(name, []).append(
                    _bytes(_field_value(name, value)).decode()
                )
    names = set(governed_names) | set(values) | set(overrides)
    projected: list[tuple[str, str, str | None]] = []
    for name in sorted(names):
        state = overrides.get(name)
        candidates = values.get(name, [])
        if state is None:
            if not candidates:
                state, value = "absent", None
            elif len(set(candidates)) > 1:
                state, value = "ambiguous", None
            elif candidates[0] == "null":
                state, value = "null", "null"
            else:
                state, value = "present", candidates[0]
        else:
            if state not in _FIELD_STATES:
                raise ValueError(f"unsupported field state: {state}")
            value = candidates[0] if state == "present" and candidates else None
            if state == "present" and value is None:
                raise ValueError(f"present override for {name} requires a value")
            if state == "null":
                value = "null"
        projected.append((name, state, value))
    return tuple(projected)


def _derive_retrieval(envelope: SourceEnvelope) -> str:
    if envelope.source_family != "github-issue":
        return "unsupported"
    if not envelope.accessible:
        return "inaccessible"
    if envelope.expected_revision and envelope.expected_revision != envelope.source_revision:
        return "stale"
    return "present"


def _derive_completeness(envelope: SourceEnvelope) -> str:
    if not envelope.pagination_complete:
        return "unknown-pagination"
    if not envelope.retrieval_complete:
        return "partial"
    return "complete"


def _derive_metadata(scan_result: ScanResult) -> str:
    findings = set(scan_result.findings)
    if scan_result.adoption_class == AdoptionClass.IDENTITY_QUARANTINED:
        return "identity-quarantined"
    if ScanFinding.METADATA_CONFLICTING in findings:
        return "ambiguous"
    if ScanFinding.METADATA_MALFORMED in findings:
        return "malformed"
    if ScanFinding.UNKNOWN_GOVERNED_FIELD in findings:
        return "unknown-governed-field"
    if ScanFinding.METADATA_DUPLICATED_IDENTICAL in findings:
        return "duplicate-identical"
    if ScanFinding.PROFILE_VERSION_UNSUPPORTED in findings:
        return "unsupported"
    if ScanFinding.METADATA_MISSING in findings:
        return "absent"
    return "present"


def _override_status(
    derived: str,
    override: str | None,
    neutral: str,
    allowed: frozenset[str],
) -> str:
    if override is None:
        return derived
    if override not in allowed:
        raise ValueError(f"unsupported status override: {override}")
    if derived != neutral and override == neutral:
        raise ValueError("status override cannot weaken evidence")
    return override


def _state_reasons(
    scan_result: ScanResult,
    retrieval: str,
    completeness: str,
    metadata: str,
    schema_version: str,
) -> tuple[str, ...]:
    reasons: set[str] = set()
    if schema_version != ISSUEPLAN_CURRENT_STATE_SCHEMA_VERSION:
        reasons.add("version.unsupported")
    if retrieval == "stale":
        reasons.add("source.revision-changed")
    elif retrieval in {"absent", "unavailable", "inaccessible"}:
        reasons.update({"source.inaccessible", "projection.lookup-failed"})
    elif retrieval == "unsupported":
        reasons.add("source.unsupported")
    if completeness in {"partial", "truncated"}:
        reasons.update({"source.partial", "projection.incomplete"})
    elif completeness == "unknown-pagination":
        reasons.update({"source.unknown-pagination", "projection.incomplete"})
    metadata_codes = {
        "duplicate-identical": "scanner.multiple-identical",
        "malformed": "scanner.malformed-candidate",
        "ambiguous": "scanner.multiple-conflicting",
        "identity-quarantined": "identity.quarantined",
        "unknown-governed-field": "scanner.unknown-governed-field",
        "unsupported": "version.unsupported",
    }
    if metadata in metadata_codes:
        reasons.add(metadata_codes[metadata])
    if ScanFinding.SOURCE_STALE in scan_result.findings:
        reasons.add("source.revision-changed")
    return _reasons(reasons)


def _snapshot_payload(snapshot: IssuePlanSourceSnapshot) -> dict[str, Any]:
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


def _evidence_payload(**values: Any) -> dict[str, Any]:
    payload = dict(values)
    payload["source_snapshot"] = _snapshot_payload(payload["source_snapshot"])
    for name in (
        "entity_ids",
        "candidate_revisions",
        "allowed_files",
        "forbidden_paths",
        "required_tests",
        "supplied_node_ids",
        "reason_codes",
    ):
        payload[name] = list(payload[name])
    payload["execution_authorized"] = False
    return payload


def _changed(
    expected: IssuePlanCurrentStateEvidence,
    current: IssuePlanCurrentStateEvidence,
) -> tuple[str, ...]:
    names = (
        "schema_version",
        "freshness_boundary",
        "source_snapshot_fingerprint",
        "scanner_result_fingerprint",
        "entity_ids",
        "candidate_revisions",
        "repository",
        "base_branch",
        "evaluated_repository_sha",
        "implementation_contract_fingerprint",
        "allowed_files",
        "forbidden_paths",
        "required_tests",
        "graph_reference",
        "planning_result_reference",
        "handoff_reference",
        "supplied_node_ids",
    )
    return tuple(
        sorted(
            name
            for name in names
            if getattr(expected, name) != getattr(current, name)
        )
    )


def _change_reasons(changed: Iterable[str]) -> tuple[str, ...]:
    names = set(changed)
    reasons: set[str] = set()
    if "schema_version" in names:
        reasons.add("version.unsupported")
    if names & {
        "repository",
        "base_branch",
        "evaluated_repository_sha",
    }:
        reasons.add("source.revision-changed")
    if "freshness_boundary" in names:
        reasons.add("source.freshness-boundary-changed")
    if names & {
        "implementation_contract_fingerprint",
        "forbidden_paths",
        "supplied_node_ids",
    }:
        reasons.add("contract.scope-changed")
    if "allowed_files" in names:
        reasons.add("contract.allowlist-changed")
    if "required_tests" in names:
        reasons.add("contract.required-tests-changed")
    if names & {
        "source_snapshot_fingerprint",
        "scanner_result_fingerprint",
        "entity_ids",
        "candidate_revisions",
    }:
        reasons.add("candidate.changed")
    return _reasons(reasons)


def _candidate_values(scan_result: ScanResult, name: str) -> tuple[str, ...]:
    return _strings(
        str(candidate.parsed[name]).strip()
        for candidate in scan_result.candidates
        if candidate.parsed and candidate.parsed.get(name) is not None
    )


def _field_value(name: str, value: Any) -> Any:
    normalized = _jsonable(value)
    if name not in _SET_LIKE_FIELDS or not isinstance(normalized, list):
        return normalized
    unique = {_bytes(item): item for item in normalized}
    return [unique[key] for key in sorted(unique)]


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("mapping keys must be strings")
        return {key: _jsonable(value[key]) for key in sorted(value)}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (set, frozenset)):
        unique = {_bytes(_jsonable(item)): _jsonable(item) for item in value}
        return [unique[key] for key in sorted(unique)]
    raise TypeError(f"unsupported canonical value type: {type(value).__name__}")


def _bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _digest(value: Any) -> str:
    return hashlib.sha256(_bytes(value)).hexdigest()


def _reasons(values: Iterable[str]) -> tuple[str, ...]:
    result = tuple(sorted(set(values)))
    if not set(result) <= _REASON_CODES:
        raise ValueError("reason_codes must use the bounded IssuePlanCore vocabulary")
    return result


def _strings(values: Iterable[str]) -> tuple[str, ...]:
    result = tuple(sorted(set(values)))
    if not all(isinstance(value, str) and value for value in result):
        raise ValueError("values must be non-empty strings")
    return result


def _text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _timestamp(value: str) -> None:
    _text(value, "observed_at")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValueError("observed_at must use RFC 3339 UTC seconds") from exc
