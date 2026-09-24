"""Deterministic adapter from canonical instructional evidence to the PPUX projection input.

This module assembles the existing TypeScript `picture-perfect-prompt-projection-input-v1`
consumer envelope. It creates no new curriculum/source schema and performs no retrieval,
persistence, execution, provider call, or external write.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .common import (
    AuthorityEvidence,
    ContractValidationError,
    ValidatedRecord,
    ValidationResult,
    ValidationStatus,
    canonical_json_bytes,
    sha256_hex,
    validate_and_normalize_json,
    validate_sha256,
    validate_stable_id,
    validate_text,
)
from .handoff import CONTRACT_ID as HANDOFF_CONTRACT_ID, validate_curriculum_handoff
from .material_requirement import (
    V2_CONTRACT_ID as MATERIAL_REQUIREMENT_V2,
    validate_material_requirement,
)
from .visual_needs import CONTRACT_ID as VISUAL_NEEDS_CONTRACT_ID, plan_visual_needs

PPUX_INPUT_VERSION = "picture-perfect-prompt-projection-input-v1"
MAX_INPUT_BYTES = 64 * 1024
_ALLOWED_DISPOSITIONS = frozenset(
    {
        "new-visual",
        "reuse-existing-visual",
        "resurface-prior-visual",
        "no-additional-visual-needed",
        "pathway-compacted",
    }
)
_AUTHORING_REQUIRED = frozenset(
    {
        "imagePurpose",
        "imageState",
        "applicationContext",
        "targetState",
        "mustShow",
        "mustNotShow",
        "annotationSpace",
        "requestedUiDetails",
    }
)
_AUTHORING_OPTIONAL = frozenset(
    {"currentVisualReference", "screenFidelityRequired", "uncertainty"}
)
_STEP_OPTIONAL = frozenset(
    {
        "authoring",
        "approvedAssetRef",
        "reasonRef",
        "visualArtifactIdentity",
        "crossContextExemplarEvidenceRef",
        "instructionalSpecificityEvidenceRefs",
        "promptReferenceEvidenceRefs",
    }
)


@dataclass(frozen=True, slots=True)
class PpuxProjectionInputAssembly:
    status: Literal["valid", "blocked"]
    envelope: dict[str, Any] | None
    canonical_bytes: bytes | None
    sha256: str | None
    byte_length: int | None
    reason_codes: tuple[str, ...]
    authority: AuthorityEvidence = field(default_factory=AuthorityEvidence, init=False)

    def __post_init__(self) -> None:
        if self.status == "valid":
            if self.envelope is None or self.canonical_bytes is None or self.sha256 is None:
                raise ValueError("valid assembly requires complete identity evidence")
            if self.byte_length != len(self.canonical_bytes):
                raise ValueError("byte_length must bind the exact canonical bytes")
            validate_sha256(self.sha256, "projection input sha256")
            if self.reason_codes:
                raise ValueError("valid assembly cannot carry reason codes")
        elif self.status == "blocked":
            if any(item is not None for item in (self.envelope, self.canonical_bytes, self.sha256, self.byte_length)):
                raise ValueError("blocked assembly cannot expose a partial PPUX input")
            if not self.reason_codes:
                raise ValueError("blocked assembly requires a reason code")
        else:
            raise ValueError("unsupported assembly status")


def assemble_ppux_projection_input(
    *,
    handoff: object,
    material_requirement: object,
    visual_needs_plan: object,
    reviewed_tutorial: object,
    routed_steps: object,
) -> PpuxProjectionInputAssembly:
    """Assemble one exact PPUX input from already-resolved canonical evidence.

    The adapter validates/reconstructs the canonical handoff, MaterialRequirement,
    and VisualNeedsPlan through their existing owners. Reviewed tutorial evidence
    and routed steps are consumer projections only; this function checks their
    identity/provenance bindings and never treats them as a new source of truth.
    """
    try:
        handoff_record = _require_valid_record(
            validate_curriculum_handoff(handoff),
            "ppux-handoff-invalid",
        )
        material_record = _require_valid_record(
            validate_material_requirement(material_requirement),
            "ppux-material-invalid",
        )
        if material_record.contract_version != MATERIAL_REQUIREMENT_V2:
            raise _blocked("ppux-material-version-unsupported", "PPUX assembly requires MaterialRequirement v2")

        material_payload = material_record.to_dict()
        _bind_material_to_handoff(material_payload, handoff_record)

        expected_visual = plan_visual_needs(material_record)
        expected_visual_record = _require_valid_record(
            expected_visual,
            "ppux-visual-needs-not-ready",
        )
        supplied_visual_record = _coerce_visual_record(visual_needs_plan)
        if (
            supplied_visual_record.contract_version != VISUAL_NEEDS_CONTRACT_ID
            or supplied_visual_record.record_id != expected_visual_record.record_id
            or supplied_visual_record.record_revision != expected_visual_record.record_revision
            or supplied_visual_record.fingerprint != expected_visual_record.fingerprint
            or supplied_visual_record.to_dict() != expected_visual_record.to_dict()
        ):
            raise _blocked("ppux-visual-needs-mismatch", "visual-needs evidence does not reconstruct from the supplied material requirement")

        visual_payload = supplied_visual_record.to_dict()
        if visual_payload.get("outcome") != "visuals-required":
            raise _blocked("ppux-visual-needs-not-ready", "PPUX projection requires a validated visuals-required plan")

        tutorial = _reviewed_tutorial(reviewed_tutorial)
        steps = _routed_steps(
            routed_steps,
            tutorial=tutorial,
            visual_payload=visual_payload,
        )

        learning = material_payload["learning_evidence"]
        route = {
            "routeId": f"ppux-route:{handoff_record.record_id}:{handoff_record.record_revision}",
            "representation": "tutorial-process",
            "sourceHandoffRef": handoff_record.record_id,
            "sourceFingerprint": handoff_record.fingerprint,
            "objectiveRef": learning["learning_objective_ref"]["stable_id"],
            "successCriteriaRef": learning["success_criteria_ref"]["stable_id"],
            "evidenceTargetRef": learning["evidence_target_ref"]["stable_id"],
            "steps": steps,
        }
        envelope = {
            "formatVersion": PPUX_INPUT_VERSION,
            "tutorial": tutorial,
            "route": route,
        }
        normalized = validate_and_normalize_json(envelope, max_bytes=MAX_INPUT_BYTES)
        if type(normalized) is not dict:
            raise _blocked("ppux-envelope-invalid", "PPUX input must remain a built-in mapping")
        canonical = canonical_json_bytes(normalized)
        return PpuxProjectionInputAssembly(
            status="valid",
            envelope=normalized,
            canonical_bytes=canonical,
            sha256=sha256_hex(normalized),
            byte_length=len(canonical),
            reason_codes=(),
        )
    except _AssemblyBlocked as exc:
        return PpuxProjectionInputAssembly(
            status="blocked",
            envelope=None,
            canonical_bytes=None,
            sha256=None,
            byte_length=None,
            reason_codes=(exc.reason_code,),
        )
    except (ContractValidationError, TypeError, ValueError, KeyError):
        return PpuxProjectionInputAssembly(
            status="blocked",
            envelope=None,
            canonical_bytes=None,
            sha256=None,
            byte_length=None,
            reason_codes=("ppux-input-invalid",),
        )


class _AssemblyBlocked(ValueError):
    def __init__(self, reason_code: str, detail: str) -> None:
        self.reason_code = reason_code
        super().__init__(detail)


def _blocked(reason_code: str, detail: str) -> _AssemblyBlocked:
    return _AssemblyBlocked(reason_code, detail)


def _require_valid_record(result: ValidationResult, reason: str) -> ValidatedRecord:
    if result.status is not ValidationStatus.VALID or result.record is None:
        raise _blocked(reason, "upstream canonical evidence is not valid/current")
    return result.record


def _coerce_visual_record(value: object) -> ValidatedRecord:
    if type(value) is ValidatedRecord:
        return value
    if type(value) is ValidationResult:
        return _require_valid_record(value, "ppux-visual-needs-not-ready")
    raise _blocked("ppux-visual-needs-invalid", "visual_needs_plan must be validated evidence")


def _bind_material_to_handoff(material: dict[str, Any], handoff: ValidatedRecord) -> None:
    ref = material["handoff_reference"]
    if (
        ref["contract_version"] != HANDOFF_CONTRACT_ID
        or ref["handoff_id"] != handoff.record_id
        or ref["record_revision"] != handoff.record_revision
        or ref["fingerprint"] != handoff.fingerprint
    ):
        raise _blocked("ppux-handoff-mismatch", "material requirement is not bound to the supplied handoff")

    modeling = material["modeling"]
    if modeling["modeling_owner"] != "teacher-modeling-coach":
        raise _blocked("ppux-modeling-owner-mismatch", "Teacher Modeling ownership is required")


def _reviewed_tutorial(value: object) -> dict[str, Any]:
    normalized = validate_and_normalize_json(value, max_bytes=MAX_INPUT_BYTES)
    if type(normalized) is not dict:
        raise _blocked("ppux-tutorial-invalid", "reviewed tutorial must be a built-in mapping")
    required = {
        "recording_id",
        "recording_sha256",
        "retained_steps",
        "excluded_step_ids",
        "review_decisions",
        "recording_evidence",
        "execution_authorized",
    }
    if set(normalized) != required:
        raise _blocked("ppux-tutorial-invalid", "reviewed tutorial fields do not match the existing PPUX projection")
    validate_stable_id(normalized["recording_id"], "recording_id")
    validate_sha256(normalized["recording_sha256"], "recording_sha256")
    if normalized["execution_authorized"] is not False:
        raise _blocked("ppux-authority-invalid", "reviewed tutorial cannot authorize execution")
    if type(normalized["retained_steps"]) is not list or not normalized["retained_steps"]:
        raise _blocked("ppux-tutorial-invalid", "reviewed tutorial must retain at least one step")

    seen: set[str] = set()
    for step in normalized["retained_steps"]:
        if type(step) is not dict:
            raise _blocked("ppux-tutorial-invalid", "retained step must be a mapping")
        review_id = validate_stable_id(step.get("review_step_id"), "review_step_id")
        if review_id in seen:
            raise _blocked("ppux-step-duplicate", "reviewed tutorial contains duplicate retained step identity")
        seen.add(review_id)
        if step.get("recording_id") != normalized["recording_id"] or step.get("recording_sha256") != normalized["recording_sha256"]:
            raise _blocked("ppux-tutorial-identity-mismatch", "retained step belongs to another recording")
        if step.get("execution_authorized") is not False:
            raise _blocked("ppux-authority-invalid", "retained step cannot authorize execution")
        source_ids = step.get("source_step_ids")
        if type(source_ids) is not list or not source_ids:
            raise _blocked("ppux-step-provenance-missing", "retained step is missing Teacher Modeling source identity")
        for source_id in source_ids:
            validate_stable_id(source_id, "source_step_id")
    return normalized


def _routed_steps(
    value: object,
    *,
    tutorial: dict[str, Any],
    visual_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    normalized = validate_and_normalize_json(value, max_bytes=MAX_INPUT_BYTES)
    if type(normalized) is not list:
        raise _blocked("ppux-route-invalid", "routed_steps must be a built-in list")

    retained = {step["review_step_id"] for step in tutorial["retained_steps"]}
    role_ids = {
        role["role_id"]
        for role in visual_payload["required_roles"] + visual_payload["optional_roles"]
    }
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for raw in normalized:
        if type(raw) is not dict:
            raise _blocked("ppux-route-invalid", "routed step must be a mapping")
        allowed = {"reviewStepId", "visualRoleRef", "disposition"} | _STEP_OPTIONAL
        if not {"reviewStepId", "visualRoleRef", "disposition"}.issubset(raw) or set(raw) - allowed:
            raise _blocked("ppux-route-invalid", "routed step fields do not match RoutedTutorialStep")
        review_id = validate_stable_id(raw["reviewStepId"], "reviewStepId")
        if review_id not in retained:
            raise _blocked("ppux-step-unmatched", "routed step does not match a retained reviewed step")
        if review_id in seen:
            raise _blocked("ppux-step-duplicate", "routed step identity is duplicated")
        seen.add(review_id)

        visual_role = validate_stable_id(raw["visualRoleRef"], "visualRoleRef")
        if visual_role not in role_ids:
            raise _blocked("ppux-visual-role-mismatch", "routed step references a visual role not owned by the visual-needs plan")

        disposition = validate_text(raw["disposition"], "disposition", max_length=64)
        if disposition not in _ALLOWED_DISPOSITIONS:
            raise _blocked("ppux-route-invalid", "unsupported tutorial fulfillment disposition")
        _validate_disposition(raw, disposition)
        if "authoring" in raw:
            _validate_authoring(raw["authoring"])
        result.append(raw)

    if seen != retained:
        raise _blocked("ppux-step-unmatched", "every retained reviewed step requires exactly one routed disposition")
    return result


def _validate_disposition(step: dict[str, Any], disposition: str) -> None:
    if disposition == "new-visual" and "authoring" not in step:
        raise _blocked("ppux-authoring-missing", "new-visual disposition requires existing PromptAuthoringInput evidence")
    if disposition in {"reuse-existing-visual", "resurface-prior-visual"}:
        if not step.get("approvedAssetRef"):
            raise _blocked("ppux-asset-reference-missing", "reuse/resurface disposition requires an approved asset reference")
    if disposition in {"no-additional-visual-needed", "pathway-compacted"}:
        if not step.get("reasonRef"):
            raise _blocked("ppux-reason-reference-missing", "non-visual disposition requires reason evidence")


def _validate_authoring(value: object) -> None:
    if type(value) is not dict:
        raise _blocked("ppux-authoring-invalid", "authoring must be a built-in mapping")
    if not _AUTHORING_REQUIRED.issubset(value) or set(value) - (_AUTHORING_REQUIRED | _AUTHORING_OPTIONAL):
        raise _blocked("ppux-authoring-invalid", "authoring fields do not match PromptAuthoringInput")
    for field_name in ("imagePurpose", "applicationContext", "targetState", "annotationSpace"):
        validate_text(value[field_name], field_name)
    if value["imageState"] not in {"action", "result", "action+result"}:
        raise _blocked("ppux-authoring-invalid", "imageState is unsupported")
    for field_name in ("mustShow", "mustNotShow", "requestedUiDetails"):
        items = value[field_name]
        if type(items) is not list:
            raise _blocked("ppux-authoring-invalid", f"{field_name} must be a list")
        for item in items:
            validate_text(item, field_name)
    if not value["mustShow"]:
        raise _blocked("ppux-authoring-invalid", "mustShow cannot be empty")
    if "screenFidelityRequired" in value and value["screenFidelityRequired"] is not True:
        raise _blocked("ppux-authoring-invalid", "screenFidelityRequired may only be true when supplied")
