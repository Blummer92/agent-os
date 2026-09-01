import pytest

from scripts.agent_os_issue_labels.pr_creation import (
    PullRequestCreationState,
    decide_pull_request_creation,
)


def test_ordinary_pr_creation_explicitly_requests_draft():
    decision = decide_pull_request_creation()
    assert decision.state is PullRequestCreationState.DRAFT
    assert decision.draft is True
    assert "explicit-draft-argument-required" in decision.reason_codes


def test_explicit_draft_request_remains_draft():
    decision = decide_pull_request_creation(ready_requested=False)
    assert decision.state is PullRequestCreationState.DRAFT
    assert decision.draft is True


def test_ready_request_without_prerequisites_fails_safe_to_draft():
    decision = decide_pull_request_creation(ready_requested=True)
    assert decision.state is PullRequestCreationState.DRAFT
    assert decision.draft is True
    assert "ready-request-fails-safe-to-draft" in decision.reason_codes
    assert "ready-transition-not-authorized" in decision.reason_codes
    assert "exact-head-validation-not-passed" in decision.reason_codes
    assert "blockers-unresolved" in decision.reason_codes


@pytest.mark.parametrize(
    "kwargs,missing_reason",
    [
        (
            dict(
                ready_transition_authorized=False,
                exact_head_validation_passed=True,
                blockers_resolved=True,
            ),
            "ready-transition-not-authorized",
        ),
        (
            dict(
                ready_transition_authorized=True,
                exact_head_validation_passed=False,
                blockers_resolved=True,
            ),
            "exact-head-validation-not-passed",
        ),
        (
            dict(
                ready_transition_authorized=True,
                exact_head_validation_passed=True,
                blockers_resolved=False,
            ),
            "blockers-unresolved",
        ),
    ],
)
def test_each_missing_ready_prerequisite_prevents_direct_ready_creation(kwargs, missing_reason):
    decision = decide_pull_request_creation(ready_requested=True, **kwargs)
    assert decision.draft is True
    assert missing_reason in decision.reason_codes


def test_explicit_ready_creation_requires_every_existing_ready_prerequisite():
    decision = decide_pull_request_creation(
        ready_requested=True,
        ready_transition_authorized=True,
        exact_head_validation_passed=True,
        blockers_resolved=True,
    )
    assert decision.state is PullRequestCreationState.READY
    assert decision.draft is False
    assert decision.reason_codes == (
        "explicit-ready-request",
        "ready-prerequisites-satisfied",
    )


def test_invalid_readiness_evidence_fails_closed():
    with pytest.raises(ValueError, match="ready_requested"):
        decide_pull_request_creation(ready_requested="yes")
