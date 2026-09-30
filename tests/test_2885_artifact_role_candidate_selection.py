"""Regression guards for #2885: the requested artifact role stays authoritative
through candidate selection.

Live reproduction (2026-09-23): the teacher asked to see the Candy Branding
Day 1-10 worksheet/PDF; ChatGPT found `Candy_Branding_Teacher_Modeling_Package`
in Drive and rendered that teacher modeling package as the visual answer.
A worksheet request must never resolve to a teacher-modeling package as the
final/preview artifact, even when the wrong-role file is the closest
title/unit-name match in the candidate set.
"""
from __future__ import annotations

from instructional_workflow_contracts.common import (
    FINGERPRINT_ALGORITHM,
    ValidatedRecord,
    ValidationResult,
    ValidationStatus,
    freeze_json,
    sha256_hex,
)
from instructional_workflow_contracts.material_requirement import (
    SUPPORTED_ARTIFACT_TYPES,
)
from instructional_workflow_contracts.reuse_planner import (
    plan_instructional_artifact_reuse,
)

# Regression metadata for the issue's required test record:
# - exact prompt sequence: "Show me what day 1-10 candybranding works like"
#   -> ten-day sequence described -> "Show me the pdf looks like"
# - expected artifact type: student worksheet (Candy Branding Day 1-10)
# - drive candidate set: a same-unit teacher modeling package
#   (Candy_Branding_Teacher_Modeling_Package) plus a student worksheet
# - failure signal: the modeling package was rendered as the visual answer
CANDY_BRANDING_UNIT = "candy-branding-day-1-10"


def _record(payload: dict[str, object], contract: str, record_id: str) -> ValidationResult:
    record = ValidatedRecord(
        contract_version=contract,
        record_id=record_id,
        record_revision=1,
        fingerprint_algorithm=FINGERPRINT_ALGORITHM,
        fingerprint=sha256_hex(payload),
        payload=freeze_json(payload),
    )
    return ValidationResult(status=ValidationStatus.VALID, record=record)


def worksheet_requirement() -> ValidationResult:
    payload = {
        "identity": {
            "requirement_id": "requirement-candy-branding",
            "source_fingerprint": "a" * 64,
        },
        "artifact": {"artifact_type": "worksheet"},
        "templates": [],
    }
    return _record(payload, "curriculum-material-requirement-v1", "requirement-candy-branding")


def drive_asset() -> dict[str, object]:
    return {
        "asset_id": "asset-1",
        "duplicate_relationship": "unique",
        "disposition": "canonical",
        "canonical_asset_ref": None,
        "rights_classification": "permission-documented",
        "privacy_observations": [],
        "privacy_resolved": True,
        "residual_privacy_risk": False,
        "content_findings": [],
        "repair_source_status": "not-needed",
        "correction_requirement": None,
        "replacement_required": False,
        "transformations": [],
        "required_context_flags": [],
        "preserved_context_flags": [],
        "context_preservation_complete": True,
    }


def drive_candidate(
    *,
    manifest_id: str,
    artifact_type: str,
    access: str = "verified",
    quality: str = "pass",
    teacher: str = "approved",
    readiness: str = "ready",
) -> ValidationResult:
    payload = {
        "identity": {
            "manifest_id": manifest_id,
            "source_fingerprint": (manifest_id.encode().hex() + "0" * 64)[:64],
        },
        "requirement_reference": {"requirement_id": "requirement-candy-branding"},
        "artifact": {"artifact_type": artifact_type},
        "external_identity": {"access_state": access},
        "statuses": {
            "quality_state": quality,
            "teacher_approval": teacher,
            "classroom_readiness": readiness,
        },
        "assets": [drive_asset()],
    }
    return _record(payload, "curriculum-artifact-manifest-v1", manifest_id)


def plan_result(candidates: list[ValidationResult]) -> dict[str, object]:
    result = plan_instructional_artifact_reuse(
        worksheet_requirement(),
        candidates,
        changed_dependency_keys=[],
        impact_map={},
        supported_executor=True,
    )
    assert result.record is not None
    return result.record.to_dict()


def test_teacher_modeling_package_is_a_supported_classified_artifact_type() -> None:
    assert "teacher-modeling-package" in SUPPORTED_ARTIFACT_TYPES
    assert "worksheet" in SUPPORTED_ARTIFACT_TYPES


def test_modeling_package_can_never_be_selected_for_a_worksheet_request() -> None:
    modeling = drive_candidate(
        manifest_id="candy-branding-teacher-modeling-package",
        artifact_type="teacher-modeling-package",
    )
    worksheet = drive_candidate(
        manifest_id="candy-branding-day-1-10-worksheet",
        artifact_type="worksheet",
    )
    outcome = plan_result([modeling, worksheet])
    assert outcome["selected_manifest_id"] == "candy-branding-day-1-10-worksheet"
    assert outcome["decision"] == "reuse-existing-approved"
    assert (
        "artifact-reuse-rejected-role-conflict:candy-branding-teacher-modeling-package"
        in outcome["rejection_reasons"]
    )
    assert "artifact-type-conflict" in outcome["conflicting_evidence"]


def test_role_conflict_beats_title_similarity_rank() -> None:
    # The modeling package is fully evidenced (score 80) while the same-unit
    # worksheet is missing quality evidence (score 70); the wrong-role file
    # ranks first by score, but the role conflict is inadmissible for selection.
    modeling = drive_candidate(
        manifest_id="candy-branding-teacher-modeling-package",
        artifact_type="teacher-modeling-package",
    )
    weaker_worksheet = drive_candidate(
        manifest_id="candy-branding-day-1-10-worksheet",
        artifact_type="worksheet",
        access="denied",
        quality="manual-review",
        teacher="pending",
        readiness="manual-review-required",
    )
    outcome = plan_result([modeling, weaker_worksheet])
    assert outcome["candidate_order"][0] == "candy-branding-teacher-modeling-package"
    assert outcome["selected_manifest_id"] == "candy-branding-day-1-10-worksheet"
    assert "candy-branding-teacher-modeling-package" != outcome["selected_manifest_id"]


def test_worksheet_only_modeling_candidate_fails_closed_without_substitution() -> None:
    # Exact live-defect shape: Drive's only close hit is the teacher modeling
    # package. The plan must not resolve it to the requested worksheet.
    modeling = drive_candidate(
        manifest_id="candy-branding-teacher-modeling-package",
        artifact_type="teacher-modeling-package",
    )
    outcome = plan_result([modeling])
    assert outcome["selected_manifest_id"] is None
    assert outcome["decision"] == "manual-review-required"
    assert (
        "artifact-reuse-rejected-role-conflict:candy-branding-teacher-modeling-package"
        in outcome["rejection_reasons"]
    )
    assert "artifact-type-conflict" in outcome["conflicting_evidence"]
    assert outcome["visual_recommendations"] == []


def test_role_conflict_exclusion_is_deterministic_and_advisory() -> None:
    modeling = drive_candidate(
        manifest_id="candy-branding-teacher-modeling-package",
        artifact_type="teacher-modeling-package",
    )
    worksheet = drive_candidate(
        manifest_id="candy-branding-day-1-10-worksheet",
        artifact_type="worksheet",
    )
    first = plan_result([modeling, worksheet])
    second = plan_result([worksheet, modeling])
    assert first == second
    assert all(value is False for value in first["authority"].values())
