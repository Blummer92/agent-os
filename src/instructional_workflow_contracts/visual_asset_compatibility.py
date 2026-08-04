"""Pure validation for governed visual-asset compatibility evidence."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Callable

from visual_asset_sync.models import ExistingAssetRecord

from .artifact_manifest import (
    CONTRACT_ID as MANIFEST_CONTRACT_ID,
    validate_artifact_manifest,
)
from .common import (
    FINGERPRINT_ALGORITHM,
    MAX_RESULT_BYTES,
    ContractValidationError,
    ValidatedRecord,
    ValidationResult,
    ValidationStatus,
    canonical_size,
    canonical_strings,
    freeze_json,
    sanitize_detail,
    sha256_hex,
    validate_and_normalize_json,
    validate_sha256,
    validate_stable_id,
    validate_text,
    validate_timestamp,
)
from .material_requirement import VISUAL_ORIENTATIONS, VISUAL_ROLE_TYPES


CONTRACT_ID = "curriculum-visual-asset-compatibility-v1"
MAX_INPUT_BYTES = 64 * 1024
MAX_ROLE_TYPES = 10
MAX_MATERIAL_TYPES = 16

ACCESSIBILITY_REVIEW_STATES = frozenset(
    {
        "pass",
        "fail",
        "not-assessed",
        "manual-review-required",
    }
)
ACCESSIBILITY_DESCRIPTION_STATES = frozenset(
    {
        "alt-text-present",
        "equivalent-description-present",
        "not-required",
        "missing",
        "manual-review-required",
    }
)
ORIENTATION_EVIDENCE = frozenset(VISUAL_ORIENTATIONS | {"flexible"})
ASPECT_STATES = frozenset(
    {
        "exact",
        "flexible",
        "mismatch",
        "unspecified",
    }
)
APPROVED_USE_STATES = frozenset(
    {
        "approved",
        "denied",
        "pending",
        "expired",
        "manual-review-required",
    }
)

TOP_LEVEL_FIELDS = frozenset(
    {
        "library_record",
        "artifact_manifest",
        "compatibility_evidence",
    }
)
EVIDENCE_FIELDS = frozenset(
    {
        "contract_version",
        "manifest_reference",
        "asset_reference",
        "library_reference",
        "purpose",
        "accessibility",
        "orientation",
        "approved_use",
        "freshness",
        "authority",
    }
)


def validate_visual_asset_compatibility_evidence(
    value: object,
) -> ValidationResult:
    """Validate one library-record-to-manifest-asset compatibility envelope."""
    try:
        envelope = _envelope(value)
        library = _library_record(envelope["library_record"])
        manifest_record = _manifest_record(envelope["artifact_manifest"])
        manifest = manifest_record.to_dict()
        evidence = _mapping(
            envelope["compatibility_evidence"],
            "compatibility_evidence",
        )
        _fields(evidence, EVIDENCE_FIELDS, "compatibility_evidence")

        contract_version = validate_text(
            evidence["contract_version"],
            "compatibility contract_version",
            max_length=64,
        )
        if contract_version != CONTRACT_ID:
            raise ContractValidationError(
                "handoff-version-unsupported",
                "visual compatibility contract version is unsupported",
            )

        manifest_reference = _mapping(
            evidence["manifest_reference"],
            "manifest_reference",
        )
        _fields(
            manifest_reference,
            frozenset(
                {
                    "manifest_id",
                    "record_revision",
                    "fingerprint",
                    "verified_at",
                    "external_file_id",
                }
            ),
            "manifest_reference",
        )

        asset_reference = _mapping(
            evidence["asset_reference"],
            "asset_reference",
        )
        _fields(
            asset_reference,
            frozenset(
                {
                    "asset_id",
                    "stable_ref",
                    "content_fingerprint",
                }
            ),
            "asset_reference",
        )

        library_reference = _mapping(
            evidence["library_reference"],
            "library_reference",
        )
        _fields(
            library_reference,
            frozenset({"page_id", "drive_file_id"}),
            "library_reference",
        )

        purpose = _purpose(evidence["purpose"])
        accessibility = _accessibility(evidence["accessibility"])
        orientation = _orientation(evidence["orientation"])
        approved_use = _approved_use(evidence["approved_use"])
        freshness = _freshness(evidence["freshness"])
        authority = _authority(evidence["authority"])

        _bind_manifest_reference(
            manifest_reference,
            manifest_record,
            manifest,
        )
        _bind_library_reference(
            library_reference,
            library,
            manifest,
        )
        matched_asset = _match_asset(asset_reference, manifest)

        classification, reasons = _classification(
            matched_asset=matched_asset,
            purpose=purpose,
            accessibility=accessibility,
            orientation=orientation,
            approved_use=approved_use,
            freshness=freshness,
        )

        normalized_payload = {
            "contract_version": CONTRACT_ID,
            "compatibility_id": _compatibility_id(
                manifest_reference=manifest_reference,
                asset_reference=asset_reference,
                library_reference=library_reference,
                purpose=purpose,
                accessibility=accessibility,
                orientation=orientation,
                approved_use=approved_use,
                freshness=freshness,
            ),
            "classification": classification,
            "reason_codes": list(reasons),
            "manifest_reference": manifest_reference,
            "asset_reference": asset_reference,
            "library_reference": library_reference,
            "purpose": purpose,
            "accessibility": accessibility,
            "orientation": orientation,
            "approved_use": approved_use,
            "freshness": freshness,
            "matched_asset": matched_asset,
            "authority": authority,
        }
        normalized_payload = validate_and_normalize_json(
            normalized_payload,
            max_bytes=MAX_RESULT_BYTES,
        )
        if type(normalized_payload) is not dict:
            raise ContractValidationError(
                "asset-compatibility-invalid",
                "compatibility output must be a built-in mapping",
            )
        if canonical_size(normalized_payload) > MAX_RESULT_BYTES:
            raise ContractValidationError(
                "handoff-oversized",
                "compatibility result exceeds the shared result-size bound",
            )

        record = ValidatedRecord(
            contract_version=CONTRACT_ID,
            record_id=normalized_payload["compatibility_id"],
            record_revision=1,
            fingerprint_algorithm=FINGERPRINT_ALGORITHM,
            fingerprint=sha256_hex(normalized_payload),
            payload=freeze_json(normalized_payload),
        )

        if classification == "manual-review-required":
            return ValidationResult(
                status=ValidationStatus.MANUAL_REVIEW_REQUIRED,
                record=record,
                reason_codes=reasons,
                details=("supplied evidence requires bounded human review",),
            )

        return ValidationResult(
            status=ValidationStatus.VALID,
            record=record,
        )
    except ContractValidationError as exc:
        return _invalid(exc.reason_code, exc.detail)
    except (TypeError, ValueError) as exc:
        return _invalid(
            "asset-compatibility-invalid",
            sanitize_detail(str(exc)),
        )


def _envelope(value: object) -> dict[str, Any]:
    if type(value) is not dict:
        raise ContractValidationError(
            "handoff-wrong-type",
            "compatibility input must be a built-in mapping",
        )
    if set(value) != TOP_LEVEL_FIELDS:
        raise ContractValidationError(
            "handoff-unknown-field",
            "compatibility input fields are not exact",
        )
    return value


def _library_record(value: object) -> dict[str, Any]:
    if type(value) is ExistingAssetRecord:
        raw = asdict(value)
    elif type(value) is dict:
        raw = value
    else:
        raise ContractValidationError(
            "handoff-wrong-type",
            "library_record must be ExistingAssetRecord or a built-in mapping",
        )

    normalized = validate_and_normalize_json(
        raw,
        max_bytes=16 * 1024,
    )
    if type(normalized) is not dict:
        raise ContractValidationError(
            "handoff-wrong-type",
            "library_record must normalize to a built-in mapping",
        )

    expected = frozenset(
        {
            "page_id",
            "page_url",
            "drive_file_id",
            "drive_url",
            "asset_title",
            "approved_use",
            "asset_type",
            "human_review_status",
            "review_date",
            "extra_fields",
        }
    )
    _fields(normalized, expected, "library_record")
    validate_stable_id(normalized["page_id"], "library page_id")
    validate_text(normalized["drive_file_id"], "library drive_file_id")
    if type(normalized["extra_fields"]) is not dict:
        raise ContractValidationError(
            "handoff-wrong-type",
            "library extra_fields must be a built-in mapping",
        )
    return normalized


def _manifest_record(value: object) -> ValidatedRecord:
    supplied: ValidatedRecord | None = None
    if type(value) is ValidationResult:
        if value.record is None:
            raise ContractValidationError(
                "asset-compatibility-invalid-manifest",
                "artifact manifest result must contain a record",
            )
        supplied = value.record
        raw = supplied.to_dict()
    elif type(value) is ValidatedRecord:
        supplied = value
        raw = supplied.to_dict()
    else:
        raw = value

    result = validate_artifact_manifest(raw)
    if result.status is not ValidationStatus.VALID or result.record is None:
        raise ContractValidationError(
            "asset-compatibility-invalid-manifest",
            "artifact manifest must be structurally valid",
        )
    reconstructed = result.record
    if reconstructed.contract_version != MANIFEST_CONTRACT_ID:
        raise ContractValidationError(
            "asset-compatibility-incompatible-manifest",
            "artifact manifest contract version is incompatible",
        )
    if supplied is not None and (
        supplied.contract_version != reconstructed.contract_version
        or supplied.record_id != reconstructed.record_id
        or supplied.record_revision != reconstructed.record_revision
        or supplied.fingerprint != reconstructed.fingerprint
    ):
        raise ContractValidationError(
            "asset-compatibility-invalid-manifest",
            "supplied manifest record does not match reconstructed evidence",
        )
    return reconstructed


def _purpose(value: object) -> dict[str, Any]:
    data = _mapping(value, "purpose")
    _fields(
        data,
        frozenset({"role_types", "decorative_only"}),
        "purpose",
    )
    if type(data["decorative_only"]) is not bool:
        raise ContractValidationError(
            "handoff-wrong-type",
            "decorative_only must be a built-in boolean",
        )
    roles = canonical_strings(
        data["role_types"],
        name="compatible visual role types",
        maximum=MAX_ROLE_TYPES,
        validator=_visual_role_type,
        allow_empty=True,
    )
    return {
        "role_types": list(roles),
        "decorative_only": data["decorative_only"],
    }


def _accessibility(value: object) -> dict[str, Any]:
    data = _mapping(value, "accessibility")
    _fields(
        data,
        frozenset(
            {
                "review_state",
                "description_state",
                "description_reference",
            }
        ),
        "accessibility",
    )
    review = _enum(
        data["review_state"],
        "accessibility review_state",
        ACCESSIBILITY_REVIEW_STATES,
    )
    description = _enum(
        data["description_state"],
        "accessibility description_state",
        ACCESSIBILITY_DESCRIPTION_STATES,
    )
    reference = data["description_reference"]
    if reference is not None:
        reference = validate_stable_id(
            reference,
            "accessibility description_reference",
        )
    if description in {
        "alt-text-present",
        "equivalent-description-present",
    } and reference is None:
        raise ContractValidationError(
            "asset-accessibility-contradiction",
            "accessible description evidence requires a stable reference",
        )
    return {
        "review_state": review,
        "description_state": description,
        "description_reference": reference,
    }


def _orientation(value: object) -> dict[str, Any]:
    data = _mapping(value, "orientation")
    _fields(
        data,
        frozenset({"orientation", "aspect_state"}),
        "orientation",
    )
    return {
        "orientation": _enum(
            data["orientation"],
            "orientation evidence",
            ORIENTATION_EVIDENCE,
        ),
        "aspect_state": _enum(
            data["aspect_state"],
            "aspect_state",
            ASPECT_STATES,
        ),
    }


def _approved_use(value: object) -> dict[str, Any]:
    data = _mapping(value, "approved_use")
    _fields(
        data,
        frozenset({"state", "role_types", "material_types"}),
        "approved_use",
    )
    roles = canonical_strings(
        data["role_types"],
        name="approved visual role types",
        maximum=MAX_ROLE_TYPES,
        validator=_visual_role_type,
        allow_empty=True,
    )
    materials = canonical_strings(
        data["material_types"],
        name="approved material types",
        maximum=MAX_MATERIAL_TYPES,
        validator=lambda item: validate_stable_id(
            item,
            "approved material type",
        ),
        allow_empty=True,
    )
    return {
        "state": _enum(
            data["state"],
            "approved-use state",
            APPROVED_USE_STATES,
        ),
        "role_types": list(roles),
        "material_types": list(materials),
    }


def _freshness(value: object) -> dict[str, Any]:
    data = _mapping(value, "freshness")
    _fields(
        data,
        frozenset(
            {
                "manifest_record_revision",
                "manifest_fingerprint",
                "manifest_verified_at",
                "compatibility_verified_at",
                "stale",
            }
        ),
        "freshness",
    )
    revision = data["manifest_record_revision"]
    if type(revision) is not int or revision < 1:
        raise ContractValidationError(
            "identity-invalid",
            "manifest_record_revision must be a positive built-in integer",
        )
    if type(data["stale"]) is not bool:
        raise ContractValidationError(
            "handoff-wrong-type",
            "freshness stale must be a built-in boolean",
        )
    return {
        "manifest_record_revision": revision,
        "manifest_fingerprint": validate_sha256(
            data["manifest_fingerprint"],
            "freshness manifest_fingerprint",
        ),
        "manifest_verified_at": validate_timestamp(
            data["manifest_verified_at"],
            "freshness manifest_verified_at",
        ),
        "compatibility_verified_at": validate_timestamp(
            data["compatibility_verified_at"],
            "freshness compatibility_verified_at",
        ),
        "stale": data["stale"],
    }


def _authority(value: object) -> dict[str, bool]:
    data = _mapping(value, "authority")
    expected = frozenset(
        {
            "execution_authorized",
            "external_write_authorized",
            "production_authorized",
            "publication_authorized",
            "side_effects_performed",
        }
    )
    _fields(data, expected, "authority")
    for key, item in data.items():
        if type(item) is not bool or item is not False:
            raise ContractValidationError(
                "authority-invalid",
                f"{key} must be the built-in false value",
            )
    return {key: False for key in sorted(expected)}


def _bind_manifest_reference(
    reference: dict[str, Any],
    record: ValidatedRecord,
    manifest: dict[str, Any],
) -> None:
    if reference["manifest_id"] != record.record_id:
        raise ContractValidationError(
            "identity-invalid",
            "manifest reference ID does not match validated manifest",
        )
    if reference["record_revision"] != record.record_revision:
        raise ContractValidationError(
            "identity-invalid",
            "manifest reference revision does not match validated manifest",
        )
    if reference["fingerprint"] != record.fingerprint:
        raise ContractValidationError(
            "identity-invalid",
            "manifest reference fingerprint does not match validated manifest",
        )
    if reference["verified_at"] != manifest["identity"]["verified_at"]:
        raise ContractValidationError(
            "identity-invalid",
            "manifest verification timestamp is contradictory",
        )
    if (
        reference["external_file_id"]
        != manifest["external_identity"]["file_id"]
    ):
        raise ContractValidationError(
            "identity-invalid",
            "manifest external file identity is contradictory",
        )


def _bind_library_reference(
    reference: dict[str, Any],
    library: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    if reference["page_id"] != library["page_id"]:
        raise ContractValidationError(
            "identity-invalid",
            "library page identity is contradictory",
        )
    if reference["drive_file_id"] != library["drive_file_id"]:
        raise ContractValidationError(
            "identity-invalid",
            "library Drive identity is contradictory",
        )
    if (
        library["drive_file_id"]
        != manifest["external_identity"]["file_id"]
    ):
        raise ContractValidationError(
            "identity-invalid",
            "library and manifest Drive file identities do not match",
        )


def _match_asset(
    reference: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any] | None:
    asset_id = validate_stable_id(
        reference["asset_id"],
        "asset_reference asset_id",
    )
    stable_ref = validate_stable_id(
        reference["stable_ref"],
        "asset_reference stable_ref",
    )
    fingerprint = validate_sha256(
        reference["content_fingerprint"],
        "asset_reference content_fingerprint",
    )

    matches = [
        asset
        for asset in manifest["assets"]
        if asset["asset_id"] == asset_id
        and asset["stable_ref"] == stable_ref
        and asset["content_fingerprint"] == fingerprint
    ]
    if len(matches) > 1:
        raise ContractValidationError(
            "asset-duplicate-id",
            "asset identity matched more than one manifest asset",
        )
    if not matches:
        return None

    asset = matches[0]
    return {
        "asset_id": asset["asset_id"],
        "stable_ref": asset["stable_ref"],
        "content_fingerprint": asset["content_fingerprint"],
        "duplicate_relationship": asset["duplicate_relationship"],
        "disposition": asset["disposition"],
        "canonical_asset_ref": asset["canonical_asset_ref"],
    }


def _classification(
    *,
    matched_asset: dict[str, Any] | None,
    purpose: dict[str, Any],
    accessibility: dict[str, Any],
    orientation: dict[str, Any],
    approved_use: dict[str, Any],
    freshness: dict[str, Any],
) -> tuple[str, tuple[str, ...]]:
    rejected: set[str] = set()
    manual: set[str] = set()

    if matched_asset is None:
        manual.add("manual-review-asset-association-missing")

    if purpose["decorative_only"]:
        rejected.add("asset-purpose-decorative-only")
    elif not purpose["role_types"]:
        manual.add("manual-review-asset-purpose-missing")

    if accessibility["review_state"] == "fail":
        rejected.add("asset-accessibility-failed")
    elif accessibility["review_state"] in {
        "not-assessed",
        "manual-review-required",
    }:
        manual.add("manual-review-asset-accessibility")

    if accessibility["description_state"] == "missing":
        rejected.add("asset-accessibility-description-missing")
    elif accessibility["description_state"] == "manual-review-required":
        manual.add("manual-review-asset-accessibility-description")

    if orientation["aspect_state"] == "mismatch":
        rejected.add("asset-orientation-mismatch")
    elif orientation["aspect_state"] == "unspecified":
        manual.add("manual-review-asset-orientation")

    if approved_use["state"] in {"denied", "expired"}:
        rejected.add("asset-approved-use-rejected")
    elif approved_use["state"] in {
        "pending",
        "manual-review-required",
    }:
        manual.add("manual-review-asset-approved-use")
    elif approved_use["state"] == "approved":
        if not approved_use["role_types"]:
            manual.add("manual-review-asset-approved-role-missing")
        if not approved_use["material_types"]:
            manual.add("manual-review-asset-approved-material-missing")

    if freshness["stale"]:
        manual.add("manual-review-asset-compatibility-stale")

    if rejected:
        return "hard-rejection", tuple(sorted(rejected))
    if manual:
        return "manual-review-required", tuple(sorted(manual))
    return "eligible", ()


def _compatibility_id(
    **parts: object,
) -> str:
    return "visual-compatibility-" + sha256_hex(
        {
            "contract_version": CONTRACT_ID,
            **parts,
        }
    )[:24]


def _visual_role_type(value: object) -> str:
    role = validate_text(
        value,
        "visual role type",
        max_length=64,
    )
    if role not in VISUAL_ROLE_TYPES:
        raise ContractValidationError(
            "asset-purpose-invalid",
            "visual role type is not governed",
        )
    return role


def _mapping(value: object, name: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ContractValidationError(
            "handoff-wrong-type",
            f"{name} must be a built-in mapping",
        )
    return value


def _fields(
    value: dict[str, Any],
    expected: frozenset[str],
    name: str,
) -> None:
    if set(value) != expected:
        raise ContractValidationError(
            "handoff-unknown-field",
            f"{name} fields are not exact",
        )


def _enum(
    value: object,
    name: str,
    allowed: frozenset[str],
) -> str:
    text = validate_text(value, name, max_length=64)
    if text not in allowed:
        raise ContractValidationError(
            "asset-compatibility-invalid",
            f"{name} is unsupported",
        )
    return text


def _invalid(reason: str, detail: str) -> ValidationResult:
    return ValidationResult(
        status=ValidationStatus.INVALID,
        record=None,
        reason_codes=(reason,),
        details=(sanitize_detail(detail),),
    )
