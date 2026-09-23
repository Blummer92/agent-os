import pytest

from scripts.agent_os_grading_decision import ApprovalState, IdentityEvidence, build_grading_decision


def identity(name):
    return IdentityEvidence(name, "synthetic-fixture", "r1")


def decision(**overrides):
    values = dict(
        student=identity("student-1"), assignment=identity("assignment-1"), rubric=identity("rubric-1"),
        proposed_score=88, feedback="Meets the rubric evidence.", uncertainty="low",
        approval_state=ApprovalState.PENDING, provenance=("fixture:evidence-1",),
        requested_target_platforms=("platform-neutral",),
    )
    values.update(overrides)
    return build_grading_decision(**values)


def test_decision_is_deterministic_and_non_authorizing():
    assert decision().decision_id == decision().decision_id
    assert decision().write_authorized is False
    assert decision().external_action_authorized is False


def test_teacher_approval_is_explicit():
    assert decision().downstream_eligible is False
    assert decision(approval_state=ApprovalState.APPROVED).downstream_eligible is True
    assert decision(approval_state=ApprovalState.REJECTED).downstream_eligible is False


def test_high_uncertainty_fails_closed_even_when_approved():
    assert decision(approval_state=ApprovalState.APPROVED, uncertainty="high").downstream_eligible is False


def test_identity_revision_changes_decision_identity():
    first = decision()
    second = decision(student=IdentityEvidence("student-1", "synthetic-fixture", "r2"))
    assert first.decision_id != second.decision_id


@pytest.mark.parametrize("score", [-1, 101, True, "88"])
def test_invalid_scores_fail_closed(score):
    with pytest.raises((TypeError, ValueError)):
        decision(proposed_score=score)


def test_duplicate_platforms_fail_closed():
    with pytest.raises(ValueError):
        decision(requested_target_platforms=("x", "x"))
