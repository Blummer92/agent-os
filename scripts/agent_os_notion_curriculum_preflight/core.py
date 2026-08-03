"""Pure-local evaluation for supplied Notion curriculum target evidence.

The evaluator does not discover targets, read connected systems, inspect the
filesystem or environment, use credentials, call subprocesses, or perform writes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from instructional_workflow_contracts.common import (
    ContractValidationError,
    canonical_json_bytes,
    freeze_json,
    sanitize_detail,
    sha256_hex,
    validate_and_normalize_json,
    validate_timestamp,
)

from .models import (
    CONTRACT_VERSION,
    EVIDENCE_TTL_HOURS,
    FINDING_CODES,
    MAX_EVIDENCE_BYTES,
    MAX_MAPPINGS,
    MAX_PROPERTIES,
    MAX_RELATIONS,
    MAX_VIEWS,
    PROPOSED_IMPLEMENTATION_SCOPE,
    SUPPORTED_CONTRACT_NAMES,
    SUPPORTED_NOTION_API_VERSION,
    ContractMappingCandidate,
    NotionAuthorizationEvidence,
    NotionCurriculumPreflightError,
    NotionCurriculumPreflightEvidence,
    NotionCurriculumPreflightReport,
    NotionLimitEvidence,
    NotionPropertyEvidence,
    NotionRelationEvidence,
    NotionViewEvidence,
    PreflightStatus,
)

_TOP_LEVEL_FIELDS = frozenset(
    {
        "contract_version",
        "record_revision",
        "evidence_id",
        "workspace_context_id",
        "notion_api_version",
        "database_id",
        "data_source_id",
        "evidence_source",
        "verified_at",
        "schema_fingerprint",
        "view_fingerprint",
        "properties",
        "relations",
        "views",
        "limits",
        "contract_mappings",
        "authorization",
    }
)
_PROPERTY_FIELDS = frozenset(
    {
        "property_id",
        "display_name",
        "property_type",
        "value_owner",
        "record_owner",
        "classification",
        "current_write_mode",
        "readiness_effect",
        "generation_effect",
        "relation_target_data_source_id",
        "maximum_value_size",
        "evidence_state",
    }
)
_RELATION_FIELDS = frozenset(
    {
        "property_id",
        "source_data_source_id",
        "target_data_source_id",
        "target_shared_with_connection",
        "access_state",
        "ambiguity_state",
    }
)
_VIEW_FIELDS = frozenset(
    {
        "view_id",
        "parent_data_source_id",
        "view_type",
        "capability_state",
        "filter_sort_compatibility",
        "evidence_state",
    }
)
_MAPPING_FIELDS = frozenset(
    {
        "contract_name",
        "contract_version",
        "source_field",
        "target_property_id",
        "projection_mode",
        "owner_compatible",
        "type_compatible",
        "bounded",
        "governed_field",
    }
)
_LIMIT_FIELDS = frozenset(
    {
        "page_size_limit",
        "pagination_complete",
        "property_value_limit",
        "collection_limit",
        "payload_limit",
        "rate_limit_policy_known",
        "retry_after_supported",
    }
)
_AUTHORIZATION_FIELDS = frozenset(
    {
        "live_read_authorized",
        "write_authorized",
        "schema_change_authorized",
        "view_change_authorized",
        "production_authorized",
        "publication_authorized",
    }
)

_INVALID_FINGERPRINT = "0" * 64
_INVALID_TARGET = ("unavailable", "unavailable", "unavailable")
_INVALID_EVIDENCE_ID = "invalid-evidence"
_INVALID_EXPIRY = "1970-01-01T00:00:00Z"
_ROLLBACK_NOTE = (
    "Remove or revert the local preflight implementation; no external cleanup is required."
)

_MANUAL_STEPS = {
    "notion-target-unverified": "Verify the exact live target through a separately authorized read.",
    "notion-schema-stale": "Refresh and re-supply the exact schema fingerprint.",
    "notion-view-stale": "Refresh and re-supply the exact view fingerprint.",
    "notion-relation-ambiguous": "Confirm relation target identity and access with the target owner.",
    "notion-rate-limit-policy-unknown": "Confirm the pinned API rate-limit and Retry-After behavior.",
    "notion-view-capability-unsupported": "Confirm supported view operations for the pinned API version.",
    "notion-view-target-ambiguous": "Confirm the exact view ID and parent data-source ID.",
    "notion-evidence-expired": "Obtain fresh target evidence before implementation planning.",
    "notion-migration-not-reversible": "Provide a bounded rollback or disable path.",
}


def _require_mapping(value: object, name: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise NotionCurriculumPreflightError(
            "notion-target-unverified", f"{name} must be an exact built-in mapping"
        )
    return value


def _require_fields(value: dict[str, Any], expected: frozenset[str], name: str) -> None:
    actual = frozenset(value)
    if actual != expected:
        raise NotionCurriculumPreflightError(
            "notion-target-unverified", f"{name} fields are missing or unsupported"
        )


def _require_list(value: object, name: str, maximum: int) -> list[Any]:
    if type(value) is not list:
        raise NotionCurriculumPreflightError(
            "notion-target-unverified", f"{name} must be an exact built-in list"
        )
    if len(value) > maximum:
        raise NotionCurriculumPreflightError(
            "notion-value-limit-exceeded", f"{name} exceeds its collection bound"
        )
    return value


def parse_preflight_evidence(payload: object) -> NotionCurriculumPreflightEvidence:
    """Normalize and reconstruct one caller-supplied evidence packet."""

    try:
        normalized = validate_and_normalize_json(payload, max_bytes=MAX_EVIDENCE_BYTES)
    except ContractValidationError as exc:
        code = (
            "notion-value-limit-exceeded"
            if exc.reason_code == "handoff-oversized"
            else "notion-target-unverified"
        )
        raise NotionCurriculumPreflightError(code, exc.detail) from exc

    root = _require_mapping(normalized, "preflight evidence")
    _require_fields(root, _TOP_LEVEL_FIELDS, "preflight evidence")

    property_values = _require_list(root["properties"], "properties", MAX_PROPERTIES)
    properties: list[NotionPropertyEvidence] = []
    for item in property_values:
        record = _require_mapping(item, "property evidence")
        _require_fields(record, _PROPERTY_FIELDS, "property evidence")
        properties.append(NotionPropertyEvidence(**record))

    relation_values = _require_list(root["relations"], "relations", MAX_RELATIONS)
    relations: list[NotionRelationEvidence] = []
    for item in relation_values:
        record = _require_mapping(item, "relation evidence")
        _require_fields(record, _RELATION_FIELDS, "relation evidence")
        relations.append(NotionRelationEvidence(**record))

    view_values = _require_list(root["views"], "views", MAX_VIEWS)
    views: list[NotionViewEvidence] = []
    for item in view_values:
        record = _require_mapping(item, "view evidence")
        _require_fields(record, _VIEW_FIELDS, "view evidence")
        views.append(NotionViewEvidence(**record))

    mapping_values = _require_list(root["contract_mappings"], "contract_mappings", MAX_MAPPINGS)
    mappings: list[ContractMappingCandidate] = []
    for item in mapping_values:
        record = _require_mapping(item, "contract mapping")
        _require_fields(record, _MAPPING_FIELDS, "contract mapping")
        mappings.append(ContractMappingCandidate(**record))

    limit_values = _require_mapping(root["limits"], "limits")
    _require_fields(limit_values, _LIMIT_FIELDS, "limits")
    authorization_values = _require_mapping(root["authorization"], "authorization")
    _require_fields(authorization_values, _AUTHORIZATION_FIELDS, "authorization")

    return NotionCurriculumPreflightEvidence(
        contract_version=root["contract_version"],
        record_revision=root["record_revision"],
        evidence_id=root["evidence_id"],
        workspace_context_id=root["workspace_context_id"],
        notion_api_version=root["notion_api_version"],
        database_id=root["database_id"],
        data_source_id=root["data_source_id"],
        evidence_source=root["evidence_source"],
        verified_at=root["verified_at"],
        schema_fingerprint=root["schema_fingerprint"],
        view_fingerprint=root["view_fingerprint"],
        properties=tuple(properties),
        relations=tuple(relations),
        views=tuple(views),
        limits=NotionLimitEvidence(**limit_values),
        contract_mappings=tuple(mappings),
        authorization=NotionAuthorizationEvidence(**authorization_values),
    )


def _parse_utc(value: str) -> datetime:
    validate_timestamp(value, "evaluation timestamp")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _invalid_report(code: str, detail: str) -> NotionCurriculumPreflightReport:
    if code not in FINDING_CODES:
        code = "notion-target-unverified"
    safe_detail = sanitize_detail(detail)
    manual = ()
    if safe_detail:
        manual = ("Correct the malformed supplied evidence and rerun the pure-local preflight.",)
    return NotionCurriculumPreflightReport(
        status=PreflightStatus.INVALID,
        evidence_id=_INVALID_EVIDENCE_ID,
        evidence_fingerprint=_INVALID_FINGERPRINT,
        exact_target_tuple=_INVALID_TARGET,
        compatible_mappings=(),
        unsupported_mappings=(),
        stale_mappings=(),
        missing_mappings=(),
        conflicting_mappings=(),
        relation_findings=(),
        view_findings=(),
        limit_findings=(code,) if code in {
            "notion-value-limit-exceeded",
            "notion-pagination-incomplete",
            "notion-rate-limit-policy-unknown",
        } else (),
        authority_findings=(code,) if code in {
            "notion-write-mode-not-authorized",
            "notion-view-write-not-authorized",
            "notion-governed-field-write-proposed",
        } else (),
        reason_codes=(code,),
        blockers=(),
        required_manual_verifications=manual,
        proposed_implementation_scope=PROPOSED_IMPLEMENTATION_SCOPE,
        evidence_expires_at=_INVALID_EXPIRY,
        rollback_note=_ROLLBACK_NOTE,
    )


def evaluate_notion_curriculum_preflight(
    payload: object,
    *,
    evaluated_at: str,
) -> NotionCurriculumPreflightReport:
    """Return a deterministic, bounded report from supplied evidence only."""

    try:
        evaluation_time = _parse_utc(evaluated_at)
        evidence = parse_preflight_evidence(payload)
    except NotionCurriculumPreflightError as exc:
        return _invalid_report(exc.finding_code, exc.detail)
    except ContractValidationError as exc:
        return _invalid_report("notion-target-unverified", exc.detail)
    except (TypeError, ValueError) as exc:
        return _invalid_report("notion-target-unverified", str(exc))

    evidence_payload = evidence.to_payload()
    frozen_evidence = freeze_json(evidence_payload)
    evidence_fingerprint = sha256_hex(frozen_evidence)
    verified_time = _parse_utc(evidence.verified_at)
    expires_time = verified_time + timedelta(hours=EVIDENCE_TTL_HOURS)
    evidence_expires_at = _format_utc(expires_time)

    blocked: set[str] = set()
    manual: set[str] = set()
    relation_findings: set[str] = set()
    view_findings: set[str] = set()
    limit_findings: set[str] = set()
    authority_findings: set[str] = set()

    compatible_mappings: set[str] = set()
    unsupported_mappings: set[str] = set()
    stale_mappings: set[str] = set()
    missing_mappings: set[str] = set()
    conflicting_mappings: set[str] = set()

    if not evidence.database_id or not evidence.data_source_id:
        blocked.add("notion-target-unverified")
    if evidence.database_id and evidence.database_id == evidence.data_source_id:
        blocked.add("notion-database-data-source-mismatch")
    if evidence.notion_api_version != SUPPORTED_NOTION_API_VERSION:
        blocked.add("notion-api-version-mismatch")
    if evidence.contract_version != CONTRACT_VERSION:
        blocked.add("notion-contract-version-incompatible")
    if not evidence.schema_fingerprint:
        manual.add("notion-target-unverified")
    if evidence.views and not evidence.view_fingerprint:
        manual.add("notion-view-target-ambiguous")
        view_findings.add("notion-view-target-ambiguous")

    if evaluation_time < verified_time:
        return _invalid_report(
            "notion-target-unverified", "evaluated_at cannot precede verified_at"
        )
    if evaluation_time > expires_time:
        manual.update(
            {"notion-evidence-expired", "notion-schema-stale", "notion-view-stale"}
        )
        view_findings.add("notion-view-stale")

    property_ids = [item.property_id for item in evidence.properties if item.property_id]
    if len(property_ids) != len(set(property_ids)):
        return _invalid_report("notion-property-conflict", "duplicate property identity")
    display_names: dict[str, set[str]] = {}
    for item in evidence.properties:
        display_names.setdefault(item.display_name.casefold(), set()).add(item.property_id)
    if any(len(ids) > 1 for ids in display_names.values()):
        manual.add("notion-property-conflict")

    property_by_id = {item.property_id: item for item in evidence.properties if item.property_id}
    for item in evidence.properties:
        if not item.property_id:
            blocked.add("notion-property-id-missing")
        if item.evidence_state == "stale":
            manual.add("notion-schema-stale")
        elif item.evidence_state in {"unverified", "missing", "inaccessible", "ambiguous"}:
            manual.add("notion-target-unverified")
        elif item.evidence_state == "conflicting":
            blocked.add("notion-property-conflict")
        if item.current_write_mode not in {"read-only", "local-draft"}:
            blocked.add("notion-write-mode-not-authorized")
            authority_findings.add("notion-write-mode-not-authorized")
        if item.readiness_effect == "governed" and item.current_write_mode != "read-only":
            blocked.add("notion-readiness-owner-conflict")
            authority_findings.add("notion-readiness-owner-conflict")
        if item.maximum_value_size > evidence.limits.property_value_limit:
            blocked.add("notion-value-limit-exceeded")
            limit_findings.add("notion-value-limit-exceeded")

    relation_keys: set[tuple[str, str, str]] = set()
    for item in evidence.relations:
        key = (item.property_id, item.source_data_source_id, item.target_data_source_id)
        if key in relation_keys:
            return _invalid_report("notion-property-conflict", "duplicate relation evidence")
        relation_keys.add(key)
        if not item.property_id or item.property_id not in property_by_id:
            blocked.add("notion-property-id-missing")
            relation_findings.add("notion-property-id-missing")
        if item.source_data_source_id != evidence.data_source_id:
            blocked.add("notion-database-data-source-mismatch")
            relation_findings.add("notion-database-data-source-mismatch")
        if not item.target_shared_with_connection or item.access_state in {
            "denied",
            "missing-or-hidden",
            "trashed",
        }:
            blocked.add("notion-relation-target-unshared")
            relation_findings.add("notion-relation-target-unshared")
        elif item.access_state in {"unverified", "transient-error"}:
            manual.add("notion-relation-ambiguous")
            relation_findings.add("notion-relation-ambiguous")
        if item.ambiguity_state != "unambiguous":
            manual.add("notion-relation-ambiguous")
            relation_findings.add("notion-relation-ambiguous")

    view_ids = [item.view_id for item in evidence.views if item.view_id]
    if len(view_ids) != len(set(view_ids)):
        return _invalid_report("notion-view-target-ambiguous", "duplicate view identity")
    for item in evidence.views:
        if not item.view_id or item.parent_data_source_id != evidence.data_source_id:
            manual.add("notion-view-target-ambiguous")
            view_findings.add("notion-view-target-ambiguous")
        if item.capability_state != "supported" or item.filter_sort_compatibility != "compatible":
            manual.add("notion-view-capability-unsupported")
            view_findings.add("notion-view-capability-unsupported")
        if item.evidence_state == "stale":
            manual.add("notion-view-stale")
            view_findings.add("notion-view-stale")
        elif item.evidence_state != "verified":
            manual.add("notion-view-target-ambiguous")
            view_findings.add("notion-view-target-ambiguous")

    if not evidence.limits.pagination_complete:
        blocked.add("notion-pagination-incomplete")
        limit_findings.add("notion-pagination-incomplete")
    if not evidence.limits.rate_limit_policy_known or not evidence.limits.retry_after_supported:
        manual.add("notion-rate-limit-policy-unknown")
        limit_findings.add("notion-rate-limit-policy-unknown")
    if (
        len(evidence.properties) > evidence.limits.collection_limit
        or len(evidence.relations) > evidence.limits.collection_limit
        or len(evidence.views) > evidence.limits.collection_limit
        or len(evidence.contract_mappings) > evidence.limits.collection_limit
        or evidence.limits.payload_limit < len(canonical_json_bytes(frozen_evidence))
    ):
        blocked.add("notion-value-limit-exceeded")
        limit_findings.add("notion-value-limit-exceeded")

    seen_mapping_ids: set[str] = set()
    mapped_contracts: set[str] = set()
    for mapping in evidence.contract_mappings:
        identity = mapping.identity
        if identity in seen_mapping_ids:
            return _invalid_report("notion-property-conflict", "duplicate contract mapping")
        seen_mapping_ids.add(identity)
        mapped_contracts.add(mapping.contract_name)

        target = property_by_id.get(mapping.target_property_id)
        if not mapping.target_property_id or target is None:
            missing_mappings.add(identity)
            blocked.add("notion-property-id-missing")
            continue
        if mapping.contract_version != CONTRACT_VERSION:
            unsupported_mappings.add(identity)
            blocked.add("notion-contract-version-incompatible")
            continue
        if not mapping.type_compatible:
            unsupported_mappings.add(identity)
            blocked.add("notion-property-type-mismatch")
            continue
        if not mapping.owner_compatible:
            conflicting_mappings.add(identity)
            blocked.add("notion-readiness-owner-conflict")
            authority_findings.add("notion-readiness-owner-conflict")
            continue
        if not mapping.bounded:
            unsupported_mappings.add(identity)
            blocked.add("notion-projection-unbounded")
            continue
        if mapping.governed_field and mapping.projection_mode not in {
            "reference-only",
            "display-only",
        }:
            conflicting_mappings.add(identity)
            blocked.add("notion-governed-field-write-proposed")
            authority_findings.add("notion-governed-field-write-proposed")
            continue
        if target.current_write_mode not in {"read-only", "local-draft"}:
            conflicting_mappings.add(identity)
            blocked.add("notion-write-mode-not-authorized")
            authority_findings.add("notion-write-mode-not-authorized")
            continue
        if target.evidence_state == "stale":
            stale_mappings.add(identity)
            manual.add("notion-schema-stale")
            continue
        if target.evidence_state != "verified":
            missing_mappings.add(identity)
            manual.add("notion-target-unverified")
            continue
        compatible_mappings.add(identity)

    missing_contracts = SUPPORTED_CONTRACT_NAMES - mapped_contracts
    for contract_name in sorted(missing_contracts):
        missing_mappings.add(f"{contract_name}:missing")
    if missing_contracts:
        blocked.add("notion-target-unverified")

    all_findings = blocked | manual
    manual_steps = tuple(
        sorted({_MANUAL_STEPS[code] for code in manual if code in _MANUAL_STEPS})
    )

    if blocked:
        status = PreflightStatus.BLOCKED
    elif manual:
        status = PreflightStatus.MANUAL_REVIEW_REQUIRED
    else:
        status = PreflightStatus.READY_FOR_LOCAL_DRAFT_IMPLEMENTATION

    return NotionCurriculumPreflightReport(
        status=status,
        evidence_id=evidence.evidence_id,
        evidence_fingerprint=evidence_fingerprint,
        exact_target_tuple=(
            evidence.workspace_context_id,
            evidence.database_id or "unavailable",
            evidence.data_source_id or "unavailable",
        ),
        compatible_mappings=tuple(compatible_mappings),
        unsupported_mappings=tuple(unsupported_mappings),
        stale_mappings=tuple(stale_mappings),
        missing_mappings=tuple(missing_mappings),
        conflicting_mappings=tuple(conflicting_mappings),
        relation_findings=tuple(relation_findings),
        view_findings=tuple(view_findings),
        limit_findings=tuple(limit_findings),
        authority_findings=tuple(authority_findings),
        reason_codes=tuple(all_findings),
        blockers=tuple(blocked),
        required_manual_verifications=manual_steps,
        proposed_implementation_scope=PROPOSED_IMPLEMENTATION_SCOPE,
        evidence_expires_at=evidence_expires_at,
        rollback_note=_ROLLBACK_NOTE,
    )


def serialize_preflight_report(report: NotionCurriculumPreflightReport) -> str:
    """Return canonical JSON for exact byte-for-byte comparison."""

    if type(report) is not NotionCurriculumPreflightReport:
        raise TypeError("report must be NotionCurriculumPreflightReport")
    return canonical_json_bytes(report.to_payload()).decode("utf-8")
