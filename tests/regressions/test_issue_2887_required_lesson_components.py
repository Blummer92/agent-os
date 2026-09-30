"""Regression coverage for #2887: a Drive worksheet missing required lesson
components must not be presented as the complete lesson artifact.

Live defect (2026-09-23): the teacher asked to see the Adobe Foundations
worksheet as a PDF. The host resolved the Drive file
"Adobe Product Foundations - Fix the Disaster - Official Class Worksheet" and
treated it as the complete lesson artifact even though the current
instructional plan required a warm-up and an exit ticket, both absent from the
worksheet (an activity-only sequence: Mission, Important, Round 1 - Diagnose,
Round 2 - Prioritize, Round 3 - Fix, Round 4 - Before/After Check, Explain Your
Best Fix, Designer Rule).

The MaterialRequirement's instructional.required_sections carry the current
plan's required lesson components; the ArtifactManifest's
artifact.observed_sections record the sections the retrieved artifact actually
contains. The reuse planner must fail closed when required components cannot
be proven present.
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
from instructional_workflow_contracts.reuse_planner import (
    plan_instructional_artifact_reuse,
)

# Required lesson components from the current instructional plan (Notion is
# authoritative for instructional intent/planning).
ADOBE_REQUIRED_SECTIONS = ["Warm-Up", "Lesson Objective", "Main Activity", "Exit Ticket"]

# Sections actually observed in the retrieved Drive worksheet: an activity-only
# sequence with no warm-up and no exit ticket.
ADOBE_OBSERVED_SECTIONS = [
    "Mission",
    "Important",
    "Round 1 - Diagnose",
    "Round 2 - Prioritize",
    "Round 3 - Fix",
    "Round 4 - Before/After Check",
    "Explain Your Best Fix",
    "Designer Rule",
]


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


def _requirement(required_sections: list[str] | None = ADOBE_REQUIRED_SECTIONS) -> ValidationResult:
    payload: dict[str, object] = {
        "identity": {
            "requirement_id": "requirement-adobe-foundations",
            "source_fingerprint": "a" * 64,
        },
        "artifact": {"artifact_type": "worksheet"},
        "templates": [],
    }
    if required_sections is not None:
        payload["instructional"] = {"required_sections": required_sections}
    return _record(payload, "curriculum-material-requirement-v1", "requirement-adobe-foundations")


def _asset() -> dict[str, object]:
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


def _manifest(observed_sections: object = ADOBE_OBSERVED_SECTIONS) -> ValidationResult:
    artifact: dict[str, object] = {"artifact_type": "worksheet"}
    if observed_sections is not None:
        artifact["observed_sections"] = observed_sections
    payload = {
        "identity": {
            "manifest_id": "manifest-adobe-worksheet",
            "source_fingerprint": "b" * 64,
        },
        "requirement_reference": {"requirement_id": "requirement-adobe-foundations"},
        "artifact": artifact,
        "external_identity": {"access_state": "verified"},
        "statuses": {
            "quality_state": "pass",
            "teacher_approval": "approved",
            "classroom_readiness": "ready",
        },
        "assets": [_asset()],
    }
    return _record(payload, "curriculum-artifact-manifest-v1", "manifest-adobe-worksheet")


def _plan(requirement: ValidationResult, manifest: ValidationResult) -> dict[str, object]:
    result = plan_instructional_artifact_reuse(
        requirement,
        [manifest],
        changed_dependency_keys=[],
        impact_map={},
        supported_executor=True,
    )
    assert result.record is not None
    return result.record.to_dict()


def test_adobe_worksheet_missing_warmup_and_exit_ticket_is_not_complete() -> None:
    """The live #2887 defect: activity-only Drive worksheet, warm-up and exit
    ticket required by the current plan but absent from the artifact."""
    payload = _plan(_requirement(), _manifest())
    assert payload["decision"] != "reuse-existing-approved"
    assert "artifact-required-sections-missing" in payload["missing_required_evidence"]
    # The candidate is still identified so the teacher sees which partial
    # artifact was assessed; it is classified as partial, not complete.
    assert payload["selected_manifest_id"] == "manifest-adobe-worksheet"


def test_adobe_worksheet_with_all_required_sections_may_be_reused() -> None:
    complete = ADOBE_OBSERVED_SECTIONS + ["Warm-Up", "Lesson Objective", "Main Activity", "Exit Ticket"]
    payload = _plan(_requirement(), _manifest(observed_sections=complete))
    assert payload["decision"] == "reuse-existing-approved"
    assert "artifact-required-sections-missing" not in payload["missing_required_evidence"]


def test_drive_title_does_not_override_missing_component_evidence() -> None:
    """An authoritative-sounding Drive title ("Official Class Worksheet") must
    not make the planner treat the artifact as complete."""
    payload = _plan(_requirement(), _manifest())
    assert payload["confidence"] != "high"
    assert payload["missing_required_evidence"] != []


def test_unevidenced_sections_fail_closed() -> None:
    """When the manifest carries no observed-section evidence at all, the
    planner cannot prove completeness and must not approve reuse."""
    payload = _plan(_requirement(), _manifest(observed_sections=None))
    assert payload["decision"] != "reuse-existing-approved"
    assert "artifact-sections-unevidenced" in payload["missing_required_evidence"]


def test_no_required_sections_preserves_existing_behavior() -> None:
    """Requirements without required lesson components behave as before."""
    payload = _plan(_requirement(required_sections=None), _manifest(observed_sections=None))
    assert payload["decision"] == "reuse-existing-approved"
    assert payload["missing_required_evidence"] == []
