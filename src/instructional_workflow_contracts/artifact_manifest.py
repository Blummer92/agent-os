"""Pure ArtifactManifest validation built on the CW5A shared core."""

from __future__ import annotations

from typing import Any

from .common import (
    FINGERPRINT_ALGORITHM,
    MAX_DEPENDENCY_KEYS,
    MAX_INPUT_BYTES,
    MAX_REFERENCES,
    MAX_RESULT_BYTES,
    ContractValidationError,
    ValidatedRecord,
    ValidationResult,
    ValidationStatus,
    canonical_reason_codes,
    canonical_size,
    canonical_strings,
    freeze_json,
    sanitize_detail,
    sha256_hex,
    validate_and_normalize_json,
    validate_dependency_key,
    validate_mapping,
    validate_reason_code,
    validate_revision,
    validate_sha256,
    validate_stable_id,
    validate_text,
    validate_timestamp,
    validate_version,
)

CONTRACT_ID = "curriculum-artifact-manifest-v1"
MATERIAL_CONTRACT_ID = "curriculum-material-requirement-v1"
MAX_REVISIONS = 32
MAX_ASSETS = 64
MAX_QUALITY_ROWS = 64
MAX_FINDINGS = 32
MAX_TRANSFORMATIONS = 32
MAX_CONTEXT_FLAGS = 32
MAX_RISK_FINDINGS = MAX_FINDINGS
MAX_TRANSFORMATION_FLAGS = MAX_TRANSFORMATIONS
MAX_CANDIDATES = 32
MAX_DISCOVERY_EVIDENCE = 32

PROVIDERS = frozenset({"google-drive", "local-reference", "other-manual-review"})
ACCESS_STATES = frozenset(
    {"verified", "denied", "missing-or-hidden", "unverified", "transient-error", "trashed"}
)
OPERATIONS = frozenset(
    {
        "discover-existing",
        "reuse-existing",
        "revise-existing",
        "copy-approved-template",
        "create-new-approved",
        "supersede-with-new-version",
        "manual-review",
    }
)
DUPLICATE_RELATIONSHIPS = frozenset({"unique", "exact-duplicate", "near-duplicate", "unknown"})
DUPLICATE_DISPOSITIONS = frozenset({"canonical", "alternate", "archive-candidate", "manual-review"})
RIGHTS_STATES = frozenset(
    {
        "cleared-internal",
        "licensed",
        "public-domain",
        "permission-documented",
        "fair-use-review-required",
        "unclear-provenance",
        "restricted-or-do-not-distribute",
        "manual-review",
    }
)
RIGHTS_BASES = frozenset(
    {
        "internal-evidence",
        "license-evidence",
        "public-domain-evidence",
        "permission-evidence",
        "fair-use-review",
        "unclear",
        "restricted",
        "crop-or-hide-signal",
        "manual-review",
    }
)
CLEARED_RIGHTS = frozenset({"cleared-internal", "licensed", "public-domain", "permission-documented"})
WARNING_SIGNALS = frozenset(
    {
        "watermark",
        "signature",
        "brand",
        "copyrighted-character",
        "commercial-product",
        "stock-image-indicator",
        "search-result-thumbnail",
    }
)
PRIVACY_OBSERVATIONS = frozenset(
    {
        "identifiable-people",
        "names",
        "profiles",
        "account-details",
        "notifications",
        "dates",
        "locations",
        "thumbnails",
        "messages",
        "comments",
        "reactions",
        "social-identities",
    }
)
PRIVACY_MITIGATIONS = frozenset(
    {"none", "context-preserving-crop", "blur-or-redact", "anonymize", "replace", "clearance-required", "manual-review"}
)
CONTENT_FINDINGS = frozenset(
    {
        "malformed-text",
        "inaccurate-content",
        "repeated-labels",
        "truncated-instructions",
        "misleading-example",
        "misleading-icon",
        "answer-revealing-content",
    }
)
TRANSFORMATIONS = frozenset(
    {
        "crop",
        "zoom",
        "enlarge",
        "segment",
        "rotate",
        "perspective-correct",
        "cleanup",
        "background-cleanup",
        "edge-cleanup",
        "contrast-adjustment",
        "glare-adjustment",
        "blur-or-redact",
        "rebuild",
        "replace",
        "no-safe-transformation",
        "manual-review",
    }
)
CONTEXT_FLAGS = frozenset(
    {
        "labels",
        "arrows",
        "sequences",
        "comparison-groups",
        "response-areas",
        "interface-identity",
        "tool-identity",
        "environmental-setting",
        "mood-evidence",
        "meaningful-order",
    }
)
ROLLBACK_KINDS = frozenset(
    {"retained-prior-file", "exported-backup", "drive-revision-only", "manifest-only-predecessor", "no-verified-artifact"}
)
QUALITY_STATES = frozenset({"not-assessed", "pass", "fail", "manual-review"})
TEACHER_STATES = frozenset({"not-requested", "pending", "approved", "rejected"})
CLASSROOM_STATES = frozenset({"not-assessed", "blocked", "manual-review-required", "ready"})
PRODUCTION_STATES = frozenset({"not-authorized", "requested", "authorized-evidence-only"})
PUBLICATION_STATES = frozenset({"not-published", "published-observed", "unknown"})
SHARING_STATES = frozenset({"private-observed", "restricted-observed", "shared-observed", "unknown"})
CUSTOM_PROPERTY_KEYS = frozenset({"manifest_id", "requirement_id", "contract_version", "idempotency_key"})
TOP_LEVEL_FIELDS = frozenset(
    {
        "identity",
        "requirement_reference",
        "artifact",
        "external_identity",
        "source_snapshot",
        "operation",
        "duplicates",
        "lineage",
        "statuses",
        "quality_rows",
        "assets",
        "references",
        "custom_properties",
        "authority",
    }
)


def artifact_manifest_source_fingerprint(value: object) -> str:
    normalized = validate_and_normalize_json(value, max_bytes=MAX_INPUT_BYTES)
    if type(normalized) is not dict or type(normalized.get("identity")) is not dict:
        raise ContractValidationError("handoff-wrong-type", "identity must be a built-in mapping")
    payload = dict(normalized)
    identity = dict(normalized["identity"])
    for key in ("source_fingerprint", "created_at", "modified_at", "verified_at"):
        identity.pop(key, None)
    payload["identity"] = identity
    external = payload.get("external_identity")
    if type(external) is dict:
        external = dict(external)
        for key in ("web_view_link", "modified_time", "last_verified_at"):
            external.pop(key, None)
        payload["external_identity"] = external
    return sha256_hex(payload)


def artifact_manifest_idempotency_key(value: object) -> str:
    normalized = validate_and_normalize_json(value, max_bytes=MAX_INPUT_BYTES)
    required = ("requirement_reference", "operation", "external_identity", "lineage")
    if type(normalized) is not dict or any(type(normalized.get(key)) is not dict for key in required):
        raise ContractValidationError("handoff-wrong-type", "idempotency groups must be built-in mappings")
    req = normalized["requirement_reference"]
    op = normalized["operation"]
    external = normalized["external_identity"]
    lineage = normalized["lineage"]
    return sha256_hex(
        {
            "requirement": {
                "requirement_id": req.get("requirement_id"),
                "contract_version": req.get("contract_version"),
                "record_revision": req.get("record_revision"),
                "fingerprint": req.get("fingerprint"),
            },
            "operation": op.get("kind"),
            "target": {
                "provider": external.get("provider"),
                "file_id": external.get("file_id"),
                "drive_id": external.get("drive_id"),
                "parent_folder_ref": external.get("parent_folder_ref"),
                "exact_reference": external.get("exact_reference"),
                "current_file_ref": op.get("current_file_ref"),
                "template_ref": op.get("template_ref"),
            },
            "lineage": {
                "predecessor_ref": lineage.get("predecessor_ref"),
                "successor_ref": lineage.get("successor_ref"),
            },
        }
    )


def validate_artifact_manifest(value: object) -> ValidationResult:
    try:
        data = validate_and_normalize_json(value, max_bytes=MAX_INPUT_BYTES)
        if type(data) is not dict:
            raise ContractValidationError("handoff-wrong-type", "manifest must be a built-in mapping")
        _fields(data, TOP_LEVEL_FIELDS, "manifest")
        groups = {
            name: validate_mapping(data[name], name)
            for name in TOP_LEVEL_FIELDS - {"quality_rows", "assets", "references"}
        }
        quality_rows = _list(data["quality_rows"], "quality_rows")
        assets = _list(data["assets"], "assets")
        references = _list(data["references"], "references")

        _identity(groups["identity"], data)
        _requirement(groups["requirement_reference"])
        _artifact(groups["artifact"])
        _external(groups["external_identity"])
        _source(groups["source_snapshot"])
        _operation(groups["operation"], groups["external_identity"])
        manual = _duplicates(groups["duplicates"], groups["operation"])
        manual |= _lineage(groups["lineage"], groups["operation"])
        _idempotency(data, groups["operation"])
        _statuses(groups["statuses"], groups["external_identity"])
        _quality_rows(quality_rows, groups["statuses"])
        manual |= _assets(assets, groups["statuses"])
        _references(references)
        _custom_properties(groups["custom_properties"], groups)
        _authority(groups["authority"])

        data["source_snapshot"]["dependency_keys"] = list(
            canonical_strings(
                groups["source_snapshot"]["dependency_keys"],
                name="dependency keys",
                maximum=MAX_DEPENDENCY_KEYS,
                validator=validate_dependency_key,
            )
        )
        data["operation"]["discovery_evidence"] = list(
            _strings(groups["operation"]["discovery_evidence"], "discovery evidence", MAX_DISCOVERY_EVIDENCE)
        )
        data["duplicates"]["candidates"] = sorted(
            groups["duplicates"]["candidates"], key=lambda item: item["candidate_id"]
        )
        data["quality_rows"] = sorted(quality_rows, key=lambda item: item["row_id"])
        data["assets"] = sorted(assets, key=lambda item: item["asset_id"])
        data["references"] = sorted(references, key=lambda item: item["reference_id"])
        if canonical_size(data) > MAX_RESULT_BYTES:
            raise ContractValidationError("handoff-oversized", "normalized manifest exceeds the 16 KiB result bound")
        identity = groups["identity"]
        record = ValidatedRecord(
            contract_version=identity["contract_version"],
            record_id=identity["manifest_id"],
            record_revision=identity["record_revision"],
            fingerprint_algorithm=FINGERPRINT_ALGORITHM,
            fingerprint=sha256_hex(data),
            payload=freeze_json(data),
        )
        access = groups["external_identity"]["access_state"]
        if access != "verified":
            manual.add("artifact-access-manual-review")
        if groups["external_identity"]["provider"] == "other-manual-review":
            manual.add("artifact-provider-manual-review")
        if groups["operation"]["kind"] == "manual-review":
            manual.add("artifact-operation-manual-review")
        if manual:
            return ValidationResult(
                status=ValidationStatus.MANUAL_REVIEW_REQUIRED,
                record=record,
                reason_codes=tuple(manual),
                details=("supplied evidence requires bounded human review",),
            )
        return ValidationResult(status=ValidationStatus.VALID, record=record)
    except ContractValidationError as exc:
        return _invalid(exc.reason_code, exc.detail)
    except (TypeError, ValueError) as exc:
        return _invalid("artifact-invalid", sanitize_detail(str(exc)))


def _invalid(reason: str, detail: str) -> ValidationResult:
    validate_reason_code(reason)
    return ValidationResult(
        status=ValidationStatus.INVALID,
        record=None,
        reason_codes=(reason,),
        details=(sanitize_detail(detail),),
    )


def _list(value: object, name: str) -> list[Any]:
    if type(value) is not list:
        raise ContractValidationError("handoff-wrong-type", f"{name} must be a built-in list")
    return value


def _fields(value: dict[str, Any], expected: frozenset[str], name: str) -> None:
    actual = set(value)
    if expected - actual:
        raise ContractValidationError("artifact-missing-required-field", f"{name} is missing required fields")
    if actual - expected:
        raise ContractValidationError("artifact-unknown-field", f"{name} contains unknown fields")


def _optional_text(value: object, name: str) -> str | None:
    return None if value is None else validate_text(value, name)


def _bool(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise ContractValidationError("handoff-wrong-type", f"{name} must be a built-in boolean")
    return value


def _enum(value: object, name: str, allowed: frozenset[str], reason: str) -> str:
    text = validate_text(value, name, max_length=64)
    if text not in allowed:
        raise ContractValidationError(reason, f"{name} is unsupported")
    return text


def _strings(value: object, name: str, maximum: int) -> tuple[str, ...]:
    return canonical_strings(
        value,
        name=name,
        maximum=maximum,
        validator=lambda item: validate_text(item, name),
    )


def _identity(value: dict[str, Any], full: dict[str, Any]) -> None:
    _fields(
        value,
        frozenset(
            {"contract_version", "manifest_id", "record_revision", "created_at", "modified_at", "verified_at", "source_fingerprint"}
        ),
        "identity",
    )
    if validate_version(value["contract_version"]) != CONTRACT_ID:
        raise ContractValidationError("artifact-contract-version-unsupported", "unsupported ArtifactManifest version")
    validate_stable_id(value["manifest_id"], "manifest_id")
    validate_revision(value["record_revision"])
    for key in ("created_at", "modified_at", "verified_at"):
        validate_timestamp(value[key], key)
    validate_sha256(value["source_fingerprint"], "source_fingerprint")
    if value["source_fingerprint"] != artifact_manifest_source_fingerprint(full):
        raise ContractValidationError("artifact-incompatible-fingerprint", "source fingerprint does not match supplied evidence")


def _requirement(value: dict[str, Any]) -> None:
    _fields(value, frozenset({"requirement_id", "contract_version", "record_revision", "fingerprint"}), "requirement_reference")
    validate_stable_id(value["requirement_id"], "requirement_id")
    if validate_version(value["contract_version"]) != MATERIAL_CONTRACT_ID:
        raise ContractValidationError("artifact-incompatible-requirement", "MaterialRequirement version is incompatible")
    validate_revision(value["record_revision"])
    validate_sha256(value["fingerprint"], "MaterialRequirement fingerprint")


def _artifact(value: dict[str, Any]) -> None:
    _fields(value, frozenset({"artifact_type", "mime_type"}), "artifact")
    validate_stable_id(value["artifact_type"], "artifact_type")
    validate_text(value["mime_type"], "mime_type", max_length=128)


def _external(value: dict[str, Any]) -> None:
    expected = frozenset(
        {
            "provider", "file_id", "drive_id", "resource_key_required", "resource_key",
            "parent_folder_ref", "exact_reference", "web_view_link", "external_revision",
            "modified_time", "last_verified_at", "verification_scope", "access_state", "trashed",
        }
    )
    _fields(value, expected, "external_identity")
    provider = _enum(value["provider"], "provider", PROVIDERS, "artifact-provider-unsupported")
    file_id = _optional_text(value["file_id"], "file_id")
    drive_id = _optional_text(value["drive_id"], "drive_id")
    resource_required = _bool(value["resource_key_required"], "resource_key_required")
    resource_key = _optional_text(value["resource_key"], "resource_key")
    _optional_text(value["parent_folder_ref"], "parent_folder_ref")
    validate_text(value["exact_reference"], "exact_reference")
    _optional_text(value["web_view_link"], "web_view_link")
    _optional_text(value["external_revision"], "external_revision")
    validate_timestamp(value["modified_time"], "modified_time")
    validate_timestamp(value["last_verified_at"], "last_verified_at")
    scope = validate_stable_id(value["verification_scope"], "verification_scope")
    access = _enum(value["access_state"], "access_state", ACCESS_STATES, "artifact-access-state-invalid")
    trashed = _bool(value["trashed"], "trashed")
    if provider == "google-drive" and file_id is None:
        raise ContractValidationError("artifact-url-only-identity", "google-drive identity requires an explicit file_id")
    if scope == "shared-drive" and drive_id is None:
        raise ContractValidationError("artifact-missing-drive-id", "shared-drive identity requires drive_id")
    if resource_required and resource_key is None:
        raise ContractValidationError("artifact-missing-resource-key", "required resource-key evidence is missing")
    if (access == "trashed") != trashed:
        raise ContractValidationError("artifact-contradictory-access-state", "trashed evidence is contradictory")


def _source(value: dict[str, Any]) -> None:
    expected = frozenset(
        {"handoff_id", "source_fingerprint", "dependency_fingerprint", "dependency_keys", "dependency_values", "source_changed"}
    )
    _fields(value, expected, "source_snapshot")
    validate_stable_id(value["handoff_id"], "handoff_id")
    validate_sha256(value["source_fingerprint"], "source snapshot fingerprint")
    validate_sha256(value["dependency_fingerprint"], "dependency fingerprint")
    keys = canonical_strings(
        value["dependency_keys"], name="dependency keys", maximum=MAX_DEPENDENCY_KEYS, validator=validate_dependency_key
    )
    values = validate_mapping(value["dependency_values"], "dependency_values")
    if set(keys) != set(values):
        raise ContractValidationError("dependency-invalid", "dependency keys and values must match exactly")
    expected_fingerprint = sha256_hex({"dependency_keys": list(keys), "dependency_values": values})
    if value["dependency_fingerprint"] != expected_fingerprint:
        raise ContractValidationError("dependency-invalid", "dependency fingerprint does not match supplied evidence")
    _bool(value["source_changed"], "source_changed")


def _operation(value: dict[str, Any], external: dict[str, Any]) -> None:
    expected = frozenset(
        {
            "kind", "idempotency_key", "approved_request_id", "approved_scope", "current_file_ref",
            "template_ref", "template_permission_state", "discovery_evidence",
        }
    )
    _fields(value, expected, "operation")
    kind = _enum(value["kind"], "operation kind", OPERATIONS, "artifact-operation-invalid")
    validate_sha256(value["idempotency_key"], "idempotency_key")
    request = _optional_text(value["approved_request_id"], "approved_request_id")
    scope = _optional_text(value["approved_scope"], "approved_scope")
    current = _optional_text(value["current_file_ref"], "current_file_ref")
    template = _optional_text(value["template_ref"], "template_ref")
    permission = _optional_text(value["template_permission_state"], "template_permission_state")
    discovery = _strings(value["discovery_evidence"], "discovery evidence", MAX_DISCOVERY_EVIDENCE)
    if kind == "discover-existing" and not discovery:
        raise ContractValidationError("artifact-missing-discovery-evidence", "discover-existing requires supplied evidence")
    if kind == "revise-existing" and (current is None or scope is None):
        raise ContractValidationError("artifact-invalid-lifecycle", "revise-existing requires exact file identity and scope")
    if kind == "copy-approved-template" and (template is None or permission not in CLEARED_RIGHTS):
        raise ContractValidationError("template-unverified-permission", "approved template evidence is incomplete")
    if kind == "create-new-approved" and request is None:
        raise ContractValidationError("artifact-invalid-lifecycle", "create-new-approved requires an approved request")
    if kind == "supersede-with-new-version" and current is None:
        raise ContractValidationError("artifact-invalid-lifecycle", "supersession requires current file identity")
    if kind in {"reuse-existing", "revise-existing", "supersede-with-new-version"} and external["file_id"] is None:
        raise ContractValidationError("artifact-missing-file-identity", "operation requires exact external file identity")


def _idempotency(full: dict[str, Any], operation: dict[str, Any]) -> None:
    if operation["idempotency_key"] != artifact_manifest_idempotency_key(full):
        raise ContractValidationError("artifact-idempotency-conflict", "idempotency key does not match supplied operation evidence")


def _duplicates(value: dict[str, Any], operation: dict[str, Any]) -> set[str]:
    _fields(value, frozenset({"candidates", "selected_candidate_ref"}), "duplicates")
    candidates = _list(value["candidates"], "duplicate candidates")
    if len(candidates) > MAX_CANDIDATES:
        raise ContractValidationError("handoff-oversized", "duplicate candidates exceed their collection bound")
    selected = _optional_text(value["selected_candidate_ref"], "selected_candidate_ref")
    seen: set[str] = set()
    compatible: list[str] = []
    manual: set[str] = set()
    fields = frozenset(
        {"candidate_id", "relationship", "disposition", "canonical_asset_ref", "comparison_evidence", "confidence", "compatible", "conflicting"}
    )
    for raw in candidates:
        candidate = validate_mapping(raw, "duplicate candidate")
        _fields(candidate, fields, "duplicate candidate")
        candidate_id = validate_stable_id(candidate["candidate_id"], "candidate_id")
        if candidate_id in seen:
            raise ContractValidationError("artifact-duplicate-candidate", "duplicate candidate IDs are not allowed")
        seen.add(candidate_id)
        relationship = _enum(candidate["relationship"], "duplicate relationship", DUPLICATE_RELATIONSHIPS, "asset-duplicate-relationship-invalid")
        disposition = _enum(candidate["disposition"], "duplicate disposition", DUPLICATE_DISPOSITIONS, "asset-duplicate-disposition-invalid")
        canonical_ref = _optional_text(candidate["canonical_asset_ref"], "canonical_asset_ref")
        validate_text(candidate["comparison_evidence"], "comparison_evidence")
        confidence = candidate["confidence"]
        if type(confidence) not in {int, float} or type(confidence) is bool or not 0 <= confidence <= 1:
            raise ContractValidationError("asset-confidence-invalid", "confidence must be between zero and one")
        is_compatible = _bool(candidate["compatible"], "compatible")
        conflicting = _bool(candidate["conflicting"], "conflicting")
        if disposition in {"alternate", "archive-candidate"} and canonical_ref is None:
            raise ContractValidationError("asset-missing-canonical-reference", "alternate and archive candidates require canonical references")
        if relationship == "unique" and disposition != "canonical":
            raise ContractValidationError("asset-contradictory-disposition", "unique assets must be canonical")
        if is_compatible and not conflicting:
            compatible.append(candidate_id)
        if relationship == "unknown" or disposition == "manual-review" or conflicting:
            manual.add("asset-duplicate-manual-review")
    if selected is not None and selected not in seen:
        raise ContractValidationError("artifact-selected-candidate-missing", "selected candidate is not supplied")
    if len(candidates) > 1:
        manual.add("artifact-ambiguous-reuse-candidate")
    if operation["kind"] == "reuse-existing" and (len(compatible) != 1 or selected != compatible[0]):
        manual.add("artifact-ambiguous-reuse-candidate")
    return manual


def _lineage(value: dict[str, Any], operation: dict[str, Any]) -> set[str]:
    _fields(value, frozenset({"revisions", "predecessor_ref", "successor_ref", "supersession_reason"}), "lineage")
    revisions = _list(value["revisions"], "revisions")
    if len(revisions) > MAX_REVISIONS:
        raise ContractValidationError("handoff-oversized", "revisions exceed their collection bound")
    predecessor = _optional_text(value["predecessor_ref"], "predecessor_ref")
    successor = _optional_text(value["successor_ref"], "successor_ref")
    reason = _optional_text(value["supersession_reason"], "supersession_reason")
    seen_ids: set[str] = set()
    seen_results: set[str] = set()
    previous_timestamp: str | None = None
    manual: set[str] = set()
    fields = frozenset(
        {
            "revision_id", "predecessor_ref", "operation", "trigger", "changed_sections", "preserved_sections",
            "resulting_file_ref", "reviewer_owner", "timestamp", "rollback_kind", "rollback_ref", "rollback_verified",
        }
    )
    for raw in revisions:
        revision = validate_mapping(raw, "revision")
        _fields(revision, fields, "revision")
        revision_id = validate_stable_id(revision["revision_id"], "revision_id")
        if revision_id in seen_ids:
            raise ContractValidationError("artifact-duplicate-revision", "revision IDs must be unique")
        seen_ids.add(revision_id)
        revision_predecessor = _optional_text(revision["predecessor_ref"], "revision predecessor_ref")
        _enum(revision["operation"], "revision operation", OPERATIONS, "artifact-operation-invalid")
        validate_text(revision["trigger"], "revision trigger")
        _strings(revision["changed_sections"], "changed sections", 32)
        _strings(revision["preserved_sections"], "preserved sections", 32)
        result_ref = validate_text(revision["resulting_file_ref"], "resulting_file_ref")
        if result_ref in seen_results or revision_predecessor == result_ref:
            raise ContractValidationError("artifact-contradictory-lineage", "revision lineage contains duplicate or self-referential results")
        seen_results.add(result_ref)
        validate_stable_id(revision["reviewer_owner"], "reviewer_owner")
        timestamp = validate_timestamp(revision["timestamp"], "revision timestamp")
        if previous_timestamp is not None and timestamp < previous_timestamp:
            raise ContractValidationError("artifact-contradictory-lineage", "revision timestamps must be append-monotonic")
        previous_timestamp = timestamp
        rollback_kind = _enum(revision["rollback_kind"], "rollback_kind", ROLLBACK_KINDS, "artifact-rollback-kind-invalid")
        rollback_ref = _optional_text(revision["rollback_ref"], "rollback_ref")
        rollback_verified = _bool(revision["rollback_verified"], "rollback_verified")
        if rollback_kind in {"retained-prior-file", "exported-backup"}:
            if rollback_ref is None or not rollback_verified:
                raise ContractValidationError("artifact-rollback-contradiction", "verified rollback evidence is incomplete")
        elif rollback_verified:
            raise ContractValidationError("artifact-rollback-contradiction", "unverified rollback kind cannot be marked verified")
        else:
            manual.add("artifact-rollback-unverified")
    kind = operation["kind"]
    if kind == "revise-existing" and not revisions:
        raise ContractValidationError("artifact-invalid-lifecycle", "revise-existing requires revision lineage")
    if kind == "supersede-with-new-version" and (predecessor is None or successor is None or reason is None or not revisions):
        raise ContractValidationError("artifact-invalid-lifecycle", "supersession requires complete preserved lineage")
    if predecessor is not None and successor == predecessor:
        raise ContractValidationError("artifact-contradictory-lineage", "predecessor and successor cannot be identical")
    return manual


def _statuses(value: dict[str, Any], external: dict[str, Any]) -> None:
    expected = frozenset(
        {"quality_state", "teacher_approval", "classroom_readiness", "production_state", "publication_state", "sharing_state"}
    )
    _fields(value, expected, "statuses")
    quality = _enum(value["quality_state"], "quality_state", QUALITY_STATES, "quality-state-invalid")
    _enum(value["teacher_approval"], "teacher_approval", TEACHER_STATES, "readiness-teacher-approval-invalid")
    classroom = _enum(value["classroom_readiness"], "classroom_readiness", CLASSROOM_STATES, "readiness-classroom-invalid")
    _enum(value["production_state"], "production_state", PRODUCTION_STATES, "authority-production-state-invalid")
    _enum(value["publication_state"], "publication_state", PUBLICATION_STATES, "authority-publication-state-invalid")
    _enum(value["sharing_state"], "sharing_state", SHARING_STATES, "authority-sharing-state-invalid")
    if classroom == "ready" and external["access_state"] != "verified":
        raise ContractValidationError("readiness-incompatible-access", "inaccessible evidence cannot be classroom-ready")
    if classroom == "ready" and quality != "pass":
        raise ContractValidationError("readiness-incompatible-quality", "classroom-ready requires passing quality evidence")


def _quality_rows(values: list[Any], statuses: dict[str, Any]) -> None:
    if len(values) > MAX_QUALITY_ROWS:
        raise ContractValidationError("handoff-oversized", "quality rows exceed their collection bound")
    seen: set[str] = set()
    unresolved = False
    fields = frozenset({"row_id", "state", "reason_codes"})
    for raw in values:
        row = validate_mapping(raw, "quality row")
        _fields(row, fields, "quality row")
        row_id = validate_stable_id(row["row_id"], "quality row_id")
        if row_id in seen:
            raise ContractValidationError("quality-duplicate-row", "quality row IDs must be unique")
        seen.add(row_id)
        state = _enum(row["state"], "quality row state", QUALITY_STATES, "quality-state-invalid")
        reasons = canonical_reason_codes(row["reason_codes"], 32)
        if state in {"fail", "manual-review"}:
            unresolved = True
            if not reasons:
                raise ContractValidationError("quality-missing-reason", "failed quality rows require reason codes")
    if unresolved and statuses["quality_state"] == "pass":
        raise ContractValidationError("quality-status-contradiction", "quality rows conflict with manifest quality state")
    if unresolved and statuses["classroom_readiness"] == "ready":
        raise ContractValidationError("readiness-incompatible-quality", "unresolved quality rows block classroom readiness")


def _assets(values: list[Any], statuses: dict[str, Any]) -> set[str]:
    if len(values) > MAX_ASSETS:
        raise ContractValidationError("handoff-oversized", "assets exceed their collection bound")
    seen: set[str] = set()
    manual: set[str] = set()
    fields = frozenset(
        {
            "asset_id", "stable_ref", "content_fingerprint", "perceptual_match_evidence", "duplicate_group_id",
            "duplicate_relationship", "disposition", "canonical_asset_ref", "comparison_evidence", "confidence",
            "rights_classification", "rights_basis", "warning_signals", "privacy_observations", "privacy_mitigation",
            "privacy_resolved", "residual_privacy_risk", "content_findings", "repair_source_status", "direct_use_status",
            "correction_requirement", "replacement_required", "transformations", "required_context_flags",
            "preserved_context_flags", "context_preservation_complete",
        }
    )
    for raw in values:
        asset = validate_mapping(raw, "asset")
        _fields(asset, fields, "asset")
        asset_id = validate_stable_id(asset["asset_id"], "asset_id")
        if asset_id in seen:
            raise ContractValidationError("asset-duplicate-id", "asset IDs must be unique")
        seen.add(asset_id)
        validate_stable_id(asset["stable_ref"], "asset stable_ref")
        if asset["content_fingerprint"] is not None:
            validate_sha256(asset["content_fingerprint"], "asset content fingerprint")
        _optional_text(asset["perceptual_match_evidence"], "perceptual_match_evidence")
        _optional_text(asset["duplicate_group_id"], "duplicate_group_id")
        relationship = _enum(asset["duplicate_relationship"], "asset duplicate relationship", DUPLICATE_RELATIONSHIPS, "asset-duplicate-relationship-invalid")
        disposition = _enum(asset["disposition"], "asset disposition", DUPLICATE_DISPOSITIONS, "asset-duplicate-disposition-invalid")
        canonical_ref = _optional_text(asset["canonical_asset_ref"], "canonical_asset_ref")
        validate_text(asset["comparison_evidence"], "comparison_evidence")
        confidence = asset["confidence"]
        if type(confidence) not in {int, float} or type(confidence) is bool or not 0 <= confidence <= 1:
            raise ContractValidationError("asset-confidence-invalid", "asset confidence must be between zero and one")
        if disposition in {"alternate", "archive-candidate"} and canonical_ref is None:
            raise ContractValidationError("asset-missing-canonical-reference", "asset disposition requires a canonical reference")
        if relationship == "unique" and disposition != "canonical":
            raise ContractValidationError("asset-contradictory-disposition", "unique asset must be canonical")
        rights = _enum(asset["rights_classification"], "rights_classification", RIGHTS_STATES, "asset-rights-classification-invalid")
        rights_basis = _enum(asset["rights_basis"], "rights_basis", RIGHTS_BASES, "asset-rights-basis-invalid")
        warning_signals = set(
            canonical_strings(asset["warning_signals"], name="warning signals", maximum=MAX_FINDINGS, validator=_warning_signal)
        )
        if rights in CLEARED_RIGHTS and rights_basis == "crop-or-hide-signal":
            raise ContractValidationError("asset-rights-not-cleared-by-crop", "cropping cannot establish cleared rights")
        if rights not in CLEARED_RIGHTS or (warning_signals and rights_basis in {"unclear", "fair-use-review", "manual-review"}):
            manual.add("asset-rights-manual-review")
        observations = set(
            canonical_strings(asset["privacy_observations"], name="privacy observations", maximum=MAX_FINDINGS, validator=_privacy_observation)
        )
        mitigation = _enum(asset["privacy_mitigation"], "privacy_mitigation", PRIVACY_MITIGATIONS, "asset-privacy-mitigation-invalid")
        resolved = _bool(asset["privacy_resolved"], "privacy_resolved")
        residual = _bool(asset["residual_privacy_risk"], "residual_privacy_risk")
        if resolved and residual:
            raise ContractValidationError("asset-privacy-contradiction", "privacy cannot be resolved with residual risk")
        if observations and mitigation == "none" and resolved:
            raise ContractValidationError("asset-privacy-contradiction", "observed privacy evidence requires mitigation")
        if observations and (not resolved or residual or mitigation in {"clearance-required", "manual-review"}):
            manual.add("asset-unresolved-privacy-risk")
        findings = set(
            canonical_strings(asset["content_findings"], name="content findings", maximum=MAX_FINDINGS, validator=_content_finding)
        )
        repair = _enum(asset["repair_source_status"], "repair_source_status", frozenset({"not-needed", "required", "completed", "manual-review"}), "quality-repair-status-invalid")
        direct_use = _enum(asset["direct_use_status"], "direct_use_status", frozenset({"student-ready", "teacher-only", "blocked", "manual-review"}), "quality-direct-use-status-invalid")
        correction = _optional_text(asset["correction_requirement"], "correction_requirement")
        replacement = _bool(asset["replacement_required"], "replacement_required")
        if findings and direct_use == "student-ready" and repair != "completed":
            raise ContractValidationError("quality-unresolved-content", "unresolved content cannot be student-ready")
        if repair == "required" and correction is None and not replacement:
            raise ContractValidationError("quality-missing-correction", "required repair needs correction or replacement evidence")
        if direct_use == "student-ready" and statuses["classroom_readiness"] != "ready":
            raise ContractValidationError("readiness-status-contradiction", "asset direct use and manifest readiness conflict")
        if direct_use in {"blocked", "manual-review"}:
            manual.add("quality-content-manual-review")
        transformations = set(
            canonical_strings(asset["transformations"], name="transformations", maximum=MAX_TRANSFORMATIONS, validator=_transformation)
        )
        required_context = set(
            canonical_strings(asset["required_context_flags"], name="required context flags", maximum=MAX_CONTEXT_FLAGS, validator=_context_flag)
        )
        preserved_context = set(
            canonical_strings(asset["preserved_context_flags"], name="preserved context flags", maximum=MAX_CONTEXT_FLAGS, validator=_context_flag)
        )
        complete = _bool(asset["context_preservation_complete"], "context_preservation_complete")
        if complete and not required_context.issubset(preserved_context):
            raise ContractValidationError("asset-context-not-preserved", "required instructional context is missing")
        if required_context and not complete:
            manual.add("asset-context-manual-review")
        if transformations & {"manual-review", "no-safe-transformation"}:
            manual.add("asset-transformation-manual-review")
        if relationship == "unknown" or disposition == "manual-review":
            manual.add("asset-duplicate-manual-review")
    return manual


def _warning_signal(value: object) -> str:
    return _enum(value, "warning signal", WARNING_SIGNALS, "asset-warning-signal-invalid")


def _privacy_observation(value: object) -> str:
    return _enum(value, "privacy observation", PRIVACY_OBSERVATIONS, "asset-privacy-observation-invalid")


def _content_finding(value: object) -> str:
    return _enum(value, "content finding", CONTENT_FINDINGS, "quality-content-finding-invalid")


def _transformation(value: object) -> str:
    return _enum(value, "transformation", TRANSFORMATIONS, "asset-transformation-invalid")


def _context_flag(value: object) -> str:
    return _enum(value, "context flag", CONTEXT_FLAGS, "asset-context-flag-invalid")


def _references(values: list[Any]) -> None:
    if len(values) > MAX_REFERENCES:
        raise ContractValidationError("handoff-oversized", "references exceed their collection bound")
    seen: set[str] = set()
    fields = frozenset({"reference_id", "kind", "stable_ref", "fingerprint"})
    for raw in values:
        ref = validate_mapping(raw, "reference")
        _fields(ref, fields, "reference")
        reference_id = validate_stable_id(ref["reference_id"], "reference_id")
        if reference_id in seen:
            raise ContractValidationError("artifact-duplicate-reference", "reference IDs must be unique")
        seen.add(reference_id)
        validate_stable_id(ref["kind"], "reference kind")
        validate_stable_id(ref["stable_ref"], "reference stable_ref")
        validate_sha256(ref["fingerprint"], "reference fingerprint")


def _custom_properties(value: dict[str, Any], groups: dict[str, dict[str, Any]]) -> None:
    if set(value) - CUSTOM_PROPERTY_KEYS:
        raise ContractValidationError("artifact-custom-property-full-manifest", "custom properties may contain compact discovery keys only")
    if len(value) > len(CUSTOM_PROPERTY_KEYS):
        raise ContractValidationError("artifact-custom-property-invalid", "too many custom properties")
    for key, item in value.items():
        if type(item) is not str:
            raise ContractValidationError("handoff-wrong-type", "custom properties must contain built-in strings")
        validate_text(item, f"custom property {key}", max_length=128)
    expected = {
        "manifest_id": groups["identity"]["manifest_id"],
        "requirement_id": groups["requirement_reference"]["requirement_id"],
        "contract_version": groups["identity"]["contract_version"],
        "idempotency_key": groups["operation"]["idempotency_key"],
    }
    for key, item in value.items():
        if item != expected[key]:
            raise ContractValidationError("artifact-custom-property-conflict", "custom property conflicts with manifest evidence")


def _authority(value: dict[str, Any]) -> None:
    expected = frozenset(
        {"execution_authorized", "external_write_authorized", "production_authorized", "publication_authorized", "side_effects_performed"}
    )
    _fields(value, expected, "authority")
    for key, item in value.items():
        if type(item) is not bool or item is not False:
            raise ContractValidationError("authority-invalid", f"{key} must be the built-in false value")
