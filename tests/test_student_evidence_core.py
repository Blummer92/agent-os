from dataclasses import FrozenInstanceError

import pytest

from student_evidence_core import (
    ContractError,
    EvidenceAsset,
    EvidenceLocator,
    EvidenceProvenance,
    EvidenceTrust,
    OrganizationProposal,
    ProjectionRecord,
    ProposalState,
    ResponseRecord,
    ReviewState,
    StudentIdentity,
    SubmissionRecord,
    TeacherDecision,
    canonical_payload,
    fingerprint,
)


def _student() -> StudentIdentity:
    return StudentIdentity("drive", "student-123", "Student 123")


def _locator() -> EvidenceLocator:
    return EvidenceLocator("drive", "file-abc", "rev-7", "drive://file-abc")


def _provenance() -> EvidenceProvenance:
    return EvidenceProvenance(
        _locator(),
        "plain-text-extract",
        "1",
        0.95,
        EvidenceTrust.PROVIDER_VERIFIED,
        ReviewState.NEEDS_REVIEW,
    )


def _asset() -> EvidenceAsset:
    provenance = _provenance()
    return EvidenceAsset(
        _student(),
        provenance.locator,
        provenance,
        "application/pdf",
        "content-sha",
        "metadata-sha",
        "bounded derived text",
    )


def test_exact_identity_revision_and_immutability() -> None:
    asset = _asset()
    assert asset.locator.native_artifact_id == "file-abc"
    assert asset.locator.native_revision == "rev-7"
    with pytest.raises(FrozenInstanceError):
        asset.media_type = "text/plain"  # type: ignore[misc]


def test_deterministic_serialization_and_fingerprint() -> None:
    first = StudentIdentity("drive", "student-123", "Student 123")
    second = StudentIdentity("drive", "student-123", "Student 123")
    assert canonical_payload(first) == canonical_payload(second)
    assert fingerprint(first) == fingerprint(second)
    assert len(fingerprint(first)) == 64


def test_submission_rejects_cross_student_evidence() -> None:
    asset = _asset()
    with pytest.raises(ContractError, match="student-mismatch"):
        SubmissionRecord(
            "submission-1",
            StudentIdentity("drive", "other-student"),
            (asset,),
            "2026-08-11T12:00:00Z",
        )


def test_derived_response_requires_provenance_and_revision() -> None:
    response = ResponseRecord(
        "response-1",
        "submission-1",
        "rev-7",
        "derived response",
        _provenance(),
    )
    assert response.source_revision == "rev-7"
    assert response.provenance.extraction_recipe == "plain-text-extract"


def test_proposal_keeps_suggestion_correction_and_execution_separate() -> None:
    proposal = OrganizationProposal(
        "proposal-1",
        ("evidence-1",),
        "Period 2/Portfolio",
        ProposalState.CORRECTED,
        teacher_correction="Period 2/Retakes",
    )
    assert proposal.suggested_destination == "Period 2/Portfolio"
    assert proposal.teacher_correction == "Period 2/Retakes"
    assert proposal.execution_result is None

    executed = OrganizationProposal(
        "proposal-2",
        ("evidence-2",),
        "Period 3/Portfolio",
        ProposalState.EXECUTED,
        execution_result="provider-operation-42",
    )
    assert executed.execution_result == "provider-operation-42"


def test_corrected_and_executed_states_fail_closed_without_required_evidence() -> None:
    with pytest.raises(ContractError, match="teacher_correction:required"):
        OrganizationProposal("proposal", ("evidence",), "dest", ProposalState.CORRECTED)
    with pytest.raises(ContractError, match="execution_result:required"):
        OrganizationProposal("proposal", ("evidence",), "dest", ProposalState.EXECUTED)


def test_teacher_decision_is_not_machine_proposal_state() -> None:
    decision = TeacherDecision(
        "proposal-1",
        ProposalState.ACCEPTED,
        "teacher-native-id",
        "decision-rev-1",
    )
    assert decision.decision is ProposalState.ACCEPTED
    with pytest.raises(ContractError, match="decision:invalid"):
        TeacherDecision("proposal-1", ProposalState.PROPOSED, "teacher", "rev")


def test_projection_authority_is_always_false() -> None:
    projection = ProjectionRecord(
        "projection-1",
        ("submission-1", "response-1"),
        "payload-sha",
        ReviewState.REVIEWED,
    )
    assert projection.grading_authority is False
    assert projection.curriculum_authority is False
    assert projection.movement_authority is False
    assert projection.publication_authority is False
    assert projection.external_write_authority is False

    with pytest.raises(ContractError, match="authority:must-be-false"):
        ProjectionRecord(
            "projection-1",
            ("submission-1",),
            "payload-sha",
            ReviewState.REVIEWED,
            external_write_authority=True,
        )


def test_malformed_and_hostile_inputs_fail_closed() -> None:
    with pytest.raises(ContractError, match="native_student_id:required"):
        StudentIdentity("drive", " ")
    with pytest.raises(ContractError, match="confidence:invalid-type"):
        EvidenceProvenance(
            _locator(),
            "extract",
            "1",
            True,  # type: ignore[arg-type]
            EvidenceTrust.UNVERIFIED,
            ReviewState.NOT_REVIEWED,
        )
    with pytest.raises(ContractError, match="confidence:out-of-range"):
        EvidenceProvenance(
            _locator(),
            "extract",
            "1",
            1.5,
            EvidenceTrust.UNVERIFIED,
            ReviewState.NOT_REVIEWED,
        )


def test_existing_packages_remain_importable_without_coupling() -> None:
    import instructional_evidence_intake
    import instructional_workflow_contracts
    import visual_asset_sync

    assert instructional_evidence_intake is not None
    assert instructional_workflow_contracts is not None
    assert visual_asset_sync is not None
