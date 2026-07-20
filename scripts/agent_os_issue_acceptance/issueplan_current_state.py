from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Literal, Mapping

from .issueplan_scanner import ScanFinding, ScanResult, SourceEnvelope

ISSUEPLAN_CURRENT_STATE_SCHEMA_VERSION = "1.0"
_SUPPORTED = frozenset({ISSUEPLAN_CURRENT_STATE_SCHEMA_VERSION})
_REQUIRED_CONTRACT_FIELDS = frozenset({"scope", "allowlist", "required_tests"})
_FIELD_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_APPROVED_REASONS = frozenset(
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
_AMBIGUOUS_REASONS = frozenset(
    {
        "scanner.multiple-identical",
        "scanner.multiple-conflicting",
        "scanner.malformed-candidate",
        "scanner.unknown-governed-field",
        "identity.quarantined",
    }
)
_STALE_REASONS = frozenset(
    {
        "source.revision-changed",
        "source.freshness-boundary-changed",
        "candidate.changed",
        "contract.scope-changed",
        "contract.allowlist-changed",
        "contract.required-tests-changed",
    }
)
_BLOCKING_REASONS = _APPROVED_REASONS - _AMBIGUOUS_REASONS - _STALE_REASONS - {
    "version.unsupported"
}
_FINDING_REASONS = {
    ScanFinding.METADATA_DUPLICATED_IDENTICAL: "scanner.multiple-identical",
    ScanFinding.METADATA_CONFLICTING: "scanner.multiple-conflicting",
    ScanFinding.METADATA_MALFORMED: "scanner.malformed-candidate",
    ScanFinding.UNKNOWN_GOVERNED_FIELD: "scanner.unknown-governed-field",
    ScanFinding.IDENTITY_FINDING_PRESENT: "identity.quarantined",
}
_FIELD_STATES = frozenset(
    {"absent", "null", "intentionally-omitted", "unavailable", "present"}
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
    source_revision: str
    source_family: str
    retrieval_complete: bool
    pagination_complete: bool
    accessible: bool
    expected_revision: str | None
    source_fingerprint: str

    def __post_init__(self) -> None:
        for name in ("source_locator", "source_revision", "source_family"):
            _require_text(getattr(self, name), name)
        if self.expected_revision is not None:
            _require_text(self.expected_revision, "expected_revision")
        for name in ("retrieval_complete", "pagination_complete", "accessible"):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a boolean")
        _require_sha(self.source_fingerprint, "source_fingerprint")


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
        for name in ("schema_version", "observed_at", "freshness_boundary"):
            _require_text(getattr(self, name), name)
        for name in (
            "evidence_id",
            "scanner_fingerprint",
            "candidate_set_fingerprint",
            "contract_scope_fingerprint",
            "contract_allowlist_fingerprint",
            "contract_required_tests_fingerprint",
            "implementation_contract_fingerprint",
        ):
            _require_sha(getattr(self, name), name)
        for name in ("projection_complete", "projection_lookup_succeeded"):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a boolean")
        for name in ("graph_reference", "planning_result_reference", "handoff_reference"):
            value = getattr(self, name)
            if value is not None:
                _require_text(value, name)
        entity_ids = _strings(self.entity_ids, "entity_ids")
        revisions = _strings(self.candidate_revisions, "candidate_revisions")
        omitted = _field_names(
            self.intentionally_omitted_fields, "intentionally_omitted_fields"
        )
        unavailable = _field_names(self.unavailable_fields, "unavailable_fields")
        if set(omitted) & set(unavailable):
            raise ValueError("omitted and unavailable field inventories must be disjoint")
        provenance = _strings(self.provenance_references, "provenance_references")
        scanner_reasons = tuple(sorted(set(self.scanner_reason_codes)))
        if not set(scanner_reasons) <= _AMBIGUOUS_REASONS:
            raise ValueError("scanner_reason_codes must use the bounded scanner vocabulary")
        object.__setattr__(self, "entity_ids", entity_ids)
        object.__setattr__(self, "candidate_revisions", revisions)
        object.__setattr__(self, "intentionally_omitted_fields", omitted)
        object.__setattr__(self, "unavailable_fields", unavailable)
        object.__setattr__(self, "provenance_references", provenance)
        object.__setattr__(self, "scanner_reason_codes", scanner_reasons)
        object.__setattr__(self, "governed_fields", _governed(self.governed_fields))


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
        changed = _strings(self.changed_bindings, "changed_bindings")
        reasons = tuple(sorted(set(self.reason_codes)))
        if not set(reasons) <= _APPROVED_REASONS:
            raise ValueError("reason_codes must use the bounded IDB2A vocabulary")
        object.__setattr__(self, "changed_bindings", changed)
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(self, "details", tuple(str(item) for item in self.details))


def compute_issueplan_current_state_fingerprint(value: Any) -> str:
    raw = json.dumps(
        _canonical(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


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
    contract = _build_inputs(
        envelope,
        scan_result,
        observed_at,
        freshness_boundary,
        implementation_contract,
        schema_version,
        projection_complete,
        projection_lookup_succeeded,
    )
    if (envelope.source_locator, envelope.source_revision) != (
        scan_result.source_locator,
        scan_result.source_revision,
    ):
        raise ValueError("scan_result must bind to the supplied source envelope")
    if scan_result.execution_authorized is not False:
        raise ValueError("scan_result cannot authorize execution")
    names = _field_names(governed_field_names, "governed_field_names")
    omitted = _field_names(
        intentionally_omitted_fields, "intentionally_omitted_fields"
    )
    unavailable = _field_names(unavailable_fields, "unavailable_fields")
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
                str(item.parsed["entity_id"]).strip()
                for item in scan_result.candidates
                if item.parsed and item.parsed.get("entity_id") is not None
            }
        )
    )
    revisions = tuple(
        sorted(
            {
                str(item.parsed["revision"]).strip()
                for item in scan_result.candidates
                if item.parsed and item.parsed.get("revision") is not None
            }
        )
    )
    discovered = {
        name
        for item in scan_result.candidates
        if item.parsed
        for name in item.parsed
    }
    all_names = tuple(sorted(set(names) | discovered | set(omitted) | set(unavailable)))
    fields = tuple(_field_state(name, scan_result, omitted, unavailable) for name in all_names)
    provenance = tuple(
        sorted(
            f"{item.source_locator}@{item.source_revision}:"
            f"{item.source_region_or_block}:{item.field_name}"
            for item in scan_result.provenance
        )
    )
    scanner_reasons = _scanner_reasons(scan_result)
    scanner_fingerprint = _scanner_fingerprint(scan_result)
    candidate_fingerprint = compute_issueplan_current_state_fingerprint(candidates)
    scope_fingerprint = compute_issueplan_current_state_fingerprint(contract["scope"])
    allowlist_fingerprint = compute_issueplan_current_state_fingerprint(
        contract["allowlist"]
    )
    tests_fingerprint = compute_issueplan_current_state_fingerprint(
        contract["required_tests"]
    )
    contract_fingerprint = compute_issueplan_current_state_fingerprint(contract)
    values = dict(
        schema_version=schema_version,
        observed_at=observed_at,
        freshness_boundary=freshness_boundary,
        source=source,
        scanner_fingerprint=scanner_fingerprint,
        candidate_set_fingerprint=candidate_fingerprint,
        entity_ids=entity_ids,
        candidate_revisions=revisions,
        governed_fields=fields,
        intentionally_omitted_fields=omitted,
        unavailable_fields=unavailable,
        provenance_references=provenance,
        scanner_reason_codes=scanner_reasons,
        contract_scope_fingerprint=scope_fingerprint,
        contract_allowlist_fingerprint=allowlist_fingerprint,
        contract_required_tests_fingerprint=tests_fingerprint,
        implementation_contract_fingerprint=contract_fingerprint,
        graph_reference=graph_reference,
        planning_result_reference=planning_result_reference,
        handoff_reference=handoff_reference,
        projection_complete=projection_complete,
        projection_lookup_succeeded=projection_lookup_succeeded,
    )
    evidence_id = compute_issueplan_current_state_fingerprint(
        {**values, "execution_authorized": False}
    )
    return IssuePlanCurrentStateEvidence(evidence_id=evidence_id, **values)


def compare_issueplan_current_state(
    expected: IssuePlanCurrentStateEvidence,
    current: IssuePlanCurrentStateEvidence,
    *,
    current_scan_result: ScanResult | None = None,
) -> IssuePlanCurrentStateComparison:
    if not isinstance(expected, IssuePlanCurrentStateEvidence) or not isinstance(
        current, IssuePlanCurrentStateEvidence
    ):
        return _result(
            IssuePlanCurrentStateOutcome.INVALID,
            _safe_id(expected),
            _safe_id(current),
            (),
            ("projection.incomplete",),
        )
    changed: list[str] = []
    reasons: list[str] = []
    invalid = not _evidence_valid(expected) or not _evidence_valid(current)
    if invalid:
        reasons.append("projection.incomplete")
    if expected.schema_version not in _SUPPORTED or current.schema_version not in _SUPPORTED:
        reasons.append("version.unsupported")

    bindings: tuple[tuple[str, Any, Any, str | None], ...] = (
        ("source.locator", expected.source.source_locator, current.source.source_locator, "source.revision-changed"),
        ("source.revision", expected.source.source_revision, current.source.source_revision, "source.revision-changed"),
        ("source.fingerprint", expected.source.source_fingerprint, current.source.source_fingerprint, "source.revision-changed"),
        ("source.expected-revision", expected.source.expected_revision, current.source.expected_revision, "source.revision-changed"),
        ("freshness.boundary", expected.freshness_boundary, current.freshness_boundary, "source.freshness-boundary-changed"),
        ("scanner.result", expected.scanner_fingerprint, current.scanner_fingerprint, "candidate.changed"),
        ("candidate.set", expected.candidate_set_fingerprint, current.candidate_set_fingerprint, "candidate.changed"),
        ("candidate.entities", expected.entity_ids, current.entity_ids, "candidate.changed"),
        ("candidate.revisions", expected.candidate_revisions, current.candidate_revisions, "candidate.changed"),
        ("governed.fields", expected.governed_fields, current.governed_fields, "candidate.changed"),
        ("governed.omitted-fields", expected.intentionally_omitted_fields, current.intentionally_omitted_fields, "candidate.changed"),
        ("governed.unavailable-fields", expected.unavailable_fields, current.unavailable_fields, "candidate.changed"),
        ("provenance.references", expected.provenance_references, current.provenance_references, "candidate.changed"),
        ("contract.fingerprint", expected.implementation_contract_fingerprint, current.implementation_contract_fingerprint, "contract.scope-changed"),
        ("contract.scope", expected.contract_scope_fingerprint, current.contract_scope_fingerprint, "contract.scope-changed"),
        ("contract.allowlist", expected.contract_allowlist_fingerprint, current.contract_allowlist_fingerprint, "contract.allowlist-changed"),
        ("contract.required-tests", expected.contract_required_tests_fingerprint, current.contract_required_tests_fingerprint, "contract.required-tests-changed"),
        ("graph.reference", expected.graph_reference, current.graph_reference, None),
        ("planning-result.reference", expected.planning_result_reference, current.planning_result_reference, None),
        ("handoff.reference", expected.handoff_reference, current.handoff_reference, None),
    )
    for name, old, new, reason in bindings:
        if old != new:
            changed.append(name)
            if reason:
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
        if not isinstance(current_scan_result, ScanResult) or (
            _scanner_fingerprint(current_scan_result) != current.scanner_fingerprint
            or _scanner_reasons(current_scan_result) != current.scanner_reason_codes
            or current_scan_result.source_locator != current.source.source_locator
            or current_scan_result.source_revision != current.source.source_revision
            or current_scan_result.execution_authorized is not False
        ):
            invalid = True
            reasons.extend(("candidate.changed", "projection.incomplete"))

    reason_codes = tuple(sorted(set(reasons)))
    changed_bindings = tuple(sorted(set(changed)))
    if invalid or "version.unsupported" in reason_codes:
        outcome = IssuePlanCurrentStateOutcome.INVALID
    elif set(reason_codes) & _AMBIGUOUS_REASONS:
        outcome = IssuePlanCurrentStateOutcome.NEEDS_DECISION
    elif set(reason_codes) & _BLOCKING_REASONS:
        outcome = IssuePlanCurrentStateOutcome.BLOCKED
    elif reason_codes or changed_bindings:
        outcome = IssuePlanCurrentStateOutcome.STALE
    else:
        outcome = IssuePlanCurrentStateOutcome.CURRENT
    return _result(
        outcome,
        expected.evidence_id,
        current.evidence_id,
        changed_bindings,
        reason_codes,
    )


def _result(
    outcome: IssuePlanCurrentStateOutcome,
    expected_id: str,
    current_id: str,
    changed: tuple[str, ...],
    reasons: tuple[str, ...],
) -> IssuePlanCurrentStateComparison:
    changed = tuple(sorted(set(changed)))
    reasons = tuple(sorted(set(reasons)))
    details = tuple(
        [f"changed binding: {item}" for item in changed]
        + [f"reason: {item}" for item in reasons]
    )
    return IssuePlanCurrentStateComparison(
        outcome, expected_id, current_id, changed, reasons, details
    )


def _candidate_projection(scan_result: ScanResult) -> tuple[dict[str, Any], ...]:
    return tuple(
        dict(
            index=item.index,
            raw=item.raw,
            parsed=item.parsed,
            malformed=item.malformed,
        )
        for item in scan_result.candidates
    )


def _scanner_fingerprint(scan_result: ScanResult) -> str:
    return compute_issueplan_current_state_fingerprint(
        dict(
            source_locator=scan_result.source_locator,
            source_revision=scan_result.source_revision,
            findings=tuple(item.value for item in scan_result.findings),
            adoption_class=scan_result.adoption_class.value,
            strict_valid=scan_result.strict_valid,
            candidates=_candidate_projection(scan_result),
            provenance=scan_result.provenance,
            evidence=scan_result.evidence,
            execution_authorized=False,
        )
    )


def _scanner_reasons(scan_result: ScanResult) -> tuple[str, ...]:
    return tuple(
        sorted(
            reason
            for finding, reason in _FINDING_REASONS.items()
            if finding in scan_result.findings
        )
    )


def _identity(evidence: IssuePlanCurrentStateEvidence) -> dict[str, Any]:
    values = {
        name: value
        for name, value in evidence.__dict__.items()
        if name != "evidence_id"
    }
    values["execution_authorized"] = False
    return values


def _evidence_valid(evidence: IssuePlanCurrentStateEvidence) -> bool:
    try:
        return evidence.evidence_id == compute_issueplan_current_state_fingerprint(
            _identity(evidence)
        )
    except (AttributeError, TypeError, ValueError):
        return False


def _field_state(
    name: str,
    scan_result: ScanResult,
    omitted: tuple[str, ...],
    unavailable: tuple[str, ...],
) -> tuple[str, str, Any]:
    if name in unavailable:
        return (name, "unavailable", None)
    if name in omitted:
        return (name, "intentionally-omitted", None)
    present = tuple(
        (item.index, _freeze(item.parsed[name]))
        for item in scan_result.candidates
        if item.parsed is not None and name in item.parsed
    )
    if not present:
        return (name, "absent", None)
    if all(value is None for _, value in present):
        return (name, "null", present)
    return (name, "present", present)


def _governed(values: Any) -> tuple[tuple[str, str, Any], ...]:
    normalized = []
    for item in tuple(values):
        if not isinstance(item, (tuple, list)) or len(item) != 3:
            raise ValueError("governed_fields entries must be three-item sequences")
        name, state, value = item
        _field_name(name)
        if state not in _FIELD_STATES:
            raise ValueError("governed field state is unsupported")
        normalized.append((name, state, _freeze(value)))
    normalized.sort(key=lambda item: (item[0], item[1], json.dumps(_canonical(item[2]), sort_keys=True)))
    return tuple(normalized)


def _strings(values: Any, name: str) -> tuple[str, ...]:
    if isinstance(values, str):
        raise TypeError(f"{name} must be a sequence of strings")
    try:
        values = tuple(values)
    except TypeError as exc:
        raise TypeError(f"{name} must be a sequence of strings") from exc
    if not all(isinstance(item, str) and item and item == item.strip() for item in values):
        raise TypeError(f"{name} must contain non-empty trimmed strings")
    return tuple(sorted(set(values)))


def _field_names(values: Any, name: str) -> tuple[str, ...]:
    values = _strings(values, name)
    for value in values:
        _field_name(value)
    return values


def _field_name(value: object) -> None:
    if not isinstance(value, str) or not _FIELD_NAME_RE.fullmatch(value):
        raise ValueError("governed field names must be bounded identifiers")


def _build_inputs(
    envelope: SourceEnvelope,
    scan_result: ScanResult,
    observed_at: str,
    freshness_boundary: str,
    contract: Mapping[str, Any],
    schema_version: str,
    projection_complete: bool,
    projection_lookup_succeeded: bool,
) -> dict[str, Any]:
    if not isinstance(envelope, SourceEnvelope):
        raise TypeError("envelope must be a SourceEnvelope")
    if not isinstance(scan_result, ScanResult):
        raise TypeError("scan_result must be a ScanResult")
    if not isinstance(contract, Mapping):
        raise TypeError("implementation_contract must be a mapping")
    for name, value in (
        ("observed_at", observed_at),
        ("freshness_boundary", freshness_boundary),
        ("schema_version", schema_version),
    ):
        _require_text(value, name)
    if schema_version not in _SUPPORTED:
        raise ValueError("schema_version is unsupported")
    if not isinstance(envelope.content, str):
        raise TypeError("source content must be a string")
    if not isinstance(projection_complete, bool) or not isinstance(
        projection_lookup_succeeded, bool
    ):
        raise TypeError("projection status values must be booleans")
    missing = _REQUIRED_CONTRACT_FIELDS - set(contract)
    if missing:
        raise ValueError(
            "implementation_contract is missing required fields: "
            + ", ".join(sorted(missing))
        )
    result = dict(contract)
    for name in _REQUIRED_CONTRACT_FIELDS:
        _contract_collection(result[name], name)
    return result


def _contract_collection(value: object, name: str) -> None:
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(
        value, (tuple, list, set, frozenset)
    ):
        raise TypeError(f"implementation_contract.{name} has an unsupported shape")
    if not value:
        raise ValueError(f"implementation_contract.{name} must not be empty")
    if not all(isinstance(item, str) and item and item == item.strip() for item in value):
        raise TypeError(
            f"implementation_contract.{name} must contain non-empty trimmed strings"
        )


def _require_text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise TypeError(f"{name} must be a non-empty trimmed string")


def _require_sha(value: object, name: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")


def _safe_id(value: object) -> str:
    evidence_id = getattr(value, "evidence_id", None)
    return evidence_id if isinstance(evidence_id, str) else "<invalid>"


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return tuple((str(key), _freeze(item)) for key, item in sorted(value.items(), key=lambda pair: str(pair[0])))
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return tuple(sorted((_freeze(item) for item in value), key=lambda item: json.dumps(_canonical(item), sort_keys=True)))
    return value


def _canonical(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return _canonical(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if isinstance(value, (set, frozenset)):
        items = (_canonical(item) for item in value)
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
    return value
