from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Mapping

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


class IssuePlanCurrentStateOutcome(str, Enum):
    CURRENT = "current"
    STALE = "stale"
    BLOCKED = "blocked"


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
    contract_scope_fingerprint: str
    contract_allowlist_fingerprint: str
    contract_required_tests_fingerprint: str
    implementation_contract_fingerprint: str
    graph_reference: str | None = None
    planning_result_reference: str | None = None
    handoff_reference: str | None = None
    projection_complete: bool = True
    projection_lookup_succeeded: bool = True
    execution_authorized: bool = False


@dataclass(frozen=True)
class IssuePlanCurrentStateComparison:
    outcome: IssuePlanCurrentStateOutcome
    expected_evidence_id: str
    current_evidence_id: str
    changed_bindings: tuple[str, ...]
    reason_codes: tuple[str, ...]
    details: tuple[str, ...]
    execution_authorized: bool = False


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
    candidates = tuple(
        {
            "index": candidate.index,
            "raw": candidate.raw,
            "parsed": candidate.parsed,
            "malformed": candidate.malformed,
        }
        for candidate in scan_result.candidates
    )
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
    omitted = tuple(sorted(set(intentionally_omitted_fields)))
    unavailable = tuple(sorted(set(unavailable_fields)))
    discovered_fields = {
        field_name
        for candidate in scan_result.candidates
        if candidate.parsed
        for field_name in candidate.parsed
    }
    field_names = tuple(
        sorted(set(governed_field_names) | discovered_fields | set(omitted) | set(unavailable))
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
    scanner_fingerprint = compute_issueplan_current_state_fingerprint(
        {
            "source_locator": scan_result.source_locator,
            "source_revision": scan_result.source_revision,
            "findings": tuple(item.value for item in scan_result.findings),
            "adoption_class": scan_result.adoption_class.value,
            "strict_valid": scan_result.strict_valid,
            "candidates": candidates,
            "provenance": scan_result.provenance,
            "evidence": scan_result.evidence,
            "execution_authorized": False,
        }
    )
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
        contract_scope_fingerprint=scope_fingerprint,
        contract_allowlist_fingerprint=allowlist_fingerprint,
        contract_required_tests_fingerprint=required_tests_fingerprint,
        implementation_contract_fingerprint=contract_fingerprint,
        graph_reference=graph_reference,
        planning_result_reference=planning_result_reference,
        handoff_reference=handoff_reference,
        projection_complete=projection_complete,
        projection_lookup_succeeded=projection_lookup_succeeded,
        execution_authorized=False,
    )


def compare_issueplan_current_state(
    expected: IssuePlanCurrentStateEvidence,
    current: IssuePlanCurrentStateEvidence,
    *,
    current_scan_result: ScanResult | None = None,
) -> IssuePlanCurrentStateComparison:
    changed: list[str] = []
    reasons: list[str] = []

    if (
        expected.schema_version not in _SUPPORTED_SCHEMA_VERSIONS
        or current.schema_version not in _SUPPORTED_SCHEMA_VERSIONS
    ):
        reasons.append("version.unsupported")

    bindings = (
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
            "candidate.set",
            expected.candidate_set_fingerprint,
            current.candidate_set_fingerprint,
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

    if not current.source.accessible:
        reasons.append("source.inaccessible")
    if not current.source.retrieval_complete:
        reasons.append("source.partial")
    if not current.source.pagination_complete:
        reasons.append("source.unknown-pagination")
    if current.source.source_family != "github-issue":
        reasons.append("source.unsupported")
    if not current.projection_complete:
        reasons.append("projection.incomplete")
    if not current.projection_lookup_succeeded:
        reasons.append("projection.lookup-failed")

    if current_scan_result is not None:
        finding_reasons = {
            ScanFinding.METADATA_DUPLICATED_IDENTICAL: "scanner.multiple-identical",
            ScanFinding.METADATA_CONFLICTING: "scanner.multiple-conflicting",
            ScanFinding.METADATA_MALFORMED: "scanner.malformed-candidate",
            ScanFinding.UNKNOWN_GOVERNED_FIELD: "scanner.unknown-governed-field",
            ScanFinding.IDENTITY_FINDING_PRESENT: "identity.quarantined",
        }
        for finding, reason in finding_reasons.items():
            if finding in current_scan_result.findings:
                reasons.append(reason)

    reason_codes = tuple(dict.fromkeys(reasons))
    if not set(reason_codes) <= _APPROVED_REASON_CODES:
        raise ValueError("comparison emitted an unapproved reason code")
    changed_bindings = tuple(sorted(set(changed)))
    blocking_reasons = _APPROVED_REASON_CODES - {
        "source.revision-changed",
        "candidate.changed",
        "contract.scope-changed",
        "contract.allowlist-changed",
        "contract.required-tests-changed",
    }
    if any(code in blocking_reasons for code in reason_codes):
        outcome = IssuePlanCurrentStateOutcome.BLOCKED
    elif reason_codes or changed_bindings:
        outcome = IssuePlanCurrentStateOutcome.STALE
    else:
        outcome = IssuePlanCurrentStateOutcome.CURRENT

    details = tuple(
        [f"changed binding: {binding}" for binding in changed_bindings]
        + [f"reason: {reason}" for reason in reason_codes]
    )
    return IssuePlanCurrentStateComparison(
        outcome=outcome,
        expected_evidence_id=expected.evidence_id,
        current_evidence_id=current.evidence_id,
        changed_bindings=changed_bindings,
        reason_codes=reason_codes,
        details=details,
        execution_authorized=False,
    )


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
