from __future__ import annotations

import copy

from instructional_workflow_contracts.common import ValidationStatus
from instructional_workflow_contracts.live_operation_subject import (
    CONTRACT_ID,
    SUBJECT_ID_PREFIX,
    validate_live_operation_subject,
)
from instructional_workflow_contracts.material_requirement import (
    material_requirement_source_fingerprint,
    validate_material_requirement,
)


def _ref(stable_id: str, owner: str) -> dict[str, object]:
    return {"stable_id": stable_id, "owner": owner, "contract_version": "curriculum-workflow-handoff-v1", "record_revision": 1, "fingerprint": "a" * 64}


def _requirement() -> dict[str, object]:
    value: dict[str, object] = {
        "identity": {"contract_version": "curriculum-material-requirement-v1", "requirement_id": "requirement-1", "record_revision": 1, "course_ref": "course-1", "unit_ref": "unit-1", "lesson_ref": "lesson-1", "created_at": "2026-09-06T00:00:00Z", "created_by": "instructional-materials-coach", "source_fingerprint": "0" * 64},
        "artifact": {"artifact_type": "worksheet", "subject_metadata": "neutral"},
        "instructional": {"purpose": "Guided practice", "audience": "students", "required_sections": ["directions"]},
        "handoff_reference": {"handoff_id": "handoff-1", "contract_version": "curriculum-workflow-handoff-v1", "record_revision": 1, "fingerprint": "b" * 64},
        "learning_evidence": {"learning_objective_ref": _ref("objective-1", "unit-alignment-agent"), "success_criteria_ref": _ref("criteria-1", "unit-alignment-agent"), "evidence_target_ref": _ref("evidence-1", "unit-alignment-agent"), "alignment_owner": "unit-alignment-agent"},
        "modeling": {"modeling_readiness_ref": _ref("modeling-1", "teacher-modeling-coach"), "materials_extract_ref": _ref("extract-1", "teacher-modeling-coach"), "modeling_owner": "teacher-modeling-coach"},
        "requirements": {"vocabulary_references": [_ref("vocab-1", "unit-alignment-agent")], "accessibility_requirements": ["plain-language"], "content_requirements": ["cite-sources"], "classroom_use_requirements": ["teacher-review"]},
        "assets": [],
        "templates": [{"template_id": "template-1", "stable_ref": "template-ref-1", "access_state": "verified", "permission_state": "cleared-internal"}],
        "destination": {"destination_id": "destination-1", "destination_class": "approved-google-drive-folder", "verification_state": "verified", "exact_reference": "folder-evidence"},
        "ai_review": {"ai_assisted_generation_permitted": True, "human_review_owner": "instructional-materials-coach", "accessibility_review_required": True, "nondiscrimination_review_required": True},
        "provenance": {"citation_expectations": "Cite sources", "provenance_state": "confirmed", "copyright_state": "permission-documented", "license_state": "licensed", "asset_permission_state": "permission-documented"},
        "prohibited_data": {"student_identifying_data": False, "protected_attributes": False, "raw_student_work": False, "permanent_learner_profile": False},
        "completeness": {"state": "ready-for-planning", "blockers": [], "reason_codes": []},
        "authority": {"execution_authorized": False, "external_write_authorized": False, "production_authorized": False, "publication_authorized": False, "side_effects_performed": False},
    }
    value["identity"]["source_fingerprint"] = material_requirement_source_fingerprint(value)  # type: ignore[index]
    return value


def _subject() -> dict[str, object]:
    requirement = _requirement()
    validated = validate_material_requirement(requirement)
    assert validated.record is not None
    return {
        "contract_version": CONTRACT_ID,
        "source": {"stable_id": "lesson-content-1", "revision": 3, "content_fingerprint": "1" * 64},
        "material_requirement": {"contract_version": validated.record.contract_version, "requirement_id": validated.record.record_id, "record_revision": validated.record.record_revision, "record_fingerprint": validated.record.fingerprint, "record": requirement},
        "workspace": {"slides_template_id": "slides-template-1", "docs_template_id": "docs-template-1", "target_folder_id": "drive-folder-1"},
        "operation": {"idempotency_key": "materials-op-1", "slides_name": "Lesson Slides", "docs_name": "Lesson Worksheet", "operation_shape_fingerprint": "2" * 64},
        "gate_evidence_ids": ["gate-production-1", "gate-source-1"],
        "visual_reuse_evidence_ids": [],
        "authority": {"approval_authorized": False, "execution_authorized": False, "external_write_authorized": False, "production_authorized": False, "publication_authorized": False, "side_effects_performed": False},
    }


def _id(value: dict[str, object]) -> str:
    result = validate_live_operation_subject(value)
    assert result.status is ValidationStatus.VALID and result.record is not None
    assert result.record.record_id.startswith(SUBJECT_ID_PREFIX)
    return result.record.record_id


def test_subject_is_deterministic_canonical_and_authority_false() -> None:
    value = _subject()
    reversed_gates = copy.deepcopy(value)
    reversed_gates["gate_evidence_ids"] = list(reversed(reversed_gates["gate_evidence_ids"]))  # type: ignore[arg-type]
    first = validate_live_operation_subject(value)
    second = validate_live_operation_subject(reversed_gates)
    assert first.status is ValidationStatus.VALID
    assert first.record is not None and second.record is not None
    assert first.record.record_id == second.record.record_id
    assert first.record.authority.execution_authorized is False
    assert first.record.to_dict()["authority"] == value["authority"]


def test_every_live_semantic_binding_changes_subject_identity() -> None:
    base = _subject()
    base_id = _id(base)
    mutations = [
        (("source", "stable_id"), "lesson-content-2"),
        (("source", "revision"), 4),
        (("source", "content_fingerprint"), "3" * 64),
        (("workspace", "slides_template_id"), "slides-template-2"),
        (("workspace", "docs_template_id"), "docs-template-2"),
        (("workspace", "target_folder_id"), "drive-folder-2"),
        (("operation", "idempotency_key"), "materials-op-2"),
        (("operation", "slides_name"), "Changed Slides"),
        (("operation", "docs_name"), "Changed Worksheet"),
        (("operation", "operation_shape_fingerprint"), "4" * 64),
    ]
    for path, replacement in mutations:
        changed = copy.deepcopy(base)
        changed[path[0]][path[1]] = replacement  # type: ignore[index]
        assert _id(changed) != base_id
    changed_gate = copy.deepcopy(base)
    changed_gate["gate_evidence_ids"] = ["gate-production-2", "gate-source-1"]
    assert _id(changed_gate) != base_id


def test_material_requirement_binding_mismatch_fails_closed() -> None:
    value = _subject()
    value["material_requirement"]["record_fingerprint"] = "f" * 64  # type: ignore[index]
    result = validate_live_operation_subject(value)
    assert result.status is ValidationStatus.INVALID
    assert "material-incompatible-fingerprint" in result.reason_codes


def test_unknown_and_invocation_audit_fields_are_rejected() -> None:
    for field in ("run_id", "attempt", "correlation_id", "executor", "credential_id", "provider_response_id", "produced_file_id"):
        value = _subject()
        value[field] = "not-approval-semantic"
        result = validate_live_operation_subject(value)
        assert result.status is ValidationStatus.INVALID
        assert "handoff-unknown-field" in result.reason_codes


def test_duplicate_evidence_and_authority_escalation_fail_closed() -> None:
    duplicate = _subject()
    duplicate["gate_evidence_ids"] = ["gate-source-1", "gate-source-1"]
    assert validate_live_operation_subject(duplicate).status is ValidationStatus.INVALID
    authority = _subject()
    authority["authority"]["approval_authorized"] = True  # type: ignore[index]
    result = validate_live_operation_subject(authority)
    assert result.status is ValidationStatus.INVALID
    assert "authority-invalid" in result.reason_codes


def test_visual_reuse_identity_is_semantic_when_supplied() -> None:
    base = _subject()
    first = copy.deepcopy(base)
    first["visual_reuse_evidence_ids"] = ["visual-plan-1"]
    second = copy.deepcopy(base)
    second["visual_reuse_evidence_ids"] = ["visual-plan-2"]
    assert _id(first) != _id(second)
