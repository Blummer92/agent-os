from __future__ import annotations

from scripts.agent_os_pr_remediation.merge_evidence_summary import (
    EvidenceStatus,
    MergeEvidenceStatus,
    PostMergeClassification,
    ReviewStatus,
    acceptance_evidence,
    ai_review_evidence,
    build_review_merge_evidence_summary,
    classify_post_merge_evidence,
    validation_evidence,
)

HEAD = "a" * 40
BASE = "b" * 40
SYNTHETIC = "c" * 40
MERGED = "d" * 40
OLD = "e" * 40
META = "1" * 64
NEW_META = "2" * 64


def acceptance(status: EvidenceStatus = EvidenceStatus.PASSED, *, fingerprint: str = META, current: str = META):
    return acceptance_evidence(
        transport_completed=True,
        status=status,
        metadata_fingerprint=fingerprint,
        current_metadata_fingerprint=current,
    )


def validation(name: str, status: EvidenceStatus = EvidenceStatus.PASSED, sha: str | None = HEAD):
    return validation_evidence(name=name, status=status, tested_sha=sha)


def review(
    status: ReviewStatus = ReviewStatus.PERFORMED_CLEAR,
    *,
    reviewed_sha: str | None = HEAD,
    unresolved=(),
    resolved=(),
    invalidated=(),
    provider: str = "provider-neutral",
):
    return ai_review_evidence(
        provider=provider,
        status=status,
        reviewed_sha=reviewed_sha,
        current_head_sha=HEAD,
        unresolved_finding_ids=unresolved,
        resolved_finding_ids=resolved,
        invalidated_finding_ids=invalidated,
    )


def summary(**overrides):
    payload = {
        "repository": "Blummer92/agent-os",
        "pr_number": 1540,
        "source_head_sha": HEAD,
        "base_sha": BASE,
        "synthetic_merge_sha": SYNTHETIC,
        "merge_commit_sha": None,
        "locally_tested_sha": HEAD,
        "acceptance": acceptance(),
        "focused_validation": [validation("focused")],
        "aggregate_validation": validation("aggregate"),
        "language_validation": [validation_evidence(name="language", status=EvidenceStatus.NOT_APPLICABLE)],
        "specialized_validation": [],
        "normal_review": review(),
        "adversarial_review": review(ReviewStatus.NOT_REQUIRED, reviewed_sha=None, provider="adversarial"),
    }
    payload.update(overrides)
    return build_review_merge_evidence_summary(**payload)


def test_workflow_transport_success_does_not_override_internal_acceptance_failure() -> None:
    result = summary(acceptance=acceptance(EvidenceStatus.FAILED))
    assert result.acceptance.transport_completed is True
    assert result.acceptance.status is EvidenceStatus.FAILED
    assert result.merge_evidence_status is MergeEvidenceStatus.BLOCKED


def test_provider_success_context_cannot_turn_explicit_skipped_review_clear() -> None:
    result = summary(normal_review=review(ReviewStatus.SKIPPED, reviewed_sha=None, provider="coderabbit"))
    assert result.normal_review.status is ReviewStatus.SKIPPED
    assert result.merge_evidence_status is MergeEvidenceStatus.INCOMPLETE


def test_quota_or_rate_limit_is_unavailable_not_reviewed_clear() -> None:
    result = summary(normal_review=review(ReviewStatus.UNAVAILABLE, reviewed_sha=None, provider="codex"))
    assert result.normal_review.status is ReviewStatus.UNAVAILABLE
    assert result.merge_evidence_status is MergeEvidenceStatus.INCOMPLETE


def test_review_on_prior_sha_is_stale_for_current_head() -> None:
    result = summary(normal_review=review(reviewed_sha=OLD))
    assert result.normal_review.status is ReviewStatus.STALE
    assert result.merge_evidence_status is MergeEvidenceStatus.STALE


def test_focused_and_aggregate_on_different_shas_never_form_exact_head_claim() -> None:
    result = summary(focused_validation=[validation("focused", sha=OLD)])
    assert result.merge_evidence_status is MergeEvidenceStatus.STALE
    assert "validation-stale:focused" in result.reason_codes


def test_synthetic_merge_sha_and_source_head_remain_distinct() -> None:
    result = summary()
    assert result.source_head_sha == HEAD
    assert result.synthetic_merge_sha == SYNTHETIC
    assert result.source_head_sha != result.synthetic_merge_sha


def test_merge_commit_is_not_retroactively_used_as_premerge_tested_head() -> None:
    result = summary(merge_commit_sha=MERGED)
    assert result.merge_commit_sha == MERGED
    assert result.aggregate_validation.tested_sha == HEAD


def test_resolved_finding_survives_when_not_invalidated() -> None:
    result = summary(normal_review=review(resolved=("finding-1",)))
    assert result.normal_review.status is ReviewStatus.PERFORMED_CLEAR
    assert result.normal_review.resolved_finding_ids == ("finding-1",)


def test_later_change_touching_finding_surface_invalidates_prior_clear_review() -> None:
    result = summary(normal_review=review(resolved=("finding-1",), invalidated=("finding-1",)))
    assert result.normal_review.status is ReviewStatus.STALE
    assert result.merge_evidence_status is MergeEvidenceStatus.STALE


def test_metadata_only_edit_stales_acceptance_without_staling_code_validation() -> None:
    result = summary(acceptance=acceptance(fingerprint=META, current=NEW_META))
    assert result.acceptance.status is EvidenceStatus.STALE
    assert result.aggregate_validation.status is EvidenceStatus.PASSED
    assert result.aggregate_validation.tested_sha == HEAD
    assert result.merge_evidence_status is MergeEvidenceStatus.STALE


def test_actual_merge_sha_run_can_be_independent_evidence() -> None:
    classification = classify_post_merge_evidence(
        run_sha=MERGED,
        pre_merge_source_head_sha=HEAD,
        merge_commit_sha=MERGED,
        newer_run_exists=False,
        duplicates_existing_proof=False,
        run_started_before_merge=False,
    )
    assert classification is PostMergeClassification.MERGE_SHA_INDEPENDENT_EVIDENCE


def test_stale_premerge_run_is_draining_not_new_merge_evidence() -> None:
    classification = classify_post_merge_evidence(
        run_sha=HEAD,
        pre_merge_source_head_sha=HEAD,
        merge_commit_sha=MERGED,
        newer_run_exists=False,
        duplicates_existing_proof=False,
        run_started_before_merge=True,
    )
    assert classification is PostMergeClassification.PRE_MERGE_RUN_DRAINING


def test_unresolved_findings_block_without_granting_authority() -> None:
    result = summary(normal_review=review(ReviewStatus.PERFORMED_BLOCKED, unresolved=("finding-2",)))
    assert result.unresolved_finding_ids == ("finding-2",)
    assert result.merge_evidence_status is MergeEvidenceStatus.BLOCKED
    assert result.execution_authorized is False
    assert result.merge_authorized is False
    assert result.closure_authorized is False
    assert result.production_authorized is False
    assert result.external_write_authorized is False
    assert result.side_effects_performed is False
