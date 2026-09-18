"""Pure bounded request-interpretation contract for Issue #924."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .common import (
    FINGERPRINT_ALGORITHM,
    MAX_INPUT_BYTES,
    AuthorityEvidence,
    ContractReference,
    ContractValidationError,
    ValidatedRecord,
    ValidationResult,
    ValidationStatus,
    freeze_json,
    is_secret_like_key,
    sha256_hex,
    validate_and_normalize_json,
    validate_bounded_list,
    validate_exact_fields,
    validate_mapping,
    validate_revision,
    validate_stable_id,
    validate_text,
    validate_timestamp,
    validate_version,
)

SCHEMA_NAME = "request-interpretation"
CONTRACT_VERSION = "request-interpretation-v1"
MAX_OUTPUTS = 8
MAX_CONSTRAINTS = 16
MAX_REFERENCES = 16

ACTIONS = frozenset({"inspect", "plan", "implement", "review", "generate", "unknown"})
EFFECTS = frozenset({"read", "propose", "mutate", "schedule"})
CONTINUATIONS = frozenset({"new", "continue"})
ORIGINS = frozenset({"direct-user", "retrieved-content", "system", "approved-handoff"})
SYSTEMS = frozenset({"github", "notion", "google-drive", "google-docs", "google-slides", "google-sheets", "unknown"})
RESOURCE_KINDS = frozenset({"repository", "issue", "pull-request", "unknown"})
REASON_CODES = frozenset({
    "action.ambiguous", "action.invalid", "action.unsupported", "target.missing", "target.multiple",
    "target.repository-missing", "target.issue-invalid", "target.pull-request-invalid", "context.missing",
    "context.stale", "context.multiple-candidates", "request.untrusted-source",
    "request.conflicting-constraints", "request.write-surface-unclear", "request.destination-unclear",
    "request.monitoring-surface-required",
})

TOP_LEVEL_FIELDS = frozenset({
    "schema_name", "contract_version", "record_revision", "observed_at", "interpreter_id",
    "raw_input_digest", "instruction_origin", "action", "requested_effect", "continuation_mode",
    "target", "requested_outputs", "constraints", "reason_codes", "evidence_references",
})
TARGET_FIELDS = frozenset({"system", "resource_kind", "repository", "resource_id"})
REFERENCE_FIELDS = frozenset({"system", "stable_id", "exact_location", "verification_evidence"})
CONSTRAINT_FIELDS = frozenset({"name", "value"})

PPUX_AUTHORITY_CONSTRAINT = "ppux-authority"
PPUX_TUTORIAL_CONSTRAINT = "ppux-tutorial-id"
PPUX_RESULT_STATE_CONSTRAINT = "ppux-result-state"
PPUX_PROVENANCE_CHANGE_CONSTRAINT = "ppux-provenance-change"

PPUX_RESULT_STATES = frozenset({
    "pending", "ready", "blocked", "source-unresolved", "execution-unavailable", "manual-review",
})
PPUX_FAIL_CLOSED_STATES = frozenset({
    "pending", "blocked", "source-unresolved", "execution-unavailable", "manual-review",
})


@dataclass(frozen=True, slots=True)
class RequestInterpretation:
    record: ValidatedRecord
    side_effects_performed: Literal[False] = field(default=False, init=False)
    authorization_created: Literal[False] = field(default=False, init=False)
    authority: AuthorityEvidence = field(default_factory=AuthorityEvidence, init=False)


@dataclass(frozen=True, slots=True)
class PpuxMissionConstraintDecision:
    """Non-authorizing continuation decision for runner-authoritative PPUX missions."""

    runner_authoritative: bool
    tutorial_id: str | None
    result_state: str | None
    manual_alternative_requested: bool
    generic_prompt_authoring_allowed: bool
    requires_fresh_tutorial_resolution: bool
    side_effects_performed: Literal[False] = field(default=False, init=False)
    authorization_created: Literal[False] = field(default=False, init=False)
    authority: AuthorityEvidence = field(default_factory=AuthorityEvidence, init=False)


def _choice(value: Any, allowed: frozenset[str], name: str) -> str:
    text = validate_text(value, name, max_length=64)
    if text not in allowed:
        raise ContractValidationError("handoff-invalid", f"{name} is unsupported")
    return text


def _optional_stable_id(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return validate_stable_id(value, name)


def _reference(value: Any) -> ContractReference:
    ref = validate_mapping(value, "evidence reference")
    validate_exact_fields(ref, REFERENCE_FIELDS, "evidence reference")
    return ContractReference(
        system=ref["system"], stable_id=ref["stable_id"], exact_location=ref["exact_location"],
        verification_evidence=ref["verification_evidence"],
    )


def _target(value: Any) -> dict[str, Any]:
    target = validate_mapping(value, "target")
    validate_exact_fields(target, TARGET_FIELDS, "target")
    system = _choice(target["system"], SYSTEMS, "target.system")
    resource_kind = _choice(target["resource_kind"], RESOURCE_KINDS, "target.resource_kind")
    repository = _optional_stable_id(target["repository"], "target.repository")
    resource_id = _optional_stable_id(target["resource_id"], "target.resource_id")
    return {"system": system, "resource_kind": resource_kind, "repository": repository, "resource_id": resource_id}


def _constraints(values: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in validate_bounded_list(values, "constraints", MAX_CONSTRAINTS):
        item = validate_mapping(raw, "constraint")
        validate_exact_fields(item, CONSTRAINT_FIELDS, "constraint")
        name = validate_stable_id(item["name"], "constraint.name")
        if is_secret_like_key(name):
            raise ContractValidationError("authority-secret-field", "constraint.name is secret-like")
        if name in seen:
            raise ContractValidationError("handoff-duplicate", "constraint names must be unique")
        seen.add(name)
        value = item["value"]
        if type(value) not in (str, int, bool) and value is not None:
            raise ContractValidationError("handoff-wrong-type", "constraint.value must be scalar")
        if type(value) is str:
            value = validate_text(value, "constraint.value")
        normalized.append({"name": name, "value": value})
    return sorted(normalized, key=lambda item: item["name"])


def _semantic_reasons(origin: str, action: str, effect: str, continuation: str, target: dict[str, Any]) -> set[str]:
    reasons: set[str] = set()
    if origin == "retrieved-content":
        reasons.add("request.untrusted-source")
    if action == "unknown":
        reasons.add("action.ambiguous")
    if target["system"] == "unknown":
        reasons.add("request.destination-unclear")
    if target["resource_kind"] == "unknown":
        reasons.add("target.missing")
    if target["system"] == "github" and target["repository"] is None:
        reasons.add("target.repository-missing")
    if target["resource_kind"] in {"issue", "pull-request"} and target["resource_id"] is None:
        reasons.add("target.missing")
    if continuation == "continue" and target["resource_id"] is None:
        reasons.add("context.missing")
    if effect == "mutate" and origin not in {"direct-user", "approved-handoff"}:
        reasons.add("request.write-surface-unclear")
    if effect == "schedule":
        reasons.add("request.monitoring-surface-required")
    return reasons


def validate_request_interpretation(value: object) -> ValidationResult:
    try:
        normalized = validate_and_normalize_json(value, max_bytes=MAX_INPUT_BYTES)
        payload = validate_mapping(normalized, "request interpretation")
        validate_exact_fields(payload, TOP_LEVEL_FIELDS, "request interpretation")
        if validate_text(payload["schema_name"], "schema_name", max_length=64) != SCHEMA_NAME:
            raise ContractValidationError("handoff-invalid", "schema_name is unsupported")
        if validate_version(payload["contract_version"]) != CONTRACT_VERSION:
            raise ContractValidationError("handoff-version-unsupported", "contract_version is unsupported")
        revision = validate_revision(payload["record_revision"])
        observed_at = validate_timestamp(payload["observed_at"], "observed_at")
        interpreter_id = validate_stable_id(payload["interpreter_id"], "interpreter_id")
        raw_input_digest = validate_text(payload["raw_input_digest"], "raw_input_digest", max_length=64)
        if len(raw_input_digest) != 64 or any(ch not in "0123456789abcdef" for ch in raw_input_digest):
            raise ContractValidationError("handoff-invalid", "raw_input_digest must be lowercase SHA-256 hex")
        origin = _choice(payload["instruction_origin"], ORIGINS, "instruction_origin")
        action = _choice(payload["action"], ACTIONS, "action")
        effect = _choice(payload["requested_effect"], EFFECTS, "requested_effect")
        continuation = _choice(payload["continuation_mode"], CONTINUATIONS, "continuation_mode")
        target = _target(payload["target"])
        outputs = sorted({validate_stable_id(item, "requested_output") for item in validate_bounded_list(payload["requested_outputs"], "requested_outputs", MAX_OUTPUTS)})
        constraints = _constraints(payload["constraints"])
        supplied_reasons = {validate_text(item, "reason_code", max_length=128) for item in validate_bounded_list(payload["reason_codes"], "reason_codes", len(REASON_CODES))}
        if not supplied_reasons <= REASON_CODES:
            raise ContractValidationError("handoff-invalid", "reason_codes contain an unknown governed code")
        references = [_reference(item) for item in validate_bounded_list(payload["evidence_references"], "evidence_references", MAX_REFERENCES)]
        reasons = tuple(sorted(supplied_reasons | _semantic_reasons(origin, action, effect, continuation, target)))
        record_payload = {
            "schema_name": SCHEMA_NAME, "contract_version": CONTRACT_VERSION, "record_revision": revision,
            "observed_at": observed_at, "interpreter_id": interpreter_id, "raw_input_digest": raw_input_digest,
            "instruction_origin": origin, "action": action, "requested_effect": effect,
            "continuation_mode": continuation, "target": target, "requested_outputs": outputs,
            "constraints": constraints, "reason_codes": list(reasons),
            "evidence_references": [
                {"system": ref.system, "stable_id": ref.stable_id, "exact_location": ref.exact_location, "verification_evidence": ref.verification_evidence}
                for ref in references
            ],
            "side_effects_performed": False, "authorization_created": False,
        }
        fingerprint = sha256_hex(record_payload)
        record = ValidatedRecord(
            contract_version=CONTRACT_VERSION, record_id=f"request-{fingerprint[:24]}", record_revision=revision,
            fingerprint_algorithm=FINGERPRINT_ALGORITHM, fingerprint=fingerprint, payload=freeze_json(record_payload),
        )
        if reasons:
            return ValidationResult(status=ValidationStatus.MANUAL_REVIEW_REQUIRED, record=record, details=reasons)
        return ValidationResult(status=ValidationStatus.VALID, record=record)
    except ContractValidationError as exc:
        return ValidationResult(status=ValidationStatus.INVALID, record=None, reason_codes=(exc.reason_code,), details=(exc.detail,))


def _constraint_map(interpretation: RequestInterpretation | None) -> dict[str, object]:
    if interpretation is None:
        return {}
    if type(interpretation) is not RequestInterpretation:
        raise TypeError("interpretation must be an exact RequestInterpretation or None")
    constraints = interpretation.record.to_dict().get("constraints", [])
    return {item["name"]: item["value"] for item in constraints}


def evaluate_ppux_mission_constraint(
    previous: RequestInterpretation | None,
    current: RequestInterpretation,
) -> PpuxMissionConstraintDecision:
    """Preserve runner PPUX provenance across a bounded continuation.

    The function consumes only validated structured request constraints. It never
    parses conversational phrases, invokes a provider, or creates authority.
    """
    if type(current) is not RequestInterpretation:
        raise TypeError("current must be an exact RequestInterpretation")

    current_payload = current.record.to_dict()
    current_constraints = _constraint_map(current)
    previous_constraints = _constraint_map(previous)

    current_tutorial = current_constraints.get(PPUX_TUTORIAL_CONSTRAINT)
    previous_tutorial = previous_constraints.get(PPUX_TUTORIAL_CONSTRAINT)
    if current_tutorial is not None and type(current_tutorial) is not str:
        raise ValueError("ppux-tutorial-id must be text")
    if previous_tutorial is not None and type(previous_tutorial) is not str:
        raise ValueError("previous ppux-tutorial-id must be text")

    provenance_change = current_constraints.get(PPUX_PROVENANCE_CHANGE_CONSTRAINT)
    if provenance_change not in (None, "manual"):
        raise ValueError("ppux-provenance-change must be manual when supplied")
    manual_requested = provenance_change == "manual"

    current_authority = current_constraints.get(PPUX_AUTHORITY_CONSTRAINT)
    previous_authority = previous_constraints.get(PPUX_AUTHORITY_CONSTRAINT)
    if current_authority not in (None, "runner"):
        raise ValueError("ppux-authority must be runner when supplied")
    if previous_authority not in (None, "runner"):
        raise ValueError("previous ppux-authority must be runner when supplied")

    result_state = current_constraints.get(PPUX_RESULT_STATE_CONSTRAINT)
    if result_state is None and current_payload["continuation_mode"] == "continue":
        result_state = previous_constraints.get(PPUX_RESULT_STATE_CONSTRAINT)
    if result_state is not None and result_state not in PPUX_RESULT_STATES:
        raise ValueError("ppux-result-state is unsupported")

    tutorial_changed = (
        previous_tutorial is not None
        and current_tutorial is not None
        and previous_tutorial != current_tutorial
    )
    runner_authoritative = (
        not manual_requested
        and not tutorial_changed
        and (
            current_authority == "runner"
            or (
                current_payload["continuation_mode"] == "continue"
                and previous_authority == "runner"
            )
        )
    )
    tutorial_id = current_tutorial if current_tutorial is not None else previous_tutorial
    if tutorial_changed:
        result_state = None

    generic_allowed = manual_requested or not runner_authoritative
    if runner_authoritative and result_state in PPUX_FAIL_CLOSED_STATES:
        generic_allowed = False
    if runner_authoritative and result_state == "ready":
        generic_allowed = False

    return PpuxMissionConstraintDecision(
        runner_authoritative=runner_authoritative,
        tutorial_id=tutorial_id,
        result_state=result_state,
        manual_alternative_requested=manual_requested,
        generic_prompt_authoring_allowed=generic_allowed,
        requires_fresh_tutorial_resolution=tutorial_changed,
    )
