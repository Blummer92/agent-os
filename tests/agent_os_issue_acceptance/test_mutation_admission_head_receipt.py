"""Nov4 admission-86: stale-head failure receipts preserve both identities."""
from scripts.agent_os_issue_acceptance.merge_admission_actions import evaluate_merge_admission_transport
from tests.agent_os_issue_acceptance.test_merge_admission_actions import (
    HEAD, REPO, FakeClient, FakeRepo, trigger,
)


def test_nov4_admission_86_stale_head_receipt_retains_both_heads():
    observed = "f" * 40
    result = evaluate_merge_admission_transport(
        trigger(), repository=REPO,
        github_client=FakeClient(FakeRepo(head=observed)),
        evaluated_at="2026-10-19T20:00:00Z",
    )
    assert result["merge_authorized"] is False
    assert "stale-head" in result["reason_codes"]
    assert result["expected_head_sha"] == HEAD
    assert result["observed_head_sha"] == observed
    assert result["expected_head_sha"] != result["observed_head_sha"]
