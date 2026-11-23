"""Cumulative required-docs evidence: checker contract (#3724).

The fixtures use the shape of a tests-only follow-up (PR 3709) to an issue
(3677) whose documentation an earlier PR (3681) delivered. They exercise
the offline checker with hand-built records only; whether a live PR yields
a record at all is decided by the producer (see
``test_3719_merged_doc_producer.py``), which rejects that real PR on
canonical association and changed documentation blobs.

These tests pin the checker contract: a declaration may be satisfied by a
merged PR only through a record passing every gate in
``merged_docs.validate_record`` (merged, timeline association, same
issue, merge commit in the evaluated base, fresh declaration snapshot)
whose files match it under the canonical declared-path contract. Every
single-gate failure below must keep docs failing.
"""
from scripts.agent_os_issue_acceptance.checks import required_docs
from scripts.agent_os_issue_acceptance.merged_docs import validate_record
from scripts.agent_os_issue_acceptance.models import AcceptanceInput, IssueMetadata, Status
from scripts.agent_os_issue_acceptance.policy import evaluate_acceptance

REQUIRED = [
    "01_Shared_Standards/github/issue-lifecycle-standard.md",
    "01_Shared_Standards/github/issue-acceptance-automation.md",
]
MERGED_FILES = [
    ".github/PULL_REQUEST_TEMPLATE.md",
    "01_Shared_Standards/github/issue-acceptance-automation.md",
    "01_Shared_Standards/github/issue-lifecycle-standard.md",
]
ISSUE_BODY = """# ISSUE-SATISFACTION-A

```yaml
agent_os_issue_acceptance:
  owner_agent: github-service-agent
  source_of_truth: GitHub
  external_writes: none
  required_files: []
  forbidden_paths: []
  required_tests: []
  documentation_impact: docs-required
  required_docs:
    - 01_Shared_Standards/github/issue-lifecycle-standard.md
    - 01_Shared_Standards/github/issue-acceptance-automation.md
  banned_patterns: []
  manual_review: []
```
"""
PR_BODY = """## Linked issue
Part of #3677

Non-closing: #3677
"""


def _record(**overrides):
    record = {
        "source_pr_number": 3681,
        "linked_issue_number": 3677,
        "association_basis": "timeline-cross-reference",
        "merge_commit_sha": "4954b05c52a24744f566b74b75753259801e41dd",
        "merged": True,
        "merge_commit_in_evaluated_base": True,
        "declared_required_docs": list(REQUIRED),
        "files": list(MERGED_FILES),
    }
    record.update(overrides)
    return record


def _metadata():
    return IssueMetadata(present=True, required_docs=list(REQUIRED))


def _docs_result(changed, merged=(), linked_issue=3677):
    return required_docs.check(_metadata(), list(changed), merged_docs=merged, linked_issue=linked_issue)


def test_3709_regression_current_pr_only_fails():
    result = _docs_result(["tests/agent_os_issue_acceptance/test_m19_criterion_identity_regression.py"])
    assert result.status == Status.FAIL
    assert result.evidence == [
        "field=required_docs; value='01_Shared_Standards/github/issue-acceptance-automation.md'; code=unmatched",
        "field=required_docs; value='01_Shared_Standards/github/issue-lifecycle-standard.md'; code=unmatched",
    ]


def test_3709_regression_valid_merged_record_passes():
    result = _docs_result(
        ["tests/agent_os_issue_acceptance/test_m19_criterion_identity_regression.py"],
        merged=(_record(),),
    )
    assert result.status == Status.PASS
    assert result.message == "Declared required docs are satisfied, including merged-PR evidence."
    assert result.evidence == [
        "field=required_docs; value='01_Shared_Standards/github/issue-acceptance-automation.md'; code=merged-pr-3681",
        "field=required_docs; value='01_Shared_Standards/github/issue-lifecycle-standard.md'; code=merged-pr-3681",
    ]


def test_current_pr_match_still_passes_without_merged_evidence():
    result = _docs_result(list(REQUIRED))
    assert result.status == Status.PASS
    assert result.message == "Declared required docs are satisfied."
    assert result.evidence == []


def test_policy_3709_docs_fail_without_merged_and_pass_with_merged():
    changed = ["tests/agent_os_issue_acceptance/test_m19_criterion_identity_regression.py"]
    base = AcceptanceInput(issue_body=ISSUE_BODY, pr_body=PR_BODY, changed_files=changed, diff_text="")
    without = evaluate_acceptance(base)
    docs_without = next(c for c in without.checks if c.name == "required docs")
    assert docs_without.status == Status.FAIL

    with_merged = evaluate_acceptance(
        AcceptanceInput(
            issue_body=ISSUE_BODY,
            pr_body=PR_BODY,
            changed_files=changed,
            diff_text="",
            merged_doc_evidence=(_record(),),
        )
    )
    docs_with = next(c for c in with_merged.checks if c.name == "required docs")
    assert docs_with.status == Status.PASS
    assert "merged_doc_records=1" in with_merged.evidence


# --- every single-gate failure must keep docs failing -----------------------


def test_unmerged_record_does_not_count():
    assert _docs_result([], merged=(_record(merged=False),)).status == Status.FAIL


def test_unrelated_issue_record_does_not_count():
    assert _docs_result([], merged=(_record(linked_issue_number=9999),)).status == Status.FAIL


def test_no_linked_issue_record_does_not_count():
    result = required_docs.check(_metadata(), [], merged_docs=(_record(),), linked_issue=None)
    assert result.status == Status.FAIL


def test_merge_not_in_base_record_does_not_count():
    assert _docs_result([], merged=(_record(merge_commit_in_evaluated_base=False),)).status == Status.FAIL


def test_prose_only_association_basis_does_not_count():
    assert _docs_result([], merged=(_record(association_basis="pr-body-mention"),)).status == Status.FAIL


def test_referenced_merge_commit_basis_does_not_count():
    # No producer emits this basis, so the checker does not accept it.
    result = _docs_result([], merged=(_record(association_basis="timeline-referenced-merge-commit"),))
    assert result.status == Status.FAIL
    assert "field=merged_docs_evidence; code=merged-docs-evidence-invalid:bad-association-basis" in result.evidence


def test_stale_declaration_snapshot_does_not_count():
    assert _docs_result([], merged=(_record(declared_required_docs=[REQUIRED[0]]),)).status == Status.FAIL


def test_partial_merged_files_do_not_count():
    assert _docs_result([], merged=(_record(files=[MERGED_FILES[0]]),)).status == Status.FAIL


def test_bad_merge_sha_does_not_count():
    assert _docs_result([], merged=(_record(merge_commit_sha="deadbeef"),)).status == Status.FAIL


def test_malformed_record_does_not_count_or_raise():
    for bad in ({}, {"source_pr_number": 3681}, [_record()], "not-a-record"):
        result = _docs_result([], merged=(bad,))
        assert result.status == Status.FAIL


def test_validate_record_reasons_are_stable():
    assert validate_record(_record(), linked_issue=3677, required_docs=REQUIRED) is None
    assert validate_record(_record(linked_issue_number=1), linked_issue=3677, required_docs=REQUIRED) == "linked-issue-mismatch"
    assert validate_record(_record(linked_issue_number=True), linked_issue=1, required_docs=REQUIRED) == "bad-linked-issue"
    assert validate_record(_record(merged=False), linked_issue=3677, required_docs=REQUIRED) == "not-merged"


def test_invalid_record_reason_is_reported_with_failure():
    result = _docs_result([], merged=(_record(merged=False),))
    assert result.status == Status.FAIL
    assert result.evidence[-1] == "field=merged_docs_evidence; code=merged-docs-evidence-invalid:not-merged"
