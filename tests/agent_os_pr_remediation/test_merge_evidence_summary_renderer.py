from __future__ import annotations

import pytest

from scripts.agent_os_pr_remediation.merge_evidence_summary import (
    MAX_RENDERED_SUMMARY_CHARS,
    EvidenceStatus,
    ReviewStatus,
    acceptance_evidence,
    ai_review_evidence,
    build_review_merge_evidence_summary,
    render_review_merge_evidence_summary,
    validation_evidence,
)
from scripts.agent_os_pr_remediation.models import EvidenceValidationError

HEAD = "a" * 40
BASE = "b" * 40
SYNTHETIC = "c" * 40
META = "1" * 64


def _summary(*, aggregate_status=EvidenceStatus.PASSED, normal_status=ReviewStatus.PERFORMED_CLEAR, findings=()):
    acceptance = acceptance_evidence(
        transport_completed=True,
        status=EvidenceStatus.PASSED,
        metadata_fingerprint=META,
        current_metadata_fingerprint=META,
    )
    aggregate = validation_evidence(name="aggregate", status=aggregate_status, tested_sha=HEAD)
    normal = ai_review_evidence(
        provider="provider-neutral",
        status=normal_status,
        reviewed_sha=HEAD if normal_status not in {ReviewStatus.SKIPPED, ReviewStatus.UNAVAILABLE} else None,
        current_head_sha=HEAD,
        unresolved_finding_ids=findings,
    )
    adversarial = ai_review_evidence(
        provider="adversarial",
        status=ReviewStatus.NOT_REQUIRED,
        reviewed_sha=None,
        current_head_sha=HEAD,
    )
    return build_review_merge_evidence_summary(
        repository="Blummer92/agent-os",
        pr_number=1540,
        source_head_sha=HEAD,
        base_sha=BASE,
        synthetic_merge_sha=SYNTHETIC,
        merge_commit_sha=None,
        locally_tested_sha=HEAD,
        acceptance=acceptance,
        focused_validation=[validation_evidence(name="focused", status=EvidenceStatus.PASSED, tested_sha=HEAD)],
        aggregate_validation=aggregate,
        language_validation=[validation_evidence(name="typescript", status=EvidenceStatus.NOT_APPLICABLE)],
        specialized_validation=[],
        normal_review=normal,
        adversarial_review=adversarial,
    )


def test_renderer_is_deterministic_bounded_and_non_authorizing():
    summary = _summary()
    first = render_review_merge_evidence_summary(summary)
    second = summary.rendered_summary
    assert first == second
    assert len(first) <= MAX_RENDERED_SUMMARY_CHARS
    assert f"Head: {HEAD[:12]} — CURRENT SUMMARY IDENTITY" in first
    assert "Evidence state: COMPLETE" in first
    assert "issue acceptance: passed" in first
    assert "aggregate: passed" in first
    assert "normal: performed-clear" in first
    assert "does not authorize readiness, approval, merge, closure, execution, production, or external writes" in first


def test_failed_validation_is_visible_without_becoming_repair_advice():
    rendered = _summary(aggregate_status=EvidenceStatus.FAILED).rendered_summary
    assert "Evidence state: BLOCKED" in rendered
    assert "aggregate: failed" in rendered
    assert "validation-failed:aggregate" in rendered
    assert "fix" not in rendered.lower()


def test_skipped_review_is_explicit_not_rendered_as_clear():
    rendered = _summary(normal_status=ReviewStatus.SKIPPED).rendered_summary
    assert "normal: skipped" in rendered
    assert "performed-clear" not in rendered
    assert "Evidence state: INCOMPLETE" in rendered


def test_unresolved_findings_are_bounded_for_mobile_projection():
    findings = tuple(f"finding-{index:02d}" for index in range(12))
    rendered = _summary(normal_status=ReviewStatus.PERFORMED_BLOCKED, findings=findings).rendered_summary
    assert "finding-00" in rendered
    assert "finding-07" in rendered
    assert "finding-08" not in rendered
    assert "(+4 more)" in rendered
    assert "Evidence state: BLOCKED" in rendered


def test_renderer_rejects_wrong_input_type():
    with pytest.raises(EvidenceValidationError):
        render_review_merge_evidence_summary({})
