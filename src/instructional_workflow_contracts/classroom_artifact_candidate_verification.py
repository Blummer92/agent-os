"""Pure classroom-artifact candidate identity verification for Issue #3024.

A Drive title (or topic/content) match is evidence of a candidate file, never
evidence that the file is the current requested course artifact. This module
classifies Drive tutorial candidates against the request's named current
course/unit identity plus reused current-curriculum-state evidence, and
fail-closes with a bounded unresolved/manual-review result when current
course identity, instructional context, or artifact provenance cannot be
verified. It performs no Drive/network calls and grants no external-operation
authority.
"""
from __future__ import annotations

from typing import Any

from .common import (
    FINGERPRINT_ALGORITHM,
    MAX_RESULT_BYTES,
    ContractValidationError,
    ValidatedRecord,
    ValidationResult,
    ValidationStatus,
    canonical_size,
    freeze_json,
    invalid_result,
    sanitize_detail,
    sha256_hex,
    validate_and_normalize_json,
    validate_bounded_list,
    validate_mapping,
    validate_stable_id,
    validate_text,
)
from .current_curriculum_state import CONTRACT_ID as CURRICULUM_STATE_CONTRACT_ID

CONTRACT_ID = "artifact-candidate-verification-v1"

CLASSIFICATIONS = frozenset({"verified-current", "legacy", "unverified"})
OUTCOMES = frozenset({"verified-current-artifact", "source-unresolved"})

REASON_SOURCE_UNRESOLVED = "artifact-identity-source-unresolved"
REASON_CURRICULUM_IDENTITY_UNRESOLVED = "artifact-curriculum-identity-unresolved"
REASON_NAMED_COURSE_UNRESOLVED = "artifact-named-course-unresolved"
REASON_LEGACY_CANDIDATES_NOT_CURRENT = "artifact-legacy-candidates-not-current"
REASON_MULTIPLE_CURRENT_CLAIMS = "artifact-multiple-current-claims"
BLOCKER_IDENTITY_UNVERIFIED = "artifact-current-identity-unverified"

_AUTHORITY = {
    "execution_authorized": False,
    "external_write_authorized": False,
    "approval_authorized": False,
    "classroom_readiness_authorized": False,
    "publication_authorized": False,
    "production_authorized": False,
}


def verify_classroom_artifact_candidates(
    request: object,
    curriculum_state: object,
    candidates: object,
) -> ValidationResult:
    """Classify Drive candidates against verified current-course identity.

    ``request`` carries the teacher request: ``request_id``, ``named_course``
    (the current course/unit the request names, or None when the request does
    not resolve to one), and ``artifact_topic``. ``curriculum_state`` is a
    validated ``curriculum-current-state-v1`` record (or None) reused from the
    existing current-curriculum evidence contract -- this module creates no
    second curriculum resolver. ``candidates`` is a list of Drive candidate
    evidence mappings: ``drive_file_id``, ``title``, ``course_binding``
    (course identity the candidate's evidence ties it to, or None),
    ``course_binding_verified`` (bool), and ``identity_conflict`` (bool).
    """
    try:
        request_record = _request(request)
        state_identity = _state_identity(curriculum_state)
        raw_candidates = _candidate_list(candidates)

        verdicts = [
            _classify(item, request_record["named_course"], state_identity)
            for item in raw_candidates
        ]
        verified = [item for item in verdicts if item["classification"] == "verified-current"]
        legacy = [item for item in verdicts if item["classification"] == "legacy"]

        reasons: list[str] = []
        blockers: list[str] = []
        outcome: str
        status: ValidationStatus
        certainty_language_authorized = False
        verified_id: str | None = None

        if state_identity is None:
            reasons.append(REASON_CURRICULUM_IDENTITY_UNRESOLVED)
        elif request_record["named_course"] is None:
            reasons.append(REASON_NAMED_COURSE_UNRESOLVED)
        elif state_identity["status"] != "active":
            reasons.append(REASON_CURRICULUM_IDENTITY_UNRESOLVED)

        if reasons:
            outcome = "source-unresolved"
            status = ValidationStatus.MANUAL_REVIEW_REQUIRED
            blockers.append(BLOCKER_IDENTITY_UNVERIFIED)
        elif len(verified) > 1:
            reasons.append(REASON_MULTIPLE_CURRENT_CLAIMS)
            outcome = "source-unresolved"
            status = ValidationStatus.MANUAL_REVIEW_REQUIRED
            blockers.append(BLOCKER_IDENTITY_UNVERIFIED)
        elif len(verified) == 1:
            outcome = "verified-current-artifact"
            status = ValidationStatus.VALID
            certainty_language_authorized = True
            verified_id = verified[0]["drive_file_id"]
        else:
            if legacy:
                reasons.append(REASON_LEGACY_CANDIDATES_NOT_CURRENT)
            reasons.append(REASON_SOURCE_UNRESOLVED)
            outcome = "source-unresolved"
            status = ValidationStatus.MANUAL_REVIEW_REQUIRED
            blockers.append(BLOCKER_IDENTITY_UNVERIFIED)

        payload = {
            "contract_version": CONTRACT_ID,
            "verification_id": "pending",
            "request": {
                "request_id": request_record["request_id"],
                "named_course": request_record["named_course"],
                "artifact_topic": request_record["artifact_topic"],
                "raw_text_digest": sha256_hex(request_record["raw_text"]),
            },
            "current_course": state_identity,
            "candidate_verdicts": verdicts,
            "overall_outcome": outcome,
            "verified_current_drive_file_id": verified_id,
            "response_wording": {
                # Verified/current certainty language (e.g. "the actual
                # tutorial") is authorized only when a candidate is
                # verified-current. Otherwise the response must stay at the
                # bounded unresolved/manual-review wording of the reasons.
                "certainty_language_authorized": certainty_language_authorized,
            },
            "authority": dict(_AUTHORITY),
        }
        payload["verification_id"] = "artifact-candidate-verification-" + sha256_hex(
            {key: value for key, value in payload.items() if key != "verification_id"}
        )[:24]
        validate_stable_id(payload["verification_id"], "verification_id")
        normalized = validate_and_normalize_json(payload, max_bytes=MAX_RESULT_BYTES)
        if type(normalized) is not dict or canonical_size(normalized) > MAX_RESULT_BYTES:
            raise ContractValidationError(
                "artifact-candidate-verification-oversized",
                "candidate verification exceeds result-size bound",
            )
        record = ValidatedRecord(
            contract_version=CONTRACT_ID,
            record_id=payload["verification_id"],
            record_revision=1,
            fingerprint_algorithm=FINGERPRINT_ALGORITHM,
            fingerprint=sha256_hex(normalized),
            payload=freeze_json(normalized),
        )
        if status is ValidationStatus.VALID:
            return ValidationResult(status=status, record=record)
        return ValidationResult(
            status=status,
            record=record,
            reason_codes=tuple(reasons),
            blockers=tuple(blockers),
            details=(_outcome_detail(outcome, legacy=bool(legacy)),),
        )
    except ContractValidationError as exc:
        return invalid_result(exc.reason_code, exc.detail)
    except (TypeError, ValueError) as exc:
        return invalid_result("artifact-candidate-verification-invalid", sanitize_detail(str(exc)))


def _request(value: object) -> dict[str, Any]:
    raw = validate_mapping(value, "request")
    return {
        "request_id": validate_stable_id(raw.get("request_id"), "request_id"),
        "named_course": (
            None
            if raw.get("named_course") is None
            else validate_stable_id(raw.get("named_course"), "named_course")
        ),
        "artifact_topic": validate_stable_id(raw.get("artifact_topic"), "artifact_topic"),
        "raw_text": validate_text(raw.get("raw_text"), "raw_text"),
    }


def _state_identity(value: object) -> dict[str, str] | None:
    if value is None:
        return None
    if type(value) is not ValidatedRecord:
        raise ContractValidationError(
            "artifact-candidate-verification-curriculum-invalid",
            "curriculum state must be a validated record or None",
        )
    if value.contract_version != CURRICULUM_STATE_CONTRACT_ID:
        raise ContractValidationError(
            "artifact-candidate-verification-curriculum-invalid",
            "curriculum state must reuse the current-curriculum-state contract",
        )
    payload = value.to_dict()
    if payload.get("contract_version") != CURRICULUM_STATE_CONTRACT_ID:
        raise ContractValidationError("identity-invalid", "curriculum state identity is invalid")
    if sha256_hex(payload) != value.fingerprint:
        raise ContractValidationError("identity-invalid", "curriculum state fingerprint does not reconstruct")
    unit = validate_mapping(payload.get("canonical_unit"), "canonical_unit")
    return {
        "stable_id": validate_stable_id(unit.get("stable_id"), "canonical unit stable_id"),
        "status": validate_text(unit.get("status"), "canonical unit status", max_length=64),
    }


def _candidate_list(value: object) -> list[dict[str, Any]]:
    items = validate_bounded_list(value, "candidates", maximum=64)
    seen: set[str] = set()
    parsed = []
    for item in items:
        candidate = _candidate(validate_mapping(item, "candidate"))
        if candidate["drive_file_id"] in seen:
            raise ContractValidationError(
                "artifact-candidate-verification-duplicate",
                "candidate drive file IDs must be unique",
            )
        seen.add(candidate["drive_file_id"])
        parsed.append(candidate)
    return parsed


def _candidate(raw: dict[str, Any]) -> dict[str, Any]:
    course_binding = raw.get("course_binding")
    verified = raw.get("course_binding_verified")
    if type(verified) is not bool:
        raise ContractValidationError(
            "artifact-candidate-verification-invalid",
            "course_binding_verified must be a boolean",
        )
    conflict = raw.get("identity_conflict")
    if type(conflict) is not bool:
        raise ContractValidationError(
            "artifact-candidate-verification-invalid",
            "identity_conflict must be a boolean",
        )
    if verified and course_binding is None:
        raise ContractValidationError(
            "artifact-candidate-verification-invalid",
            "a verified binding must name its course identity",
        )
    provenance_note = raw.get("provenance_note", "")
    if provenance_note is None:
        provenance_note = ""
    if type(provenance_note) is not str:
        raise ContractValidationError(
            "artifact-candidate-verification-invalid",
            "provenance_note must be a string",
        )
    if provenance_note:
        provenance_note = validate_text(provenance_note, "provenance_note", max_length=256)
    return {
        "drive_file_id": validate_stable_id(raw.get("drive_file_id"), "drive_file_id"),
        "title": validate_text(raw.get("title"), "title", max_length=512),
        "course_binding": (
            None if course_binding is None else validate_stable_id(course_binding, "course_binding")
        ),
        "course_binding_verified": verified,
        "identity_conflict": conflict,
        "provenance_note": provenance_note,
    }


def _classify(
    candidate: dict[str, Any],
    named_course: str | None,
    state_identity: dict[str, str] | None,
) -> dict[str, Any]:
    # Title/topic similarity is never evidence of current-course identity, so
    # no classification here consults the title. Identity must come from
    # verified course binding against the requested current course.
    classification = "unverified"
    reason = "title or topic similarity alone does not establish current-course identity"
    if candidate["identity_conflict"]:
        classification = "legacy"
        reason = "evidence conflicts with the requested current course identity"
    elif (
        candidate["course_binding_verified"]
        and state_identity is not None
        and state_identity["status"] == "active"
        and candidate["course_binding"] == named_course
        and candidate["course_binding"] == state_identity["stable_id"]
    ):
        classification = "verified-current"
        reason = "verified course binding matches the requested current course"
    if classification not in CLASSIFICATIONS:
        raise ContractValidationError(
            "artifact-candidate-verification-outcome-invalid",
            "unsupported candidate classification",
        )
    return {
        "drive_file_id": candidate["drive_file_id"],
        "title": candidate["title"],
        "classification": classification,
        "classification_reason": reason,
    }


def _outcome_detail(outcome: str, *, legacy: bool) -> str:
    if outcome not in OUTCOMES:
        raise ContractValidationError(
            "artifact-candidate-verification-outcome-invalid",
            "unsupported verification outcome",
        )
    detail = (
        "no candidate has verified current-course identity; "
        "return a visible bounded unresolved/manual-review result rather than "
        "asserting a match"
    )
    if legacy:
        detail += "; legacy candidates are labeled legacy, not current"
    return detail
