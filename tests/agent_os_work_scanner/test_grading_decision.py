from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from scripts.agent_os_work_scanner import (
    EvidenceFreshness,
    GradingDecision,
    IdentityEvidence,
    IdentityResolution,
    RubricCriterionEvidence,
    SourceProvenance,
    TeacherApprovalState,
)


DIGEST = "a" * 64


def identity(identity_id: str = "synthetic-student-01") -> IdentityEvidence:
    return IdentityEvidence(
        resolution=IdentityResolution.RESOLVED,
        resolved_id=identity_id,
        evidence_refs=("synthetic-evidence-1",),
        confidence=Decimal("0.98"),
    )


def criterion(
    criterion_id: str = "composition",
    possible: str = "10",
    awarded: str = "8",
) -> RubricCriterionEvidence:
    return RubricCriterionEvidence(
        criterion_id=criterion_id,
        description="Synthetic rubric criterion",
        possible_points=Decimal(possible),
        awarded_points=Decimal(awarded),
        evidence_refs=(f"evidence-{criterion_id}",),
    )


def decision(**overrides: object) -> GradingDecision:
    values: dict[str, object] = {
        "student": identity(),
        "assignment": identity("synthetic-assignment-01"),
        "rubric": (criterion(),),
        "proposed_score": Decimal("8"),
        "max_score": Decimal("10"),
        "feedback": "Synthetic feedback only.",
        "confidence": Decimal("0.95"),
        "uncertainty_reasons": (),
        "approval_state": TeacherApprovalState.APPROVED,
        "freshness": EvidenceFreshness.CURRENT,
        "provenance": (
            SourceProvenance(
                source_type="synthetic-submission",
                source_id="submission-01",
                content_digest=DIGEST,
            ),
        ),
        "target_platforms": ("schoology", "powerschool"),
    }
    values.update(overrides)
    return GradingDecision(**values)  # type: ignore[arg-type]


def test_valid_decision_is_portable_but_never_write_authorized() -> None:
    result = decision()

    assert result.eligible_for_authorization_review is True
    assert result.write_authorized is False
    assert result.to_record()["write_authorized"] is False
    assert result.to_record()["target_platforms"] == ["powerschool", "schoology"]
    assert result.decision_id.startswith("grading-decision:")


def test_serialization_and_digest_are_deterministic() -> None:
    first = decision(
        target_platforms=("schoology", "powerschool"),
        uncertainty_reasons=("z", "a"),
    )
    second = decision(
        target_platforms=("powerschool", "schoology"),
        uncertainty_reasons=("a", "z"),
    )

    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.decision_id == second.decision_id


def test_multi_criterion_order_does_not_change_digest() -> None:
    a = criterion("analysis", "4", "3")
    b = criterion("craft", "6", "5")
    first = decision(rubric=(a, b))
    second = decision(rubric=(b, a))

    assert first.decision_id == second.decision_id


@pytest.mark.parametrize(
    ("field", "resolution", "expected"),
    [
        ("student", IdentityResolution.AMBIGUOUS, "student.ambiguous"),
        ("assignment", IdentityResolution.AMBIGUOUS, "assignment.ambiguous"),
        ("student", IdentityResolution.NOT_FOUND, "student.not-found"),
    ],
)
def test_unresolved_identity_fails_closed(
    field: str,
    resolution: IdentityResolution,
    expected: str,
) -> None:
    unresolved = IdentityEvidence(
        resolution=resolution,
        resolved_id=None,
        evidence_refs=("synthetic-match-evidence",),
        confidence=Decimal("0.4"),
    )
    result = decision(**{field: unresolved})

    assert expected in result.blocking_reasons
    assert result.eligible_for_authorization_review is False


@pytest.mark.parametrize(
    ("approval", "expected"),
    [
        (TeacherApprovalState.PENDING, "approval.pending"),
        (TeacherApprovalState.REJECTED, "approval.rejected"),
    ],
)
def test_unapproved_decision_fails_closed(
    approval: TeacherApprovalState,
    expected: str,
) -> None:
    result = decision(approval_state=approval)

    assert expected in result.blocking_reasons
    assert result.eligible_for_authorization_review is False
    assert result.write_authorized is False


def test_stale_decision_fails_closed() -> None:
    result = decision(freshness=EvidenceFreshness.STALE)

    assert result.blocking_reasons == ("evidence.stale",)
    assert result.eligible_for_authorization_review is False


def test_uncertainty_fails_closed() -> None:
    result = decision(uncertainty_reasons=("rubric-evidence-incomplete",))

    assert result.blocking_reasons == ("decision.uncertain",)
    assert result.eligible_for_authorization_review is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"proposed_score": Decimal("11")},
        {"max_score": Decimal("9")},
        {"feedback": "  "},
        {"target_platforms": ()},
        {"provenance": ()},
    ],
)
def test_malformed_decisions_are_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        decision(**overrides)


def test_rubric_totals_must_match_proposed_score() -> None:
    with pytest.raises(ValueError, match="proposed_score must equal"):
        decision(proposed_score=Decimal("7"))


def test_duplicate_rubric_criteria_are_rejected() -> None:
    with pytest.raises(ValueError, match="criterion_id values must be unique"):
        decision(rubric=(criterion(), criterion()))


def test_platform_specific_runtime_details_are_not_part_of_contract() -> None:
    record = decision().to_record()
    serialized = str(record).lower()

    for forbidden in ("selector", "cookie", "session", "url", "dom"):
        assert forbidden not in serialized


def test_decision_id_changes_when_semantics_change() -> None:
    original = decision()
    changed = decision(feedback="Different synthetic feedback.")

    assert original.decision_id != changed.decision_id


def test_frozen_decision_cannot_be_mutated_after_approval() -> None:
    approved = decision()

    with pytest.raises(Exception):
        approved.feedback = "mutated"  # type: ignore[misc]


def test_identity_requires_evidence_and_resolved_id_consistency() -> None:
    with pytest.raises(ValueError):
        IdentityEvidence(
            resolution=IdentityResolution.RESOLVED,
            resolved_id=None,
            evidence_refs=("evidence",),
            confidence=Decimal("0.9"),
        )
    with pytest.raises(ValueError):
        replace(identity(), resolution=IdentityResolution.AMBIGUOUS)
