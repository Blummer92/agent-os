"""Nov4 admission-7: malformed input receipts retain supplied selectors."""
from scripts.agent_os_issue_acceptance.merge_admission_actions import evaluate_merge_admission_transport
from tests.agent_os_issue_acceptance.test_merge_admission_actions import (
    REPO, FakeClient, FakeRepo, trigger,
)


def test_nov4_admission_7_malformed_envelope_retains_identity_fields():
    envelope = trigger()
    envelope["reason"] = "wrong-transport-reason"
    result = evaluate_merge_admission_transport(
        envelope, repository=REPO, github_client=FakeClient(FakeRepo()),
        evaluated_at="2026-10-19T20:00:00Z",
    )
    assert result["merge_authorized"] is False
    assert result["expected_head_sha"] == envelope["merge_admission_head_sha_or_none"]
    assert result["pr_number"] == envelope["merge_admission_pr_number_or_none"]
    assert result["logical_trigger_id"] == envelope["logical_trigger_id_or_none"]
    assert "transport-not-merge-admission" in result["reason_codes"]
