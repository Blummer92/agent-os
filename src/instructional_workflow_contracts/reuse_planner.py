"""Pure advisory dependency-impact and artifact-reuse planning."""

from __future__ import annotations

from typing import Any, Callable

from .common import (
    FINGERPRINT_ALGORITHM,
    MAX_RESULT_BYTES as SHARED_MAX_RESULT_BYTES,
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
    validate_dependency_key,
    validate_reason_code,
    validate_stable_id,
    validate_text,
)
from .material_requirement import (
    V1_CONTRACT_ID as MATERIAL_V1_CONTRACT_ID,
    V2_CONTRACT_ID as MATERIAL_V2_CONTRACT_ID,
    validate_material_requirement,
)
from .artifact_manifest import CONTRACT_ID as MANIFEST_CONTRACT_ID, validate_artifact_manifest

CONTRACT_ID = "curriculum-artifact-reuse-plan-v1"
MAX_COMBINED_INPUT_BYTES = 256 * 1024
MAX_RESULT_BYTES = 32 * 1024
MAX_CANDIDATES = 32
MAX_DEPENDENCY_KEYS = 128
MAX_CHANGED_KEYS = 128
MAX_REJECTION_REASONS = 64
MAX_IMPACTED_SECTIONS = 128
MAX_VISUAL_RISK_REASONS = 64
MATERIAL_CONTRACT_IDS = frozenset(
    {MATERIAL_V1_CONTRACT_ID, MATERIAL_V2_CONTRACT_ID}
)
MANIFEST_CONTRACT_IDS = frozenset({MANIFEST_CONTRACT_ID})

DECISIONS = (
    "reuse-existing-approved",
    "revise-existing-bounded",
    "reuse-approved-components",
    "copy-approved-template-and-create",
    "create-new-required",
    "manual-review-required",
)
VISUAL_DECISIONS = frozenset(
    {
        "reuse-canonical-asset",
        "reuse-alternate-with-explicit-reason",
        "bounded-context-preserving-crop-or-cleanup",
        "bounded-content-repair",
        "rebuild-or-recreate-required",
        "replacement-asset-required",
        "permission-or-rights-review-required",
        "privacy-clearance-or-anonymization-required",
        "manual-review-required",
    }
)
ROUTINE_TRANSFORMS = frozenset(
    {"crop", "zoom", "enlarge", "segment", "rotate", "perspective-correct", "cleanup", "background-cleanup", "edge-cleanup", "contrast-adjustment", "glare-adjustment"}
)
CLEARED_RIGHTS = frozenset({"cleared-internal", "licensed", "public-domain", "permission-documented"})
UNSAFE_CONTENT = frozenset(
    {"malformed-text", "inaccurate-content", "repeated-labels", "truncated-instructions", "misleading-example", "misleading-icon", "answer-revealing-content"}
)


def plan_instructional_artifact_reuse(
    requirement: object,
    candidates: object,
    *,
    changed_dependency_keys: object,
    impact_map: object,
    supported_executor: object = True,
) -> ValidationResult:
    """Return one deterministic advisory plan from supplied validated evidence."""
    try:
        if type(candidates) is not list:
            raise ContractValidationError("handoff-wrong-type", "candidates must be a built-in list")
        if len(candidates) > MAX_CANDIDATES:
            raise ContractValidationError("handoff-oversized", "candidates exceed the 32-item bound")
        if type(supported_executor) is not bool:
            raise ContractValidationError("handoff-wrong-type", "supported_executor must be a built-in boolean")

        requirement_payload = _validated_payload(
            requirement,
            validator=validate_material_requirement,
            contract_ids=MATERIAL_CONTRACT_IDS,
            name="MaterialRequirement",
        )
        manifest_payloads = [
            _validated_payload(
                candidate,
                validator=validate_artifact_manifest,
                contract_ids=MANIFEST_CONTRACT_IDS,
                name="ArtifactManifest",
            )
            for candidate in candidates
        ]
        changed = canonical_strings(
            changed_dependency_keys,
            name="changed dependency keys",
            maximum=MAX_CHANGED_KEYS,
            validator=validate_dependency_key,
            allow_empty=True,
        )
        normalized_map = _impact_map(impact_map)
        combined = {
            "requirement": requirement_payload,
            "candidates": manifest_payloads,
            "changed_dependency_keys": list(changed),
            "impact_map": normalized_map,
            "supported_executor": supported_executor,
        }
        if canonical_size(combined) > MAX_COMBINED_INPUT_BYTES:
            raise ContractValidationError("handoff-oversized", "combined planner input exceeds 256 KiB")

        unmapped = tuple(key for key in changed if key not in normalized_map)
        impacted_sections = tuple(
            sorted({section for key in changed for section in normalized_map.get(key, ())})
        )
        if len(impacted_sections) > MAX_IMPACTED_SECTIONS:
            raise ContractValidationError("handoff-oversized", "impacted sections exceed the 128-item bound")

        ranked = sorted(
            (_candidate_evidence(requirement_payload, payload) for payload in manifest_payloads),
            key=lambda item: (-item["score"], item["manifest_id"]),
        )
        decision, selected, rejections, missing, conflicts, visual = _decide(
            requirement_payload,
            ranked,
            changed,
            unmapped,
            supported_executor,
        )
        if len(rejections) > MAX_REJECTION_REASONS:
            raise ContractValidationError("handoff-oversized", "rejection reasons exceed the 64-item bound")
        visual_reason_count = sum(len(item["reasons"]) for item in visual)
        if visual_reason_count > MAX_VISUAL_RISK_REASONS:
            raise ContractValidationError("handoff-oversized", "visual-risk reasons exceed the 64-item bound")

        human_review = decision == "manual-review-required"
        confidence = _confidence(decision, missing, conflicts, unmapped)
        payload = {
            "contract_version": CONTRACT_ID,
            "plan_id": _plan_id(requirement_payload, ranked, changed, normalized_map, supported_executor),
            "requirement_id": requirement_payload["identity"]["requirement_id"],
            "decision": decision,
            "selected_manifest_id": None if selected is None else selected["manifest_id"],
            "candidate_order": [item["manifest_id"] for item in ranked],
            "rejection_reasons": list(rejections),
            "changed_dependency_keys": list(changed),
            "unmapped_dependency_keys": list(unmapped),
            "impacted_sections": list(impacted_sections),
            "missing_required_evidence": list(missing),
            "conflicting_evidence": list(conflicts),
            "visual_recommendations": visual,
            "confidence": confidence,
            "human_review_required": human_review,
            "recommended_next_owner": "instructional-materials-coach" if human_review else "integration-manager",
            "authority": {
                "execution_authorized": False,
                "external_write_authorized": False,
                "production_authorized": False,
                "publication_authorized": False,
                "side_effects_performed": False,
            },
        }
        result_size = canonical_size(payload)
        if result_size > MAX_RESULT_BYTES:
            raise ContractValidationError("handoff-oversized", "planner result exceeds 32 KiB")
        if result_size > SHARED_MAX_RESULT_BYTES:
            raise ContractValidationError("handoff-oversized", "planner result exceeds the shared 16 KiB record bound")
        record = ValidatedRecord(
            contract_version=CONTRACT_ID,
            record_id=payload["plan_id"],
            record_revision=1,
            fingerprint_algorithm=FINGERPRINT_ALGORITHM,
            fingerprint=sha256_hex(payload),
            payload=freeze_json(payload),
        )
        if human_review:
            return ValidationResult(
                status=ValidationStatus.MANUAL_REVIEW_REQUIRED,
                record=record,
                reason_codes=("manual-review-artifact-reuse-plan",),
                details=("supplied evidence requires bounded human review",),
            )
        return ValidationResult(status=ValidationStatus.VALID, record=record)
    except ContractValidationError as exc:
        return _invalid(exc.reason_code, exc.detail)
    except (TypeError, ValueError) as exc:
        return _invalid("artifact-planner-invalid", sanitize_detail(str(exc)))


def _validated_payload(
    value: object,
    *,
    validator: Callable[[object], ValidationResult],
    contract_ids: frozenset[str],
    name: str,
) -> dict[str, Any]:
    if type(value) is ValidationResult:
        result = value
    elif type(value) is ValidatedRecord:
        result = ValidationResult(status=ValidationStatus.VALID, record=value)
    else:
        result = validator(value)
    if result.status is not ValidationStatus.VALID or result.record is None:
        raise ContractValidationError("artifact-planner-invalid-upstream", f"{name} must be structurally valid")
    if result.record.contract_version not in contract_ids:
        raise ContractValidationError("artifact-planner-incompatible-upstream", f"{name} contract version is incompatible")
    payload = result.record.to_dict()
    if type(payload) is not dict:
        raise ContractValidationError("handoff-wrong-type", f"{name} payload must be a built-in mapping")
    return payload


def _impact_map(value: object) -> dict[str, list[str]]:
    normalized = validate_and_normalize_json(value, max_bytes=64 * 1024)
    if type(normalized) is not dict:
        raise ContractValidationError("handoff-wrong-type", "impact_map must be a built-in mapping")
    if len(normalized) > MAX_DEPENDENCY_KEYS:
        raise ContractValidationError("handoff-oversized", "impact_map exceeds 128 dependency keys")
    result: dict[str, list[str]] = {}
    for raw_key, raw_sections in normalized.items():
        key = validate_dependency_key(raw_key)
        result[key] = list(canonical_strings(
            raw_sections,
            name="impact sections",
            maximum=MAX_IMPACTED_SECTIONS,
            validator=lambda item: validate_stable_id(item, "impact section"),
            allow_empty=False,
        ))
    return dict(sorted(result.items()))


def _candidate_evidence(requirement: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    manifest_id = validate_stable_id(manifest["identity"]["manifest_id"], "manifest_id")
    reasons: list[str] = []
    missing: list[str] = []
    conflicts: list[str] = []
    if manifest["requirement_reference"]["requirement_id"] != requirement["identity"]["requirement_id"]:
        conflicts.append("artifact-requirement-identity-conflict")
    if manifest["artifact"]["artifact_type"] != requirement["artifact"]["artifact_type"]:
        conflicts.append("artifact-type-conflict")
    statuses = manifest["statuses"]
    external = manifest["external_identity"]
    if external["access_state"] != "verified":
        missing.append("artifact-access-unverified")
    if statuses["quality_state"] != "pass":
        missing.append("quality-evidence-missing")
    if statuses["teacher_approval"] != "approved":
        missing.append("readiness-teacher-approval-missing")
    if statuses["classroom_readiness"] != "ready":
        missing.append("readiness-classroom-missing")
    visual = [_visual_recommendation(asset) for asset in manifest.get("assets", [])]
    unsafe_visual = any(item["decision"] not in {"reuse-canonical-asset", "reuse-alternate-with-explicit-reason", "bounded-context-preserving-crop-or-cleanup", "bounded-content-repair"} for item in visual)
    if unsafe_visual:
        reasons.append("asset-visual-risk-review-required")
    score = 100 - 20 * len(conflicts) - 10 * len(missing) - 5 * len(reasons)
    return {
        "manifest_id": manifest_id,
        "payload": manifest,
        "score": score,
        "missing": tuple(sorted(missing)),
        "conflicts": tuple(sorted(conflicts)),
        "reasons": tuple(sorted(reasons)),
        "visual": visual,
        "safe": not missing and not conflicts and not unsafe_visual,
    }


def _visual_recommendation(asset: dict[str, Any]) -> dict[str, Any]:
    asset_id = validate_stable_id(asset["asset_id"], "asset_id")
    rights = asset["rights_classification"]
    privacy_observations = tuple(asset["privacy_observations"])
    residual_privacy = asset["residual_privacy_risk"]
    findings = set(asset["content_findings"])
    transforms = set(asset["transformations"])
    required = set(asset["required_context_flags"])
    preserved = set(asset["preserved_context_flags"])
    reasons: list[str] = []

    if rights not in CLEARED_RIGHTS:
        decision = "permission-or-rights-review-required"
        reasons.append("asset-rights-review-required")
    elif privacy_observations and (residual_privacy or not asset["privacy_resolved"]):
        decision = "privacy-clearance-or-anonymization-required"
        reasons.append("asset-privacy-review-required")
    elif findings & UNSAFE_CONTENT:
        if asset["repair_source_status"] == "completed" and asset["correction_requirement"]:
            decision = "bounded-content-repair"
            reasons.append("quality-bounded-content-repair")
        elif asset["replacement_required"]:
            decision = "replacement-asset-required"
            reasons.append("quality-replacement-required")
        else:
            decision = "rebuild-or-recreate-required"
            reasons.append("quality-rebuild-required")
    elif not required.issubset(preserved) or not asset["context_preservation_complete"]:
        decision = "manual-review-required"
        reasons.append("asset-context-loss-review-required")
    elif transforms & ROUTINE_TRANSFORMS:
        decision = "bounded-context-preserving-crop-or-cleanup"
        reasons.append("asset-bounded-cleanup")
    elif asset["disposition"] == "alternate":
        if asset["canonical_asset_ref"]:
            decision = "reuse-alternate-with-explicit-reason"
            reasons.append("asset-alternate-requires-explicit-reason")
        else:
            decision = "manual-review-required"
            reasons.append("asset-missing-canonical-reference")
    elif asset["disposition"] == "archive-candidate":
        decision = "manual-review-required"
        reasons.append("asset-archive-candidate-rejected")
    elif asset["duplicate_relationship"] == "unknown" or asset["disposition"] == "manual-review":
        decision = "manual-review-required"
        reasons.append("asset-duplicate-evidence-ambiguous")
    else:
        decision = "reuse-canonical-asset"
        reasons.append("asset-canonical-reuse")
    if decision not in VISUAL_DECISIONS:
        raise ContractValidationError("artifact-planner-invalid", "unsupported visual recommendation")
    return {"asset_id": asset_id, "decision": decision, "reasons": sorted(reasons)}


def _decide(
    requirement: dict[str, Any],
    ranked: list[dict[str, Any]],
    changed: tuple[str, ...],
    unmapped: tuple[str, ...],
    supported_executor: bool,
) -> tuple[str, dict[str, Any] | None, tuple[str, ...], tuple[str, ...], tuple[str, ...], list[dict[str, Any]]]:
    rejections: list[str] = []
    missing = sorted({item for candidate in ranked for item in candidate["missing"]})
    conflicts = sorted({item for candidate in ranked for item in candidate["conflicts"]})
    selected = ranked[0] if ranked else None
    visual = [] if selected is None else selected["visual"]

    if not supported_executor:
        rejections.extend(("artifact-reuse-rejected-unsupported-executor", "artifact-revision-rejected-unsupported-executor"))
        return "manual-review-required", selected, tuple(rejections), tuple(missing), tuple(conflicts), visual
    if unmapped:
        rejections.extend(("artifact-reuse-rejected-unmapped-dependency", "artifact-revision-rejected-unmapped-dependency"))
        return "manual-review-required", selected, tuple(rejections), tuple(missing), tuple(conflicts), visual
    if selected is not None and selected["safe"] and not changed:
        return "reuse-existing-approved", selected, (), tuple(missing), tuple(conflicts), visual
    rejections.append("artifact-reuse-rejected-change-or-evidence")
    if selected is not None and selected["safe"] and changed:
        return "revise-existing-bounded", selected, tuple(rejections), tuple(missing), tuple(conflicts), visual
    rejections.append("artifact-revision-rejected-unsafe-or-conflicting")
    if selected is not None and not selected["conflicts"] and selected["payload"].get("assets"):
        return "reuse-approved-components", selected, tuple(rejections), tuple(missing), tuple(conflicts), visual
    rejections.append("artifact-components-rejected-unavailable")
    templates = requirement.get("templates", [])
    if templates:
        return "copy-approved-template-and-create", selected, tuple(rejections), tuple(missing), tuple(conflicts), visual
    rejections.append("template-copy-rejected-unavailable")
    if not ranked:
        return "create-new-required", None, tuple(rejections), tuple(missing), tuple(conflicts), visual
    rejections.append("artifact-create-rejected-review-required")
    return "manual-review-required", selected, tuple(rejections), tuple(missing), tuple(conflicts), visual


def _confidence(decision: str, missing: tuple[str, ...], conflicts: tuple[str, ...], unmapped: tuple[str, ...]) -> str:
    if decision == "manual-review-required":
        return "none"
    if conflicts or unmapped:
        return "low"
    if missing:
        return "medium"
    return "high"


def _plan_id(
    requirement: dict[str, Any],
    ranked: list[dict[str, Any]],
    changed: tuple[str, ...],
    impact_map: dict[str, list[str]],
    supported_executor: bool,
) -> str:
    digest = sha256_hex(
        {
            "requirement_id": requirement["identity"]["requirement_id"],
            "requirement_fingerprint": requirement["identity"]["source_fingerprint"],
            "candidate_fingerprints": [item["payload"]["identity"]["source_fingerprint"] for item in ranked],
            "changed": list(changed),
            "impact_map": impact_map,
            "supported_executor": supported_executor,
        }
    )
    return f"reuse-plan-{digest[:24]}"


def _invalid(reason: str, detail: str) -> ValidationResult:
    validate_reason_code(reason)
    return ValidationResult(
        status=ValidationStatus.INVALID,
        record=None,
        reason_codes=(reason,),
        details=(sanitize_detail(detail),),
    )
