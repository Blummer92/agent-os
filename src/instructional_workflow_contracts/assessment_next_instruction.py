"""Governed assessment-evidence -> next-instruction analysis contract.

Issue: #1891 (ANI1).  This module turns a bounded, teacher-reviewed,
class-level assessment evidence summary into a versioned, provider-neutral
analysis record.  Observed evidence, inferred hypotheses, and bounded
instructional options are kept structurally separate; inferred content can
never overwrite a teacher decision, and every consequential option carries
an explicit teacher-decision requirement.

The contract is pure-local, deterministic, and fail-closed:

- no I/O, no timestamps, no randomness, no learner-level data;
- intake is admitted only with ``review_state == "reviewed"``;
- observations are class-scoped only (``scope == "class"``);
- hypotheses may never claim stronger evidence than their supporting
  observations and must state their limitations;
- instructional options bind only to supplied targets/rubric dimensions and
  may never rest on insufficient-strength hypotheses;
- missing, conflicting, or insufficient evidence routes to an explicit
  ``insufficient-evidence`` hold instead of a confident recommendation;
- all execution, grading, readiness, production, publication, and external
  write authority is permanently false.
"""

from __future__ import annotations

import hashlib
from typing import Any

from .common import (
    MAX_INPUT_BYTES,
    ContractValidationError,
    FrozenObject,
    ValidatedRecord,
    ValidationResult,
    ValidationStatus,
    canonical_json_bytes,
    freeze_json,
    validate_and_normalize_json,
    validate_bounded_list,
    validate_exact_fields,
    validate_mapping,
    validate_reason_code,
    validate_revision,
    validate_stable_id,
    validate_text,
    validate_version,
)

CONTRACT_ID = "assessment-next-instruction-v1"

# Bounded evidence sources admitted by this contract.  ``teacher-class-summary``
# is a teacher-entered class-level summary; ``normalized-evidence-intake`` is
# the EIA1-shaped normalized intake route shared with the LP pacing handoff.
EVIDENCE_SOURCES = frozenset({"teacher-class-summary", "normalized-evidence-intake"})

# Evidence kinds for a single class-level observation.
EVIDENCE_KINDS = frozenset({"direct", "context", "partial", "uncertain"})

# Evidence strength ladder, weakest to strongest.
STRENGTH_ORDER = ("insufficient", "weak", "moderate", "strong")
STRENGTH_RANK = {name: rank for rank, name in enumerate(STRENGTH_ORDER)}

# Hypothesis kinds are always labeled as hypotheses, never judgments.
HYPOTHESIS_KINDS = frozenset(
    {"misconception", "prerequisite-gap", "strategy-opportunity"}
)

# Bounded instructional-option kinds.  ``manual-review`` options carry no
# instructional content; they route the record to explicit human review.
OPTION_KINDS = frozenset(
    {
        "reteach-bounded",
        "modeling-revisit",
        "practice-redesign",
        "materials-revision",
        "pacing-adjustment",
        "sequence-change",
        "manual-review",
    }
)

# Deterministic option-kind -> existing owner routing.  No new agent is
# introduced by this contract; continuation routes to existing owners.
_OPTION_OWNER = {
    "reteach-bounded": "teacher-modeling-coach",
    "modeling-revisit": "teacher-modeling-coach",
    "practice-redesign": "instructional-materials-coach",
    "materials-revision": "instructional-materials-coach",
    "pacing-adjustment": "unit-alignment-agent",
    "sequence-change": "unit-alignment-agent",
    "manual-review": "manual-review",
}

MAX_TARGETS = 32
MAX_OBSERVATIONS = 64
MAX_HYPOTHESES = 32
MAX_OPTIONS = 16

_INPUT_FIELDS = frozenset(
    {
        "contract_version",
        "analysis_id",
        "record_revision",
        "evidence_source",
        "review_state",
        "privacy_disposition",
        "blueprint_identity",
        "targets",
        "observations",
        "hypotheses",
        "options",
    }
)
_BLUEPRINT_FIELDS = frozenset({"blueprint_id", "blueprint_version"})
_TARGET_FIELDS = frozenset({"target_ref", "label"})
_OBSERVATION_FIELDS = frozenset(
    {
        "observation_id",
        "bound_target_ref",
        "scope",
        "evidence_kind",
        "strength",
        "observed",
    }
)
_HYPOTHESIS_FIELDS = frozenset(
    {
        "hypothesis_id",
        "kind",
        "bound_target_ref",
        "supporting_observation_ids",
        "evidence_strength",
        "limitations",
    }
)
_OPTION_FIELDS = frozenset(
    {
        "option_id",
        "kind",
        "bound_target_refs",
        "supporting_hypothesis_ids",
        "consequential",
        "description",
    }
)


def _invalid(reason: str, detail: str) -> ValidationResult:
    validate_reason_code(reason)
    return ValidationResult(
        status=ValidationStatus.INVALID,
        record=None,
        reason_codes=(reason,),
        details=(detail,),
    )


def _require_enum(value: object, allowed: frozenset[str], name: str) -> str:
    text = validate_text(value, name, max_length=64)
    if text not in allowed:
        raise ContractValidationError(
            "source-invalid", f"{name} is outside the admitted set"
        )
    return text


def _validate_targets(raw: object) -> list[dict[str, Any]]:
    items = validate_bounded_list(raw, "targets", MAX_TARGETS)
    if not items:
        raise ContractValidationError(
            "handoff-invalid", "targets must name at least one target or rubric dimension"
        )
    seen: set[str] = set()
    validated: list[dict[str, Any]] = []
    for item in items:
        mapping = validate_mapping(item, "target")
        validate_exact_fields(mapping, _TARGET_FIELDS, "target")
        target_ref = validate_stable_id(mapping["target_ref"], "target_ref")
        if target_ref in seen:
            raise ContractValidationError("identity-invalid", "duplicate target_ref")
        seen.add(target_ref)
        validated.append(
            {
                "target_ref": target_ref,
                "label": validate_text(mapping["label"], "target label"),
            }
        )
    return validated


def _validate_blueprint(raw: object) -> dict[str, str]:
    mapping = validate_mapping(raw, "blueprint_identity")
    validate_exact_fields(mapping, _BLUEPRINT_FIELDS, "blueprint_identity")
    return {
        "blueprint_id": validate_stable_id(mapping["blueprint_id"], "blueprint_id"),
        "blueprint_version": validate_version(mapping["blueprint_version"]),
    }


def _validate_observations(
    raw: object, target_refs: frozenset[str]
) -> list[dict[str, Any]]:
    items = validate_bounded_list(raw, "observations", MAX_OBSERVATIONS)
    seen: set[str] = set()
    validated: list[dict[str, Any]] = []
    for item in items:
        mapping = validate_mapping(item, "observation")
        validate_exact_fields(mapping, _OBSERVATION_FIELDS, "observation")
        observation_id = validate_stable_id(mapping["observation_id"], "observation_id")
        if observation_id in seen:
            raise ContractValidationError("identity-invalid", "duplicate observation_id")
        seen.add(observation_id)
        bound = validate_stable_id(mapping["bound_target_ref"], "bound_target_ref")
        if bound not in target_refs:
            raise ContractValidationError(
                "source-invalid", "observation binds to an unknown target_ref"
            )
        scope = _require_enum(mapping["scope"], frozenset({"class"}), "scope")
        kind = _require_enum(mapping["evidence_kind"], EVIDENCE_KINDS, "evidence_kind")
        strength = _require_enum(
            mapping["strength"], frozenset(STRENGTH_ORDER), "strength"
        )
        if kind == "uncertain" and strength != "insufficient":
            raise ContractValidationError(
                "quality-invalid",
                "uncertain evidence cannot carry stronger than insufficient strength",
            )
        validated.append(
            {
                "observation_id": observation_id,
                "bound_target_ref": bound,
                "scope": scope,
                "evidence_kind": kind,
                "strength": strength,
                "observed": validate_text(mapping["observed"], "observed evidence"),
            }
        )
    return validated


def _validate_hypotheses(
    raw: object,
    target_refs: frozenset[str],
    observation_strength: dict[str, str],
) -> list[dict[str, Any]]:
    items = validate_bounded_list(raw, "hypotheses", MAX_HYPOTHESES)
    seen: set[str] = set()
    validated: list[dict[str, Any]] = []
    for item in items:
        mapping = validate_mapping(item, "hypothesis")
        validate_exact_fields(mapping, _HYPOTHESIS_FIELDS, "hypothesis")
        hypothesis_id = validate_stable_id(mapping["hypothesis_id"], "hypothesis_id")
        if hypothesis_id in seen:
            raise ContractValidationError("identity-invalid", "duplicate hypothesis_id")
        seen.add(hypothesis_id)
        kind = _require_enum(mapping["kind"], HYPOTHESIS_KINDS, "hypothesis kind")
        bound = validate_stable_id(mapping["bound_target_ref"], "bound_target_ref")
        if bound not in target_refs:
            raise ContractValidationError(
                "source-invalid", "hypothesis binds to an unknown target_ref"
            )
        supporting = validate_bounded_list(
            mapping["supporting_observation_ids"],
            "supporting_observation_ids",
            MAX_OBSERVATIONS,
        )
        if not supporting:
            raise ContractValidationError(
                "handoff-invalid", "hypothesis requires supporting observations"
            )
        supporting_ids: list[str] = []
        for identifier in supporting:
            stable = validate_stable_id(identifier, "supporting observation id")
            if stable not in observation_strength:
                raise ContractValidationError(
                    "source-invalid", "hypothesis references an unknown observation"
                )
            supporting_ids.append(stable)
        strength = _require_enum(
            mapping["evidence_strength"], frozenset(STRENGTH_ORDER), "evidence_strength"
        )
        weakest_support = min(
            STRENGTH_RANK[observation_strength[identifier]]
            for identifier in supporting_ids
        )
        if STRENGTH_RANK[strength] > weakest_support:
            raise ContractValidationError(
                "quality-invalid",
                "hypothesis evidence strength exceeds its supporting observations",
            )
        limitations = validate_text(mapping["limitations"], "hypothesis limitations")
        if not limitations.strip():
            raise ContractValidationError(
                "quality-invalid", "hypothesis must state its limitations"
            )
        validated.append(
            {
                "hypothesis_id": hypothesis_id,
                "kind": kind,
                "bound_target_ref": bound,
                "supporting_observation_ids": sorted(supporting_ids),
                "evidence_strength": strength,
                "limitations": limitations,
            }
        )
    return validated


def _validate_options(
    raw: object,
    target_refs: frozenset[str],
    hypothesis_strength: dict[str, str],
) -> list[dict[str, Any]]:
    items = validate_bounded_list(raw, "options", MAX_OPTIONS)
    seen: set[str] = set()
    validated: list[dict[str, Any]] = []
    for item in items:
        mapping = validate_mapping(item, "instructional option")
        validate_exact_fields(mapping, _OPTION_FIELDS, "instructional option")
        option_id = validate_stable_id(mapping["option_id"], "option_id")
        if option_id in seen:
            raise ContractValidationError("identity-invalid", "duplicate option_id")
        seen.add(option_id)
        kind = _require_enum(mapping["kind"], OPTION_KINDS, "option kind")
        bound_refs = validate_bounded_list(
            mapping["bound_target_refs"], "bound_target_refs", MAX_TARGETS
        )
        if not bound_refs:
            raise ContractValidationError(
                "handoff-invalid", "option requires at least one bound target"
            )
        normalized_refs: list[str] = []
        for ref in bound_refs:
            stable = validate_stable_id(ref, "bound target ref")
            if stable not in target_refs:
                raise ContractValidationError(
                    "source-invalid", "option binds to an unknown target_ref"
                )
            normalized_refs.append(stable)
        supporting = validate_bounded_list(
            mapping["supporting_hypothesis_ids"],
            "supporting_hypothesis_ids",
            MAX_HYPOTHESES,
        )
        if not supporting:
            raise ContractValidationError(
                "handoff-invalid", "option requires supporting hypotheses"
            )
        supporting_ids: list[str] = []
        for identifier in supporting:
            stable = validate_stable_id(identifier, "supporting hypothesis id")
            if stable not in hypothesis_strength:
                raise ContractValidationError(
                    "source-invalid", "option references an unknown hypothesis"
                )
            if hypothesis_strength[stable] == "insufficient":
                raise ContractValidationError(
                    "quality-invalid",
                    "option cannot rest on an insufficient-strength hypothesis",
                )
            supporting_ids.append(stable)
        consequential = mapping["consequential"]
        if type(consequential) is not bool:
            raise ContractValidationError(
                "handoff-wrong-type", "option consequential must be a boolean"
            )
        validated.append(
            {
                "option_id": option_id,
                "kind": kind,
                "bound_target_refs": sorted(normalized_refs),
                "supporting_hypothesis_ids": sorted(supporting_ids),
                "consequential": consequential,
                # Consequential choices always require an explicit teacher
                # decision; the advisory record never makes them.
                "teacher_decision_required": consequential,
                "description": validate_text(mapping["description"], "option description"),
            }
        )
    return validated


def _route_owner(options: list[dict[str, Any]]) -> str:
    owners = [_OPTION_OWNER[option["kind"]] for option in options]
    if "manual-review" in owners:
        return "manual-review"
    counts: dict[str, int] = {}
    for owner in owners:
        counts[owner] = counts.get(owner, 0) + 1
    # Deterministic: highest count wins, ties break alphabetically.
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _build_record(
    *,
    analysis_id: str,
    record_revision: int,
    evidence_source: str,
    blueprint: dict[str, str],
    targets: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    hypotheses: list[dict[str, Any]],
    options: list[dict[str, Any]],
    classification: str,
    routing: str,
    manual_review_required: bool,
    unresolved_uncertainties: tuple[str, ...],
) -> ValidatedRecord:
    payload = {
        "contract_version": CONTRACT_ID,
        "analysis_id": analysis_id,
        "record_revision": record_revision,
        "evidence_source": evidence_source,
        "blueprint_identity": blueprint,
        "targets": targets,
        # Observed evidence and inferred hypotheses are structurally separate.
        "observed_evidence": observations,
        "inference_hypotheses": hypotheses,
        # Bounded instructional options; teacher decisions are stored by the
        # teacher-facing surface, never overwritten by this record.
        "instructional_options": options,
        "recommended_next_owner": _route_owner(options) if routing != "hold" else "manual-review",
        "teacher_decision_required": any(
            option["teacher_decision_required"] for option in options
        ),
        "manual_review_required": manual_review_required,
        "classification": classification,
        "routing": routing,
        "unresolved_uncertainties": list(unresolved_uncertainties),
        "authority": {
            "analysis_authorized": False,
            "execution_authorized": False,
            "grading_authorized": False,
            "readiness_authorized": False,
            "production_authorized": False,
            "publication_authorized": False,
            "external_write_authorized": False,
        },
    }
    frozen = freeze_json(payload)
    if type(frozen) is not FrozenObject:  # pragma: no cover - defensive
        raise ContractValidationError("handoff-invalid", "record payload is not an object")
    # The fingerprint binds the exact canonical payload bytes.
    fingerprint = hashlib.sha256(canonical_json_bytes(frozen)).hexdigest()
    return ValidatedRecord(
        contract_version=CONTRACT_ID,
        record_id=analysis_id,
        record_revision=record_revision,
        fingerprint_algorithm="sha256",
        fingerprint=fingerprint,
        payload=frozen,
    )


def _hold_result(
    *,
    analysis_id: str,
    record_revision: int,
    evidence_source: str,
    blueprint: dict[str, str],
    targets: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    hypotheses: list[dict[str, Any]],
    reason_code: str,
    uncertainties: tuple[str, ...],
) -> ValidationResult:
    validate_reason_code(reason_code)
    record = _build_record(
        analysis_id=analysis_id,
        record_revision=record_revision,
        evidence_source=evidence_source,
        blueprint=blueprint,
        targets=targets,
        observations=observations,
        hypotheses=hypotheses,
        options=[],
        classification="insufficient-evidence",
        routing="hold",
        manual_review_required=True,
        unresolved_uncertainties=uncertainties,
    )
    return ValidationResult(
        status=ValidationStatus.MANUAL_REVIEW_REQUIRED,
        record=record,
        reason_codes=(reason_code,),
        details=("assessment evidence is insufficient for next-instruction options",),
    )


def analyze_assessment_next_instruction(evidence: object) -> ValidationResult:
    """Validate and assemble an assessment -> next-instruction analysis record.

    Returns ``VALID`` with a versioned analysis record, ``MANUAL_REVIEW_REQUIRED``
    with an explicit insufficient-evidence hold record, or ``INVALID`` when the
    intake violates the contract.  The function is pure-local and deterministic.
    """
    try:
        normalized = validate_and_normalize_json(evidence, max_bytes=MAX_INPUT_BYTES)
    except (ContractValidationError, ValueError) as exc:
        return _invalid("handoff-oversized", str(exc))
    if type(normalized) is not dict:
        return _invalid("handoff-wrong-type", "evidence must be a JSON object")
    try:
        validate_exact_fields(normalized, _INPUT_FIELDS, "assessment evidence")
        contract_version = validate_version(normalized["contract_version"])
        if contract_version != CONTRACT_ID:
            raise ContractValidationError(
                "handoff-version-unsupported",
                "contract_version is not a supported assessment-next-instruction contract",
            )
        analysis_id = validate_stable_id(normalized["analysis_id"], "analysis_id")
        record_revision = validate_revision(normalized["record_revision"])
        evidence_source = _require_enum(
            normalized["evidence_source"], EVIDENCE_SOURCES, "evidence_source"
        )
        review_state = validate_text(normalized["review_state"], "review_state")
        if review_state != "reviewed":
            raise ContractValidationError(
                "source-invalid",
                "evidence is admitted only with an explicit teacher review state",
            )
        blueprint = _validate_blueprint(normalized["blueprint_identity"])
        targets = _validate_targets(normalized["targets"])
        target_refs = frozenset(target["target_ref"] for target in targets)
        observations = _validate_observations(normalized["observations"], target_refs)
        observation_strength = {
            item["observation_id"]: item["strength"] for item in observations
        }
        hypotheses = _validate_hypotheses(
            normalized["hypotheses"], target_refs, observation_strength
        )
        hypothesis_strength = {
            item["hypothesis_id"]: item["evidence_strength"] for item in hypotheses
        }
        options = _validate_options(normalized["options"], target_refs, hypothesis_strength)

        privacy_disposition = validate_text(
            normalized["privacy_disposition"], "privacy_disposition"
        )
        if privacy_disposition != "eligible":
            return _hold_result(
                analysis_id=analysis_id,
                record_revision=record_revision,
                evidence_source=evidence_source,
                blueprint=blueprint,
                targets=targets,
                observations=observations,
                hypotheses=hypotheses,
                reason_code="manual-review-privacy-ineligible",
                uncertainties=("manual-review-privacy-ineligible",),
            )

        if not observations or all(
            item["strength"] == "insufficient" for item in observations
        ):
            if options:
                raise ContractValidationError(
                    "handoff-invalid",
                    "insufficient evidence admits no instructional options",
                )
            return _hold_result(
                analysis_id=analysis_id,
                record_revision=record_revision,
                evidence_source=evidence_source,
                blueprint=blueprint,
                targets=targets,
                observations=observations,
                hypotheses=hypotheses,
                reason_code="manual-review-insufficient-evidence",
                uncertainties=("manual-review-insufficient-evidence",),
            )

        uncertainties: list[str] = []
        if any(item["strength"] in ("weak", "insufficient") for item in observations):
            uncertainties.append("manual-review-weak-evidence-present")
        if any(item["evidence_kind"] == "uncertain" for item in observations):
            uncertainties.append("manual-review-uncertain-evidence-excluded")
        for uncertainty in uncertainties:
            validate_reason_code(uncertainty)

        record = _build_record(
            analysis_id=analysis_id,
            record_revision=record_revision,
            evidence_source=evidence_source,
            blueprint=blueprint,
            targets=targets,
            observations=observations,
            hypotheses=hypotheses,
            options=options,
            classification="sufficient-evidence",
            routing="proceed-to-owner-review",
            manual_review_required=bool(uncertainties),
            unresolved_uncertainties=tuple(uncertainties),
        )
        return ValidationResult(status=ValidationStatus.VALID, record=record)
    except ContractValidationError as exc:
        return _invalid(exc.reason_code, exc.detail)


__all__ = [
    "CONTRACT_ID",
    "EVIDENCE_SOURCES",
    "analyze_assessment_next_instruction",
]
