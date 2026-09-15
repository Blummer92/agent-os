from dataclasses import replace

from scripts.agent_os_issue_acceptance.bulk_repair_review_integration import (
    BulkRepairReviewInput,
    BulkReviewDisposition,
    evaluate_bulk_repair_review,
)
from scripts.agent_os_pr_remediation.review_coverage import (
    CoverageStatus,
    ReviewCoverageRecord,
)
from scripts.agent_os_pr_remediation.review_evidence import ReviewDepth, ReviewRiskEvidence


HEAD = "a" * 40
OLD = "b" * 40


def base(**changes):
    values = dict(
        repository="Blummer92/agent-os",
        issue_number=2417,
        pull_request_number=42,
        base_sha="c" * 40,
        head_sha=HEAD,
        objective="compose existing review evidence",
        acceptance_criteria=("current review required",),
        allowed_paths=("scripts/example.py",),
        forbidden_paths=(".github/workflows/",),
        non_goals=("no second reviewer",),
        authorization_ceiling=("repository-only",),
        changed_files=("scripts/example.py",),
        bounded_diff="+bounded change",
        change_kinds=("code",),
    )
    values.update(changes)
    return BulkRepairReviewInput(**values)


def coverage(status=CoverageStatus.EXAMINED_CLEAR):
    return ReviewCoverageRecord(
        attack_id="attack-1",
        reviewed_head_sha=HEAD,
        affected_surface_refs=("scripts/example.py",),
        review_execution_id="review-1",
        coverage_status=status,
        finding_ids=(),
        bounded_evidence_refs=("review:evidence",),
        reason_codes=(),
    )


def test_normal_review_requires_coverage_before_handoff():
    result = evaluate_bulk_repair_review(base())
    assert result.review_depth is ReviewDepth.NORMAL
    assert result.disposition is BulkReviewDisposition.REVIEW_REQUIRED
    assert result.handoff_to_br3 is False


def test_normal_review_with_clear_coverage_hands_to_br3():
    result = evaluate_bulk_repair_review(base(coverage=(coverage(),)))
    assert result.disposition is BulkReviewDisposition.CLEARED
    assert result.handoff_to_br3 is True
    assert result.merge_authorized is False


def test_no_ai_review_can_clear_without_duplicate_reviewer():
    result = evaluate_bulk_repair_review(
        base(code_changed=False, change_kinds=("markdown-only",))
    )
    assert result.review_depth is ReviewDepth.NO_AI
    assert result.disposition is BulkReviewDisposition.CLEARED


def test_adversarial_risk_uses_existing_depth_selector():
    result = evaluate_bulk_repair_review(
        base(
            risk_evidence=(ReviewRiskEvidence("authorization", ("authority seam changed",)),),
            coverage=(coverage(),),
        )
    )
    assert result.review_depth is ReviewDepth.ADVERSARIAL
    assert result.disposition is BulkReviewDisposition.CLEARED


def test_manual_risk_blocks_handoff():
    result = evaluate_bulk_repair_review(base(stale_or_conflicting_risk_evidence=True))
    assert result.review_depth is ReviewDepth.MANUAL
    assert result.disposition is BulkReviewDisposition.MANUAL_BLOCKED
    assert result.manual_review_required is True


def test_blocking_coverage_requires_review():
    result = evaluate_bulk_repair_review(
        base(coverage=(coverage(CoverageStatus.UNEXAMINED_BLOCKING),))
    )
    assert result.disposition is BulkReviewDisposition.REVIEW_REQUIRED
    assert result.blocking_coverage_ids


def test_new_head_invalidates_changed_reviewed_path():
    result = evaluate_bulk_repair_review(
        base(
            prior_reviewed_head=OLD,
            paths_changed_since_review=("scripts/example.py",),
            coverage=(coverage(),),
        )
    )
    assert result.disposition is BulkReviewDisposition.STALE
    assert result.invalidated_paths == ("scripts/example.py",)
    assert result.handoff_to_br3 is False


def test_full_review_invalidator_invalidates_reviewed_scope():
    result = evaluate_bulk_repair_review(
        base(
            prior_reviewed_head=OLD,
            paths_changed_since_review=("other.py",),
            material_change_kinds=("public-interface",),
            coverage=(coverage(),),
        )
    )
    assert result.disposition is BulkReviewDisposition.STALE
    assert result.invalidated_paths == ("scripts/example.py",)


def test_projection_is_non_authorizing():
    result = evaluate_bulk_repair_review(base(coverage=(coverage(),)))
    assert result.execution_authorized is False
    assert result.merge_authorized is False
    assert result.closure_authorized is False
    assert result.readiness_authorized is False
    assert result.production_authorized is False
    assert result.external_write_authorized is False
    assert result.side_effects_performed is False
