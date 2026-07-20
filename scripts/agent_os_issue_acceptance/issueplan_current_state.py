from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Literal, Mapping

from .issueplan_scanner import ScanFinding, ScanResult, SourceEnvelope

ISSUEPLAN_CURRENT_STATE_SCHEMA_VERSION = "1.0"
_SUPPORTED_SCHEMA_VERSIONS = frozenset({ISSUEPLAN_CURRENT_STATE_SCHEMA_VERSION})
_APPROVED_REASON_CODES = frozenset(
    {
        "source.revision-changed",
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
_STALE_REASON_CODES = frozenset(
    {
        "source.revision-changed",
        "candidate.changed",
        "contract.scope-changed",
        "contract.allowlist-changed",
        "contract.required-tests-changed",
    }
)
_NEEDS_DECISION_REASON_CODES = frozenset(
    {
        "scanner.unknown-governed-field",
        "projection.lookup-failed",
    }
)
_BLOCKED_REASON_CODES = _APPROVED_REASON_CODES - (
    _STALE_REASON_CODES
    | _NEEDS_DECISION_REASON_CODES
    | {"version.unsupported"}
)
_SCANNER_REASON_CODES = frozenset(
    {
        "scanner.multiple-identical",
        "scanner.multiple-conflicting",
        "scanner.malformed-candidate",
        "scanner.unknown-governed-field",
        "identity.quarantined",
    }
)
_FINDING_REASON_CODES = {
    ScanFinding.METADATA_DUPLICATED_IDENTICAL: "scanner.multiple-identical",
    ScanFinding.METADATA_CONFLICTING: "scanner.multiple-conflicting",
    ScanFinding.METADATA_MALFORMED: "scanner.malformed-candidate",
    ScanFinding.UNKNOWN_GOVERNED_FIELD: "scanner.unknown-governed-field",
    ScanFinding.IDENTITY_FINDING_PRESENT: "identity.quarantined",
}
_FIELD_STATES = frozenset(
    {"absent", "null", "intentionally-omitted", "unavailable", "present"}
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class IssuePlanCurrentStateOutcome(str, Enum):
    CURRENT = "current"
    STALE = "stale"
    BLOCKED = "blocked"
    INVALID = "invalid"
    NEEDS_DECISION = "needs-decision"


@dataclass(frozen=True)
class IssuePlanSourceSnapshot:
    source_locator: str
    source_revision: str
    source_family: str
    retrieval_complete: bool
    pagination_complete: bool
    accessible: bool
    expected_revision: str | None
    source_fingerprint: str


@dataclass(frozen=True)
class IssuePlanCurrentStateEvidence:
    schema_version: str
    evidence_id: str
    observed_at: str
    freshness_boundary: str
    source: IssuePlanSourceSnapshot
    scanner_fingerprint: str
    candidate_set_fingerprint: str
    entity_ids: tuple[str, ...]
    candidate_revisions: tuple[str, ...]
    governed_fields: tuple[tuple[str, str, Any], ...]
    intentionally_omitted_fields: tuple[str, ...]
    unavailable_fields: tuple[str, ...]
    provenance_references: tuple[str, ...]
    scanner_reason_codes: tuple[str, ...]
    contract_scope_fingerprint: str
    contract_allowlist_fingerprint: str
    contract_required_tests_fingerprint: str
    implementation_contract_fingerprint: str
    graph_reference: str | None = None
    planning_result_reference: str | None = None
    handoff_reference: str | None = None
    projection_complete: bool = True
    projection_lookup_succeeded: bool = True
    execution_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.source, IssuePlanSourceSnapshot):
            raise TypeError("source must be an IssuePlanSourceSnapshot")
        entity_ids = _normalize_strings(self.entity_ids, "entity_ids")
        candidate_revisions = _normalize_strings(
            self.candidate_revisions, "candidate_revisions"
        )
        omitted = _normalize_strings(
            self.intentionally_omitted_fields,
            "intentionally_omitted_fields",
        )
        unavailable = _normalize_strings(self.unavailable_fields, "unavailable_fields")
        if set(omitted) & set(unavailable):
            raise ValueError("omitted and unavailable field inventories must be disjoint")
        provenance = _normalize_strings(
            self.provenance_references, "provenance_references"
        )
        scanner_reasons = tuple(sorted(set(self.scanner_reason_codes)))
        if not set(scanner_reasons) <= _SCANNER_REASON_CODES:
            raise ValueError("scanner_reason_codes must use the bounded scanner vocabulary")
        governed_fields = _normalize_governed_fields(self.governed_fields)
        object.__setattr__(self, "entity_ids", entity_ids)
        object.__setattr__(self, "candidate_revisions", candidate_revisions)
        object.__setattr__(self, "intentionally_omitted_fields", omitted)
        object.__setattr__(self, "unavailable_fields", unavailable)
        object.__setattr__(self, "provenance_references", provenance)
        object.__setattr__(self, "scanner_reason_codes", scanner_reasons)
        object.__setattr__(self, "governed_fields", governed_fields)


@dataclass(frozen=True)
class IssuePlanCurrentStateComparison:
    outcome: IssuePlanCurrentStateOutcome
    expected_evidence_id: str
    current_evidence_id: str
    changed_bindings: tuple[str, ...]
    reason_codes: tuple[str, ...]
    details: tuple[str, ...]
    execution_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, IssuePlanCurrentStateOutcome):
            raise TypeError("outcome must be an IssuePlanCurrentStateOutcome")
        changed = _normalize_strings(self.changed_bindings, "changed_bindings")
        reasons = tuple(sorted(set(self.reason_codes)))
        if not set(reasons) <= _APPROVED_REASON_CODES:
            raise ValueError("reason_codes must use the bounded IDB2A vocabulary")
        details = tuple(str(item) for item in self.details)
        object.__setattr__(self, "changed_bindings", changed)
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(self, "details", details)


def compute_issueplan_current_state_fingerprint(value: Any) -> str:
    payload = json.dumps(
        _canonicalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_issueplan_current_state_evidence(
    *,
    envelope: SourceEnvelope,
    scan_result: ScanResult,
    observed_at: str,
    freshness_boundary: str,
    implementation_contract: Mapping[str, Any],
    governed_field_names: tuple[str, ...] = (),
    intentionally_omitted_fields: tuple[str, ...] = (),
    unavailable_fields: tuple[str, ...] = (),
    graph_reference: str | None = None,
    planning_result_reference: str | None = None,
    handoff_reference: str | None = None,
    projection_complete: bool = True,
    projection_lookup_succeeded: bool = True,
    schema_version: str = ISSUEPLAN_CURRENT_STATE_SCHEMA_VERSION,
) -> IssuePlanCurrentStateEvidence:
    _validate_build_inputs(
        envelope=envelope,
        scan_result=scan_result,
        observed_at=observed_at,
        freshness_boundary=freshness_boundary,
        implementation_contract=implementation_contract,
        schema_version=schema_version,
        projection_complete=projection_complete,
        projection_lookup_succeeded=projection_lookup_succeeded,
    )
    if (
        envelope.source_locator != scan_result.source_locator
        or envelope.source_revision != scan_result.source_revision
    ):
        raise ValueError("scan_result must bind to the supplied source envelope")
    if scan_result.execution_authorized is not False:
        raise ValueError("scan_result cannot authorize execution")

    governed_names = _normalize_strings(
        governed_field_names, "governed_field_names"
    )
    omitted = _normalize_strings(
        intentionally_omitted_fields, "intentionally_omitted_fields"
    )
    unavailable = _normalize_strings(unavailable_fields, "unavailable_fields")
    if set(omitted) & set(unavailable):
        raise ValueError("omitted and unavailable field inventories must be disjoint")

    source = IssuePlanSourceSnapshot(
        source_locator=envelope.source_locator,
        source_revision=envelope.source_revision,
        source_family=envelope.source_family,
        retrieval_complete=envelope.retrieval_complete,
        pagination_complete=envelope.pagination_complete,
        accessible=envelope.accessible,
        expected_revision=envelope.expected_revision,
        source_fingerprint=compute_issueplan_current_state_fingerprint(envelope.content),
    )
    candidates = _candidate_projection(scan_result)
    entity_ids = tuple(
        sorted(
            {
                str(candidate.parsed["entity_id"]).strip()
                for candidate in scan_result.candidates
                if candidate.parsed and candidate.parsed.get("entity_id") is not None
            }
        )
    )
    candidate_revisions = tuple(
        sorted(
            {
                str(candidate.parsed["revision"]).strip()
                for candidate in scan_result.candidates
                if candidate.parsed and candidate.parsed.get("revision") is not None
            }
        )
    )
    discovered_fields = {
        field_name
        for candidate in scan_result.candidates
        if candidate.parsed
        for field_name in candidate.parsed
    }
    field_names = tuple(
        sorted(set(governed_names) | discovered_fields | set(omitted) | set(unavailable))
    )
    governed_fields = tuple(
        _field_state(field_name, scan_result, omitted, unavailable)
        for field_name in field_names
    )
    provenance_references = tuple(
        sorted(
            f"{item.source_locator}@{item.source_revision}:"
            f"{item.source_region_or_block}:{item.field_name}"
            for item in scan_result.provenance
        )
    )
    scanner_reason_codes = _scanner_reason_codes(scan_result)
    scanner_fingerprint = _scanner_fingerprint(scan_result)
    candidate_set_fingerprint = compute_issueplan_current_state_fingerprint(candidates)
    scope_fingerprint = compute_issueplan_current_state_fingerprint(
        implementation_contract.get("scope", ())
    )
    allowlist_fingerprint = compute_issueplan_current_state_fingerprint(
        implementation_contract.get("allowlist", ())
    )
    required_tests_fingerprint = compute_issueplan_current_state_fingerprint(
        implementation_contract.get("required_tests", ())
    )
    contract_fingerprint = compute_issueplan_current_state_fingerprint(
        implementation_contract
    )

    identity = {
        "schema_version": schema_version,
        "observed_at": observed_at,
        "freshness_boundary": freshness_boundary,
        "source": source,
        "scanner_fingerprint": scanner_fingerprint,
        "candidate_set_fingerprint": candidate_set_fingerprint,
        "entity_ids": entity_ids,
        "candidate_revisions": candidate_revisions,
        "governed_fields": governed_fields,
        "intentionally_omitted_fields": omitted,
        "unavailable_fields": unavailable,
        "provenance_references": provenance_references,
        "scanner_reason_codes": scanner_reason_codes,
        "contract_scope_fingerprint": scope_fingerprint,
        "contract_allowlist_fingerprint": allowlist_fingerprint,
        "contract_required_tests_fingerprint": required_tests_fingerprint,
        "implementation_contract_fingerprint": contract_fingerprint,
        "graph_reference": graph_reference,
        "planning_result_reference": planning_result_reference,
        "handoff_reference": handoff_reference,
        "projection_complete": projection_complete,
        "projection_lookup_succeeded": projection_lookup_succeeded,
        "execution_authorized": False,
    }
    return IssuePlanCurrentStateEvidence(
        schema_version=schema_version,
        evidence_id=compute_issueplan_current_state_fingerprint(identity),
        observed_at=observed_at,
        freshness_boundary=freshness_boundary,
        source=source,
        scanner_fingerprint=scanner_fingerprint,
        candidate_set_fingerprint=candidate_set_fingerprint,
        entity_ids=entity_ids,
        candidate_revisions=candidate_revisions,
        governed_fields=governed_fields,
        intentionally_omitted_fields=omitted,
        unavailable_fields=unavailable,
        provenance_references=provenance_references,
        scanner_reason_codes=scanner_reason_codes,
        contract_scope_fingerprint=scope_fingerprint,
        contract_allowlist_fingerprint=allowlist_fingerprint,
        contract_required_tests_fingerprint=required_tests_fingerprint,
        implementation_contract_fingerprint=contract_fingerprint,
        graph_reference=graph_reference,
        planning_result_reference=planning_result_reference,
        handoff_reference=handoff_reference,
        projection_complete=projection_complete,
        projection_lookup_succeeded=projection_lookup_succeeded,
    )


def compare_issueplan_current_state(
    expected: IssuePlanCurrentStateEvidence,
    current: IssuePlanCurrentStateEvidence,
    *,
    current_scan_result: ScanResult | None = None,
) -> IssuePlanCurrentStateComparison:
    if not isinstance(expected, IssuePlanCurrentStateEvidence) or not isinstance(
        current, IssuePlanCurrentStateEvidence
    ):
        return _comparison(
            outcome=IssuePlanCurrentStateOutcome.INVALID,
            expected_id=_safe_evidence_id(expected),
            current_id=_safe_evidence_id(current),
            changed=(),
            reasons=("projection.incomplete",),
        )

    changed: list[str] = []
    reasons: list[str] = []
    invalid = not _evidence_is_valid(expected) or not _evidence_is_valid(current)
    if invalid:
        reasons.append("projection.incomplete")

    if (
        expected.schema_version not in _SUPPORTED_SCHEMA_VERSIONS
        or current.schema_version not in _SUPPORTED_SCHEMA_VERSIONS
    ):
        reasons.append("version.unsupported")

    bindings = (
        (
            "source.locator",
            expected.source.source_locator,
            current.source.source_locator,
            "source.revision-changed",
        ),
        (
            "source.revision",
            expected.source.source_revision,
            current.source.source_revision,
            "source.revision-changed",
        ),
        (
            "source.fingerprint",
            expected.source.source_fingerprint,
            current.source.source_fingerprint,
            "source.revision-changed",
        ),
        (
            "source.expected-revision",
            expected.source.expected_revision,
            current.source.expected_revision,
            "source.revision-changed",
        ),
        (
            "freshness.boundary",
            expected.freshness_boundary,
            current.freshness_boundary,
            "source.revision-changed",
        ),
        (
            "scanner.result",
            expected.scanner_fingerprint,
            current.scanner_fingerprint,
            "candidate.changed",
        ),
        (
            "candidate.set",
            expected.candidate_set_fingerprint,
            current.candidate_set_fingerprint,
            "candidate.changed",
        ),
        (
            "candidate.entities",
            expected.entity_ids,
            current.entity_ids,
            "candidate.changed",
        ),
        (
            "candidate.revisions",
            expected.candidate_revisions,
            current.candidate_revisions,
            "candidate.changed",
        ),
        (
            "governed.fields",
            expected.governed_fields,
            current.governed_fields,
            "candidate.changed",
        ),
        (
            "governed.omitted-fields",
            expected.intentionally_omitted_fields,
            current.intentionally_omitted_fields,
            "candidate.changed",
        ),
        (
            "governed.unavailable-fields",
            expected.unavailable_fields,
            current.unavailable_fields,
            "candidate.changed",
        ),
        (
            "provenance.references",
            expected.provenance_references,
            current.provenance_references,
            "candidate.changed",
        ),
        (
            "contract.fingerprint",
            expected.implementation_contract_fingerprint,
            current.implementation_contract_fingerprint,
            "contract.scope-changed",
        ),
        (
            "contract.scope",
            expected.contract_scope_fingerprint,
            current.contract_scope_fingerprint,
            "contract.scope-changed",
        ),
        (
            "contract.allowlist",
            expected.contract_allowlist_fingerprint,
            current.contract_allowlist_fingerprint,
            "contract.allowlist-changed",
        ),
        (
            "contract.required-tests",
            expected.contract_required_tests_fingerprint,
            current.contract_required_tests_fingerprint,
            "contract.required-tests-changed",
        ),
        (
            "graph.reference",
            expected.graph_reference,
            current.graph_reference,
            "contract.scope-changed",
        ),
        (
            "planning-result.reference",
            expected.planning_result_reference,
            current.planning_result_reference,
            "contract.scope-changed",
        ),
        (
            "handoff.reference",
            expected.handoff_reference,
            current.handoff_reference,
            "contract.scope-changed",
        ),
    )
    for name, expected_value, current_value, reason in bindings:
        if expected_value != current_value:
            changed.append(name)
            reasons.append(reason)

    for evidence in (expected, current):
        reasons.extend(evidence.scanner_reason_codes)
        if not evidence.source.accessible:
            reasons.append("source.inaccessible")
        if not evidence.source.retrieval_complete:
            reasons.append("source.partial")
        if not evidence.source.pagination_complete:
            reasons.append("source.unknown-pagination")
        if evidence.source.source_family != "github-issue":
            reasons.append("source.unsupported")
        if (
            evidence.source.expected_revision is not None
            and evidence.source.expected_revision != evidence.source.source_revision
        ):
            reasons.append("source.revision-changed")
        if not evidence.projection_complete:
            reasons.append("projection.incomplete")
        if not evidence.projection_lookup_succeeded:
            reasons.append("projection.lookup-failed")

    if current_scan_result is not None:
        if not isinstance(current_scan_result, ScanResult):
            invalid = True
            reasons.append("projection.incomplete")
        else:
            supplied_fingerprint = _scanner_fingerprint(current_scan_result)
            supplied_reasons = _scanner_reason_codes(current_scan_result)
            if (
                supplied_fingerprint != current.scanner_fingerprint
                or supplied_reasons != current.scanner_reason_codes
                or current_scan_result.source_locator != current.source.source_locator
                or current_scan_result.source_revision != current.source.source_revision
            ):
                invalid = True
                reasons.extend(("candidate.changed", "projection.incomplete"))

    reason_codes = tuple(sorted(set(reasons)))
    changed_bindings = tuple(sorted(set(changed)))
    if invalid or "version.unsupported" in reason_codes:
        outcome = IssuePlanCurrentStateOutcome.INVALID
    elif set(reason_codes) & _NEEDS_DECISION_REASON_CODES:
        outcome = IssuePlanCurrentStateOutcome.NEEDS_DECISION
    elif set(reason_codes) & _BLOCKED_REASON_CODES:
        outcome = IssuePlanCurrentStateOutcome.BLOCKED
    elif reason_codes or changed_bindings:
        outcome = IssuePlanCurrentStateOutcome.STALE
    else:
        outcome = IssuePlanCurrentStateOutcome.CURRENT

    return _comparison(
        outcome=outcome,
        expected_id=expected.evidence_id,
        current_id=current.evidence_id,
        changed=changed_bindings,
        reasons=reason_codes,
    )


def _comparison(
    *,
    outcome: IssuePlanCurrentStateOutcome,
    expected_id: str,
    current_id: str,
    changed: tuple[str, ...],
    reasons: tuple[str, ...],
) -> IssuePlanCurrentStateComparison:
    changed_bindings = tuple(sorted(set(changed)))
    reason_codes = tuple(sorted(set(reasons)))
    details = tuple(
        [f"changed binding: {binding}" for binding in changed_bindings]
        + [f"reason: {reason}" for reason in reason_codes]
    )
    return IssuePlanCurrentStateComparison(
        outcome=outcome,
        expected_evidence_id=expected_id,
        current_evidence_id=current_id,
        changed_bindings=changed_bindings,
        reason_codes=reason_codes,
        details=details,
    )


def _candidate_projection(scan_result: ScanResult) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "index": candidate.index,
            "raw": candidate.raw,
            "parsed": candidate.parsed,
            "malformed": candidate.malformed,
        }
        for candidate in scan_result.candidates
    )


def _scanner_fingerprint(scan_result: ScanResult) -> str:
    return compute_issueplan_current_state_fingerprint(
        {
            "source_locator": scan_result.source_locator,
            "source_revision": scan_result.source_revision,
            "findings": tuple(item.value for item in scan_result.findings),
            "adoption_class": scan_result.adoption_class.value,
            "strict_valid": scan_result.strict_valid,
            "candidates": _candidate_projection(scan_result),
            "provenance": scan_result.provenance,
            "evidence": scan_result.evidence,
            "execution_authorized": False,
        }
    )


def _scanner_reason_codes(scan_result: ScanResult) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                reason
                for finding, reason in _FINDING_REASON_CODES.items()
                if finding in scan_result.findings
            }
        )
    )


def _evidence_identity_payload(evidence: IssuePlanCurrentStateEvidence) -> dict[str, Any]:
    return {
        "schema_version": evidence.schema_version,
        "observed_at": evidence.observed_at,
        "freshness_boundary": evidence.freshness_boundary,
        "source": evidence.source,
        "scanner_fingerprint": evidence.scanner_fingerprint,
        "candidate_set_fingerprint": evidence.candidate_set_fingerprint,
        "entity_ids": evidence.entity_ids,
        "candidate_revisions": evidence.candidate_revisions,
        "governed_fields": evidence.governed_fields,
        "intentionally_omitted_fields": evidence.intentionally_omitted_fields,
        "unavailable_fields": evidence.unavailable_fields,
        "provenance_references": evidence.provenance_references,
        "scanner_reason_codes": evidence.scanner_reason_codes,
        "contract_scope_fingerprint": evidence.contract_scope_fingerprint,
        "contract_allowlist_fingerprint": evidence.contract_allowlist_fingerprint,
        "contract_required_tests_fingerprint": evidence.contract_required_tests_fingerprint,
        "implementation_contract_fingerprint": evidence.implementation_contract_fingerprint,
        "graph_reference": evidence.graph_reference,
        "planning_result_reference": evidence.planning_result_reference,
        "handoff_reference": evidence.handoff_reference,
        "projection_complete": evidence.projection_complete,
        "projection_lookup_succeeded": evidence.projection_lookup_succeeded,
        "execution_authorized": False,
    }


def _evidence_is_valid(evidence: IssuePlanCurrentStateEvidence) -> bool:
    try:
        if not all(
            isinstance(value, str) and value
            for value in (
                evidence.schema_version,
                evidence.evidence_id,
                evidence.observed_at,
                evidence.freshness_boundary,
                evidence.source.source_locator,
                evidence.source.source_revision,
                evidence.source.source_family,
            )
        ):
            return False
        if evidence.source.expected_revision is not None and not isinstance(
            evidence.source.expected_revision, str
        ):
            return False
        if not all(
            isinstance(value, bool)
            for value in (
                evidence.source.retrieval_complete,
                evidence.source.pagination_complete,
                evidence.source.accessible,
                evidence.projection_complete,
                evidence.projection_lookup_succeeded,
            )
        ):
            return False
        fingerprints = (
            evidence.evidence_id,
            evidence.source.source_fingerprint,
            evidence.scanner_fingerprint,
            evidence.candidate_set_fingerprint,
            evidence.contract_scope_fingerprint,
            evidence.contract_allowlist_fingerprint,
            evidence.contract_required_tests_fingerprint,
            evidence.implementation_contract_fingerprint,
        )
        if not all(
            isinstance(value, str) and bool(_SHA256_RE.fullmatch(value))
            for value in fingerprints
        ):
            return False
        if not set(evidence.scanner_reason_codes) <= _SCANNER_REASON_CODES:
            return False
        expected_id = compute_issueplan_current_state_fingerprint(
            _evidence_identity_payload(evidence)
        )
        return expected_id == evidence.evidence_id
    except (AttributeError, TypeError, ValueError):
        return False


def _field_state(
    field_name: str,
    scan_result: ScanResult,
    intentionally_omitted_fields: tuple[str, ...],
    unavailable_fields: tuple[str, ...],
) -> tuple[str, str, Any]:
    if field_name in unavailable_fields:
        return (field_name, "unavailable", None)
    if field_name in intentionally_omitted_fields:
        return (field_name, "intentionally-omitted", None)
    present = tuple(
        (candidate.index, _freeze(candidate.parsed[field_name]))
        for candidate in scan_result.candidates
        if candidate.parsed is not None and field_name in candidate.parsed
    )
    if not present:
        return (field_name, "absent", None)
    if all(value is None for _, value in present):
        return (field_name, "null", present)
    return (field_name, "present", present)


def _normalize_governed_fields(
    values: tuple[tuple[str, str, Any], ...],
) -> tuple[tuple[str, str, Any], ...]:
    normalized: list[tuple[str, str, Any]] = []
    for item in tuple(values):
        if not isinstance(item, (tuple, list)) or len(item) != 3:
            raise ValueError("governed_fields entries must be three-item sequences")
        field_name, state, value = item
        if not isinstance(field_name, str) or not field_name:
            raise ValueError("governed field names must be non-empty strings")
        if state not in _FIELD_STATES:
            raise ValueError("governed field state is unsupported")
        normalized.append((field_name, state, _freeze(value)))
    normalized.sort(
        key=lambda item: (
            item[0],
            item[1],
            json.dumps(_canonicalize(item[2]), sort_keys=True),
        )
    )
    return tuple(normalized)


def _normalize_strings(values: Any, field_name: str) -> tuple[str, ...]:
    if isinstance(values, str):
        raise TypeError(f"{field_name} must be a sequence of strings")
    normalized = tuple(values)
    if not all(isinstance(value, str) and value for value in normalized):
        raise TypeError(f"{field_name} must contain non-empty strings")
    return tuple(sorted(set(normalized)))


def _validate_build_inputs(
    *,
    envelope: SourceEnvelope,
    scan_result: ScanResult,
    observed_at: str,
    freshness_boundary: str,
    implementation_contract: Mapping[str, Any],
    schema_version: str,
    projection_complete: bool,
    projection_lookup_succeeded: bool,
) -> None:
    if not isinstance(envelope, SourceEnvelope):
        raise TypeError("envelope must be a SourceEnvelope")
    if not isinstance(scan_result, ScanResult):
        raise TypeError("scan_result must be a ScanResult")
    if not isinstance(implementation_contract, Mapping):
        raise TypeError("implementation_contract must be a mapping")
    if not all(
        isinstance(value, str) and value
        for value in (observed_at, freshness_boundary, schema_version)
    ):
        raise TypeError("timestamps, freshness boundary, and schema version must be strings")
    if not isinstance(envelope.content, str):
        raise TypeError("source content must be a string")
    if not isinstance(projection_complete, bool) or not isinstance(
        projection_lookup_succeeded, bool
    ):
        raise TypeError("projection status values must be booleans")


def _safe_evidence_id(value: object) -> str:
    evidence_id = getattr(value, "evidence_id", None)
    return evidence_id if isinstance(evidence_id, str) else "<invalid>"


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return tuple(
            (str(key), _freeze(item))
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        )
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return tuple(
            sorted(
                (_freeze(item) for item in value),
                key=lambda item: json.dumps(_canonicalize(item), sort_keys=True),
            )
        )
    return value


def _canonicalize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return _canonicalize(asdict(value))
    if isinstance(value, Mapping):
        return {
            str(key): _canonicalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_canonicalize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        items = (_canonicalize(item) for item in value)
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
    return value
