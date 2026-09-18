from scripts.agent_os_issue_acceptance.primary_pr_creation_admission import (
    ActivePrimaryPr,
    PrimaryPrCreationAction,
    evaluate_primary_pr_creation_admission,
    evaluate_batch_primary_pr_packaging,
)


def pr(number: int) -> ActivePrimaryPr:
    return ActivePrimaryPr(
        pull_request_number=number,
        branch=f"agent/{number}-fixture",
        head_sha=f"{number % 16:x}" * 40,
    )


def test_no_active_primary_pr_admits_creation_without_granting_write_authority() -> None:
    result = evaluate_primary_pr_creation_admission(
        issue_number=2612,
        issue_open=True,
        evidence_current=True,
        active_primary_prs=(),
    )
    assert result.creation_admitted is True
    assert result.action is PrimaryPrCreationAction.CREATE_PRIMARY_PR
    assert result.existing_pull_request_number is None
    assert result.github_writes_authorized is False


def test_one_active_primary_pr_reuses_existing_lineage() -> None:
    result = evaluate_primary_pr_creation_admission(
        issue_number=2609,
        issue_open=True,
        evidence_current=True,
        active_primary_prs=(pr(2610),),
    )
    assert result.creation_admitted is False
    assert result.action is PrimaryPrCreationAction.REUSE_EXISTING_PRIMARY_PR
    assert result.existing_pull_request_number == 2610
    assert result.reason_codes == ("primary-pr.existing-active",)


def test_2609_duplicate_pr_reproduction_fails_closed() -> None:
    result = evaluate_primary_pr_creation_admission(
        issue_number=2609,
        issue_open=True,
        evidence_current=True,
        active_primary_prs=(pr(2610), pr(2611)),
    )
    assert result.creation_admitted is False
    assert result.action is PrimaryPrCreationAction.MANUAL_RECONCILIATION
    assert result.reason_codes == ("primary-pr.multiple-active",)


def test_stale_evidence_never_admits_creation() -> None:
    result = evaluate_primary_pr_creation_admission(
        issue_number=2612,
        issue_open=True,
        evidence_current=False,
        active_primary_prs=(),
    )
    assert result.creation_admitted is False
    assert result.reason_codes == ("primary-pr-evidence.stale",)


def test_closed_issue_never_admits_creation() -> None:
    result = evaluate_primary_pr_creation_admission(
        issue_number=2612,
        issue_open=False,
        evidence_current=True,
        active_primary_prs=(),
    )
    assert result.creation_admitted is False
    assert result.reason_codes == ("issue.not-open",)


def test_2447_independent_batch_issues_require_separate_primary_prs() -> None:
    result = evaluate_batch_primary_pr_packaging(
        issue_numbers=(2442, 2443),
        focused_objective_shared=False,
    )
    assert result.packaging_admitted is False
    assert result.reason_codes == ("primary-pr.independent-issues-require-separate-prs",)
    assert result.github_writes_authorized is False


def test_2423_2424_simultaneous_selection_does_not_authorize_combined_pr() -> None:
    result = evaluate_batch_primary_pr_packaging(
        issue_numbers=(2423, 2424),
        focused_objective_shared=False,
    )
    assert result.packaging_admitted is False


def test_multiple_issue_reference_requires_explicit_shared_objective_evidence() -> None:
    result = evaluate_batch_primary_pr_packaging(
        issue_numbers=(10, 11),
        focused_objective_shared=True,
    )
    assert result.packaging_admitted is True
    assert result.reason_codes == ("primary-pr.shared-focused-objective-proven",)
