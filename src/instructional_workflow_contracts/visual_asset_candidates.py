"""Pure deterministic filtering of governed visual-asset candidates."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from visual_asset_sync.models import ExistingAssetRecord

from .artifact_manifest import (
    CLEARED_RIGHTS,
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
    freeze_json,
    sanitize_detail,
    sha256_hex,
    validate_and_normalize_json,
    validate_revision,
    validate_stable_id,
    validate_text,
)
from .visual_asset_compatibility import (
    CONTRACT_ID as COMPATIBILITY_CONTRACT_ID,
    validate_visual_asset_compatibility_evidence,
)
from .visual_needs import CONTRACT_ID as VISUAL_NEEDS_CONTRACT_ID

CONTRACT_ID = "curriculum-visual-asset-candidates-v1"
MAX_CANDIDATES = 32
MAX_SOURCE_REVISION_LENGTH = 256
SUPPORTED_ASSET_TYPES = frozenset({"image"})
_SUPPORTED_OPERATIONS = frozenset({"discover-existing", "reuse-existing"})


def filter_approved_visual_candidates(
    visual_needs_plan: object,
    candidates: object,
    *,
    source_revision: object,
) -> ValidationResult:
    """Return bounded eligible, rejected, and manual-review candidate groups."""
    try:
        plan = _plan_record(visual_needs_plan)
        plan_payload = plan.to_dict()
        if plan_payload["outcome"] != "visuals-required":
            raise ContractValidationError(
                "asset-candidates-plan-not-actionable",
                "visual-needs plan must require visuals",
            )

        revision = validate_text(
            source_revision,
            "source_revision",
            max_length=MAX_SOURCE_REVISION_LENGTH,
        )
        raw_candidates = _candidate_list(candidates)
        required_roles = {
            item["role_type"]: item for item in plan_payload["required_roles"]
        }
        optional_roles = {
            item["role_type"]: item for item in plan_payload["optional_roles"]
        }
        governed_roles = {**optional_roles, **required_roles}

        eligible: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        manual_review: list[dict[str, Any]] = []
        seen_candidates: set[str] = set()

        for candidate in raw_candidates:
            compatibility_result = validate_visual_asset_compatibility_evidence(candidate)
            entry = _candidate_entry(compatibility_result)
            if compatibility_result.record is None:
                rejected.append(entry)
                continue

            compatibility = compatibility_result.record.to_dict()
            candidate_id = compatibility_result.record.record_id
            if candidate_id in seen_candidates:
                raise ContractValidationError(
                    "handoff-duplicate",
                    "visual candidate compatibility identities must be unique",
                )
            seen_candidates.add(candidate_id)

            if compatibility_result.record.contract_version != COMPATIBILITY_CONTRACT_ID:
                entry["classification"] = "hard-rejection"
                entry["reason_codes"] = ["asset-candidate-contract-incompatible"]
                rejected.append(entry)
                continue

            classification = compatibility["classification"]
            if classification == "hard-rejection":
                rejected.append(entry)
                continue
            if classification == "manual-review-required":
                manual_review.append(entry)
                continue

            hard_reasons, manual_reasons, identity = _candidate_policy_reasons(
                candidate,
                compatibility=compatibility,
                governed_roles=governed_roles,
                material_type=plan_payload["material_type"],
            )
            entry.update(identity)
            if hard_reasons:
                entry["classification"] = "hard-rejection"
                entry["reason_codes"] = list(hard_reasons)
                rejected.append(entry)
            elif manual_reasons:
                entry["classification"] = "manual-review-required"
                entry["reason_codes"] = list(manual_reasons)
                manual_review.append(entry)
            else:
                eligible.append(entry)

        eligible.sort(key=_candidate_sort_key)
        rejected.sort(key=_candidate_sort_key)
        manual_review.sort(key=_candidate_sort_key)

        revision_fingerprint = sha256_hex(
            {"source_revision": revision, "contract_version": CONTRACT_ID}
        )
        payload = {
            "contract_version": CONTRACT_ID,
            "candidate_set_id": _candidate_set_id(
                plan=plan,
                source_revision=revision,
                eligible=eligible,
                rejected=rejected,
                manual_review=manual_review,
            ),
            "source_revision": revision,
            "source_revision_fingerprint": revision_fingerprint,
            "visual_needs_plan": {
                "contract_version": plan.contract_version,
                "plan_id": plan.record_id,
                "record_revision": plan.record_revision,
                "fingerprint": plan.fingerprint,
            },
            "maximum_candidate_count": MAX_CANDIDATES,
            "candidate_count": len(raw_candidates),
            "eligible_count": len(eligible),
            "rejected_count": len(rejected),
            "manual_review_count": len(manual_review),
            "incomplete_evidence": bool(manual_review),
            "eligible": eligible,
            "rejected": rejected,
            "manual_review": manual_review,
            "authority": {
                "execution_authorized": False,
                "external_write_authorized": False,
                "production_authorized": False,
                "publication_authorized": False,
                "side_effects_performed": False,
            },
        }
        normalized = validate_and_normalize_json(payload, max_bytes=MAX_RESULT_BYTES)
        if type(normalized) is not dict or canonical_size(normalized) > MAX_RESULT_BYTES:
            raise ContractValidationError(
                "handoff-oversized",
                "visual candidate result exceeds the shared result-size bound",
            )
        record = ValidatedRecord(
            contract_version=CONTRACT_ID,
            record_id=normalized["candidate_set_id"],
            record_revision=1,
            fingerprint_algorithm=FINGERPRINT_ALGORITHM,
            fingerprint=sha256_hex(normalized),
            payload=freeze_json(normalized),
        )
        if manual_review:
            return ValidationResult(
                status=ValidationStatus.MANUAL_REVIEW_REQUIRED,
                record=record,
                reason_codes=("manual-review-visual-candidates",),
                details=("one or more candidates require bounded human review",),
            )
        return ValidationResult(status=ValidationStatus.VALID, record=record)
    except ContractValidationError as exc:
        return _invalid(exc.reason_code, exc.detail)
    except (KeyError, TypeError, ValueError) as exc:
        return _invalid("asset-candidates-invalid", sanitize_detail(str(exc)))


def _plan_record(value: object) -> ValidatedRecord:
    supplied: ValidatedRecord
    if type(value) is ValidationResult:
        if value.status is not ValidationStatus.VALID or value.record is None:
            raise ContractValidationError(
                "asset-candidates-invalid-plan",
                "visual-needs validation result must be valid",
            )
        supplied = value.record
    elif type(value) is ValidatedRecord:
        supplied = value
    else:
        raise ContractValidationError(
            "asset-candidates-invalid-plan",
            "visual-needs plan must be validated evidence",
        )

    if supplied.contract_version != VISUAL_NEEDS_CONTRACT_ID:
        raise ContractValidationError(
            "asset-candidates-incompatible-plan",
            "visual-needs contract version is incompatible",
        )
    payload = supplied.to_dict()
    expected = {
        "contract_version",
        "plan_id",
        "source_requirement",
        "material_type",
        "outcome",
        "source_visual_decision",
        "required_roles",
        "optional_roles",
        "accessibility_requirements",
        "cognitive_load_ceiling",
        "maximum_visual_count",
        "manual_review_required",
        "reason_codes",
        "authority",
    }
    if set(payload) != expected:
        raise ContractValidationError(
            "asset-candidates-invalid-plan",
            "visual-needs plan fields are not exact",
        )
    validate_stable_id(payload["plan_id"], "visual-needs plan_id")
    if payload["plan_id"] != supplied.record_id:
        raise ContractValidationError(
            "asset-candidates-invalid-plan",
            "visual-needs plan identity does not match its validated record",
        )
    validate_revision(supplied.record_revision)
    if sha256_hex(payload) != supplied.fingerprint:
        raise ContractValidationError(
            "asset-candidates-invalid-plan",
            "visual-needs plan fingerprint does not reconstruct exactly",
        )
    if type(payload["required_roles"]) is not list or type(payload["optional_roles"]) is not list:
        raise ContractValidationError(
            "asset-candidates-invalid-plan",
            "visual-needs roles must be built-in lists",
        )
    return supplied


def _candidate_list(value: object) -> list[object]:
    if type(value) is not list:
        raise ContractValidationError(
            "handoff-wrong-type",
            "visual candidates must be a built-in list",
        )
    if len(value) > MAX_CANDIDATES:
        raise ContractValidationError(
            "handoff-oversized",
            "visual candidates exceed the 32-candidate bound",
        )
    return value


def _candidate_entry(result: ValidationResult) -> dict[str, Any]:
    if result.record is None:
        return {
            "compatibility": None,
            "library": None,
            "drive": None,
            "manifest": None,
            "asset": None,
            "classification": "invalid",
            "reason_codes": list(result.reason_codes),
        }
    payload = result.record.to_dict()
    manifest = payload["manifest_reference"]
    asset = payload["asset_reference"]
    library = payload["library_reference"]
    return {
        "compatibility": {
            "id": result.record.record_id,
            "fingerprint": result.record.fingerprint,
        },
        "library": {"page_id": library["page_id"]},
        "drive": {"file_id": library["drive_file_id"]},
        "manifest": {
            "id": manifest["manifest_id"],
            "revision": manifest["record_revision"],
            "fingerprint": manifest["fingerprint"],
        },
        "asset": {
            "id": asset["asset_id"],
            "stable_ref": asset["stable_ref"],
            "fingerprint": asset["content_fingerprint"],
        },
        "classification": payload["classification"],
        "reason_codes": list(payload["reason_codes"]),
    }


def _candidate_policy_reasons(
    candidate: object,
    *,
    compatibility: dict[str, Any],
    governed_roles: dict[str, dict[str, Any]],
    material_type: str,
) -> tuple[tuple[str, ...], tuple[str, ...], dict[str, Any]]:
    if type(candidate) is not dict:
        raise ContractValidationError(
            "handoff-wrong-type",
            "visual candidate must be a built-in mapping",
        )
    manifest_result = _manifest_result(candidate["artifact_manifest"])
    if manifest_result.record is None:
        return tuple(manifest_result.reason_codes), (), {}
    manifest = manifest_result.record.to_dict()
    library = _library_mapping(candidate["library_record"])
    asset = _matched_asset(manifest, compatibility["asset_reference"])

    hard = set(
        _plan_mismatch_reasons(
            compatibility,
            governed_roles=governed_roles,
            material_type=material_type,
        )
    )
    manual = set(manifest_result.reason_codes) if manifest_result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED else set()

    asset_type = library.get("asset_type")
    if asset_type is None:
        manual.add("manual-review-asset-type-missing")
    elif asset_type not in SUPPORTED_ASSET_TYPES:
        hard.add("asset-candidate-type-unsupported")

    review = library.get("human_review_status")
    if review in {"rejected", "denied"}:
        hard.add("asset-human-review-rejected")
    elif review != "approved":
        manual.add("manual-review-asset-human-review")
    elif library.get("review_date") is None:
        manual.add("manual-review-asset-review-date")

    external = manifest["external_identity"]
    access = external["access_state"]
    if access in {"denied", "trashed"}:
        hard.add("asset-access-rejected")
    elif access != "verified":
        manual.add("manual-review-asset-access")
    if manifest["source_snapshot"]["source_changed"]:
        manual.add("manual-review-asset-source-changed")

    statuses = manifest["statuses"]
    quality = statuses["quality_state"]
    if quality == "fail":
        hard.add("quality-candidate-failed")
    elif quality != "pass":
        manual.add("manual-review-asset-quality")
    teacher = statuses["teacher_approval"]
    if teacher == "rejected":
        hard.add("readiness-teacher-rejected")
    elif teacher != "approved":
        manual.add("manual-review-asset-teacher-approval")
    readiness = statuses["classroom_readiness"]
    if readiness == "blocked":
        hard.add("readiness-classroom-blocked")
    elif readiness != "ready":
        manual.add("manual-review-asset-readiness")

    rights = asset["rights_classification"]
    if rights == "restricted-or-do-not-distribute":
        hard.add("asset-rights-rejected")
    elif rights not in CLEARED_RIGHTS:
        manual.add("asset-rights-manual-review")
    if not asset["privacy_resolved"] or asset["residual_privacy_risk"]:
        hard.add("asset-privacy-unresolved")

    direct_use = asset["direct_use_status"]
    if direct_use in {"teacher-only", "blocked"}:
        hard.add("quality-direct-use-rejected")
    elif direct_use != "student-ready":
        manual.add("manual-review-asset-direct-use")
    if asset["repair_source_status"] == "required":
        hard.add("quality-repair-required")
    elif asset["repair_source_status"] == "manual-review":
        manual.add("manual-review-asset-repair")
    if asset["replacement_required"]:
        hard.add("quality-replacement-required")

    relationship = asset["duplicate_relationship"]
    disposition = asset["disposition"]
    if disposition in {"alternate", "archive-candidate"}:
        hard.add("asset-duplicate-disposition-rejected")
    elif relationship == "unknown" or disposition == "manual-review":
        manual.add("manual-review-asset-duplicate")

    operation = manifest["operation"]["kind"]
    if operation == "manual-review":
        manual.add("manual-review-asset-lifecycle")
    elif operation not in _SUPPORTED_OPERATIONS:
        hard.add("artifact-lifecycle-ineligible")

    if hard:
        manual.clear()

    identity = {
        "drive": {
            "file_id": external["file_id"],
            "drive_id": external["drive_id"],
        },
        "manifest": {
            "id": manifest["identity"]["manifest_id"],
            "revision": manifest["identity"]["record_revision"],
            "fingerprint": manifest_result.record.fingerprint,
        },
        "asset": {
            "id": asset["asset_id"],
            "stable_ref": asset["stable_ref"],
            "fingerprint": asset["content_fingerprint"],
        },
    }
    return tuple(sorted(hard)), tuple(sorted(manual)), identity


def _manifest_result(value: object) -> ValidationResult:
    supplied: ValidatedRecord | None = None
    if type(value) is ValidationResult:
        if value.record is None:
            return value
        supplied = value.record
        raw = supplied.to_dict()
    elif type(value) is ValidatedRecord:
        supplied = value
        raw = supplied.to_dict()
    else:
        raw = value
    result = validate_artifact_manifest(raw)
    if result.record is None:
        return result
    if result.record.contract_version != MANIFEST_CONTRACT_ID:
        raise ContractValidationError(
            "asset-candidate-manifest-incompatible",
            "artifact manifest contract version is incompatible",
        )
    if supplied is not None and (
        supplied.contract_version != result.record.contract_version
        or supplied.record_id != result.record.record_id
        or supplied.record_revision != result.record.record_revision
        or supplied.fingerprint != result.record.fingerprint
    ):
        raise ContractValidationError(
            "asset-candidate-manifest-incompatible",
            "supplied artifact manifest does not reconstruct exactly",
        )
    return result


def _library_mapping(value: object) -> dict[str, Any]:
    if type(value) is ExistingAssetRecord:
        return asdict(value)
    if type(value) is dict:
        return value
    raise ContractValidationError(
        "handoff-wrong-type",
        "library record must be ExistingAssetRecord or a built-in mapping",
    )


def _matched_asset(
    manifest: dict[str, Any],
    reference: dict[str, Any],
) -> dict[str, Any]:
    matches = [
        asset
        for asset in manifest["assets"]
        if asset["asset_id"] == reference["asset_id"]
        and asset["stable_ref"] == reference["stable_ref"]
        and asset["content_fingerprint"] == reference["content_fingerprint"]
    ]
    if len(matches) != 1:
        raise ContractValidationError(
            "asset-candidate-identity-invalid",
            "candidate asset identity must match exactly one manifest asset",
        )
    return matches[0]


def _plan_mismatch_reasons(
    compatibility: dict[str, Any],
    *,
    governed_roles: dict[str, dict[str, Any]],
    material_type: str,
) -> tuple[str, ...]:
    reasons: list[str] = []
    compatible_roles = set(compatibility["purpose"]["role_types"])
    approved_roles = set(compatibility["approved_use"]["role_types"])
    matched_roles = compatible_roles & approved_roles & set(governed_roles)
    if not matched_roles:
        reasons.append("asset-candidate-role-mismatch")
    approved_materials = set(compatibility["approved_use"]["material_types"])
    if material_type not in approved_materials:
        reasons.append("asset-candidate-material-mismatch")
    orientation = compatibility["orientation"]["orientation"]
    if matched_roles and orientation != "flexible":
        if not any(
            governed_roles[role]["orientation"] in {orientation, "unspecified"}
            for role in matched_roles
        ):
            reasons.append("asset-candidate-orientation-mismatch")
    return tuple(sorted(reasons))


def _candidate_sort_key(item: dict[str, Any]) -> tuple[object, ...]:
    compatibility = item.get("compatibility") or {}
    manifest = item.get("manifest") or {}
    asset = item.get("asset") or {}
    return (
        compatibility.get("id") or "",
        manifest.get("id") or "",
        asset.get("id") or "",
        tuple(item["reason_codes"]),
    )


def _candidate_set_id(
    *,
    plan: ValidatedRecord,
    source_revision: str,
    eligible: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    manual_review: list[dict[str, Any]],
) -> str:
    identity = {
        "contract_version": CONTRACT_ID,
        "plan_id": plan.record_id,
        "plan_revision": plan.record_revision,
        "plan_fingerprint": plan.fingerprint,
        "source_revision": source_revision,
        "eligible": eligible,
        "rejected": rejected,
        "manual_review": manual_review,
    }
    return validate_stable_id(
        "visual-candidates-" + sha256_hex(identity)[:24],
        "candidate_set_id",
    )


def _invalid(reason: str, detail: str) -> ValidationResult:
    return ValidationResult(
        status=ValidationStatus.INVALID,
        record=None,
        reason_codes=(reason,),
        details=(sanitize_detail(detail),),
    )
