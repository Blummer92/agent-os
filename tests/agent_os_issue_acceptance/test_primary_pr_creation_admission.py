from scripts.agent_os_issue_acceptance.primary_pr_creation_admission import (
    ActivePrimaryPr,
    BatchIssuePrimaryPrEvidence,
    PrimaryPrCreationAction,
    evaluate_batch_primary_pr_packaging,
    evaluate_primary_pr_creation_admission,
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





def test_existing_implementation_branch_without_active_pr_fails_closed() -> None:
    result = evaluate_primary_pr_creation_admission(
        issue_number=2612,
        issue_open=True,
        evidence_current=True,
        active_primary_prs=(),
        branch_exists=True,
    )
    assert result.creation_admitted is False
    assert result.action is PrimaryPrCreationAction.MANUAL_RECONCILIATION
    assert result.reason_codes == ("primary-pr.branch-without-active-pr",)


def test_batch_packaging_preserves_branch_without_pr_fail_closed_behavior() -> None:
    result = evaluate_batch_primary_pr_packaging(
        issue_evidence=(
            BatchIssuePrimaryPrEvidence(
                issue_number=2612,
                issue_open=True,
                objective_ref="objective/branch-claim",
                active_primary_prs=(),
                branch_exists=True,
            ),
        ),
        evidence_current=True,
    )
    assert result.packaging_admitted is False
    assert result.per_issue_admissions[0][1].action is PrimaryPrCreationAction.MANUAL_RECONCILIATION
    assert result.reason_codes == ("primary-pr.branch-without-active-pr",)


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


def issue(number: int, objective_ref: str, *active: ActivePrimaryPr) -> BatchIssuePrimaryPrEvidence:
    return BatchIssuePrimaryPrEvidence(
        issue_number=number,
        issue_open=True,
        objective_ref=objective_ref,
        active_primary_prs=active,
    )


def test_2447_independent_batch_issues_require_separate_primary_prs() -> None:
    result = evaluate_batch_primary_pr_packaging(
        issue_evidence=(
            issue(2442, "objective/candidate-packet-identity"),
            issue(2443, "objective/candidate-packet-transport"),
        ),
        evidence_current=True,
    )
    assert result.packaging_admitted is False
    assert result.reason_codes == ("primary-pr.independent-issues-require-separate-prs",)
    assert result.github_writes_authorized is False


def test_2423_2424_simultaneous_selection_does_not_authorize_combined_pr() -> None:
    result = evaluate_batch_primary_pr_packaging(
        issue_evidence=(
            issue(2423, "objective/acceptance-report-transport"),
            issue(2424, "objective/acceptance-report-rendering"),
        ),
        evidence_current=True,
    )
    assert result.packaging_admitted is False


def test_shared_focused_objective_is_proven_by_canonical_objective_evidence() -> None:
    result = evaluate_batch_primary_pr_packaging(
        issue_evidence=(
            issue(10, "objective/one-focused-implementation"),
            issue(11, "objective/one-focused-implementation"),
        ),
        evidence_current=True,
    )
    assert result.packaging_admitted is True
    assert result.reason_codes == ("primary-pr.shared-focused-objective-proven",)


def test_shared_objective_cannot_be_asserted_without_canonical_evidence() -> None:
    try:
        BatchIssuePrimaryPrEvidence(
            issue_number=10,
            issue_open=True,
            objective_ref="",
            active_primary_prs=(),
        )
    except ValueError as exc:
        assert "objective_ref" in str(exc)
    else:  # pragma: no cover - the guard must reject unproven objective evidence
        assert False, "empty objective evidence must not admit packaging"


def test_2447_second_execution_wave_reuses_the_existing_primary_pr() -> None:
    """#2688-#2695 reproduction: a second batch wave must not open a second primary PR."""
    first_wave = evaluate_batch_primary_pr_packaging(
        issue_evidence=(issue(2688, "objective/lp4-zero-comparable-runs"),),
        evidence_current=True,
    )
    assert first_wave.packaging_admitted is True
    assert first_wave.per_issue_admissions[0][1].action is PrimaryPrCreationAction.CREATE_PRIMARY_PR

    second_wave = evaluate_batch_primary_pr_packaging(
        issue_evidence=(issue(2688, "objective/lp4-zero-comparable-runs", pr(2703)),),
        evidence_current=True,
    )
    assert second_wave.packaging_admitted is False
    assert second_wave.per_issue_admissions[0][1].action is PrimaryPrCreationAction.REUSE_EXISTING_PRIMARY_PR
    assert second_wave.per_issue_admissions[0][1].existing_pull_request_number == 2703
    assert second_wave.reason_codes == ("primary-pr.existing-active",)


def test_2447_a_different_branch_slug_never_admits_a_second_primary_pr() -> None:
    existing = ActivePrimaryPr(
        pull_request_number=2703,
        branch="agent/2688-lp-fix",
        head_sha="6" * 40,
    )
    result = evaluate_batch_primary_pr_packaging(
        issue_evidence=(
            BatchIssuePrimaryPrEvidence(
                issue_number=2688,
                issue_open=True,
                objective_ref="objective/lp4-zero-comparable-runs",
                active_primary_prs=(existing,),
            ),
        ),
        evidence_current=True,
    )
    assert result.packaging_admitted is False
    assert result.per_issue_admissions[0][1].existing_pull_request_number == 2703


def test_batch_packaging_rejects_stale_evidence_for_every_issue() -> None:
    result = evaluate_batch_primary_pr_packaging(
        issue_evidence=(
            issue(2442, "objective/shared"),
            issue(2443, "objective/shared"),
        ),
        evidence_current=False,
    )
    assert result.packaging_admitted is False
    assert result.reason_codes == ("primary-pr-evidence.stale",)


def test_batch_packaging_surfaces_multiple_active_primary_prs_for_reconciliation() -> None:
    result = evaluate_batch_primary_pr_packaging(
        issue_evidence=(issue(2695, "objective/lp4-observation-quality", pr(2710), pr(2722)),),
        evidence_current=True,
    )
    assert result.packaging_admitted is False
    assert result.per_issue_admissions[0][1].action is PrimaryPrCreationAction.MANUAL_RECONCILIATION
    assert result.reason_codes == ("primary-pr.multiple-active",)
