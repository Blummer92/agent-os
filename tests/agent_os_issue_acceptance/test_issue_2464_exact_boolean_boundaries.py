import pytest

from scripts.agent_os_issue_acceptance.batch_merge_execution import BatchMergeAction, BatchMergeCursor, CurrentPrEvidence, MergeReadbackEvidence, record_lifecycle_mutations, record_merge_attempt


def test_current_pr_evidence_requires_boolean_flags():
    with pytest.raises(TypeError):
        CurrentPrEvidence(11, "m", "h", "open", "current", semantic_conflict="no")
    with pytest.raises(TypeError):
        CurrentPrEvidence(11, "m", "h", "open", "current", provider_available=1)


def test_merge_readback_requires_boolean_flags():
    with pytest.raises(TypeError):
        MergeReadbackEvidence(11, "h", "no", "m2")
    with pytest.raises(TypeError):
        MergeReadbackEvidence(11, "h", True, "m2", provider_available="yes")


def test_mutation_acknowledgements_require_exact_bool():
    merge_cursor = BatchMergeCursor((11,), current_main_sha="m", current_head_sha="h", action=BatchMergeAction.MERGE)
    with pytest.raises(TypeError):
        record_merge_attempt(merge_cursor, pull_request_number=11, expected_head_sha="h", accepted=1)
    lifecycle_cursor = BatchMergeCursor((11,), ((11, 101),), current_main_sha="m", current_head_sha="h", pending_merged_main_sha="m2", action=BatchMergeAction.LIFECYCLE_MUTATE)
    with pytest.raises(TypeError):
        record_lifecycle_mutations(lifecycle_cursor, issue_number=101, accepted="yes")
