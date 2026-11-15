"""Nov4 admission-28: invalid clock is still recorded for diagnosis."""
from scripts.agent_os_issue_acceptance.merge_admission_actions import evaluate_merge_admission_transport
from tests.agent_os_issue_acceptance.test_merge_admission_actions import (
    REPO, FakeClient, FakeRepo, trigger,
)


def test_nov4_admission_28_malformed_clock_receipt_retains_input():
    invalid = "not-a-timestamp"
    result = evaluate_merge_admission_transport(
        trigger(), repository=REPO, github_client=FakeClient(FakeRepo()),
        evaluated_at=invalid,
    )
    assert result["merge_authorized"] is False
    assert result["reason_codes"] == ["evaluator-clock-malformed"]
    assert result["evaluated_at"] == invalid
    assert result["expected_head_sha"] == trigger()["merge_admission_head_sha_or_none"]
