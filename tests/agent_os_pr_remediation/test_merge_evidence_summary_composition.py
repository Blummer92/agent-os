from __future__ import annotations

import pytest

from scripts.agent_os_pr_remediation.aggregate_failure_provenance import (
    AggregateFailureProvenance,
    AggregateFailureEvidence,
)
from scripts.agent_os_pr_remediation.ci_evidence_recovery import (
    CIEvidenceIdentity,
    CIEvidenceRecoveryPlan,
)
from scripts.agent_os_pr_remediation.merge_evidence_summary import (
    EvidenceStatus,
    ReviewStatus,
    acceptance_evidence,
    ai_review_evidence,
    build_review_merge_evidence_summary,
    compose_repair_evidence,
    validation_evidence,
)
from scripts.agent_os_pr_remediation.models import EvidenceValidationError

HEAD = "a" * 40
BASE = "b" * 40
META = "1" * 64


def _summary():
    return build_review_merge_evidence_summary(
        repository="Blummer92/agent-os",
        pr_number=1540,
        source_head_sha=HEAD,
        base_sha=BASE,
        synthetic_merge_sha=None,
        merge_commit_sha=None,
        locally_tested_sha=HEAD,
        acceptance=acceptance_evidence(
            transport_completed=True,
            status=EvidenceStatus.PASSED,
            metadata_fingerprint=META,
            current_metadata_fingerprint=META,
        ),
        focused_validation=[],
        aggregate_validation=validation_evidence(
            name="aggregate", status=EvidenceStatus.FAILED, tested_sha=HEAD
        ),
        language_validation=[],
        specialized_validation=[],
        normal_review=ai_review_evidence(
            provider="CodeRabbit",
            status=ReviewStatus.SKIPPED,
            reviewed_sha=None,
            current_head_sha=HEAD,
        ),
        adversarial_review=ai_review_evidence(
            provider="Codex",
            status=ReviewStatus.UNAVAILABLE,
            reviewed_sha=None,
            current_head_sha=HEAD,
            reason_codes=("rate-limited",),
        ),
    )


def _ci(*, head=HEAD):
    identity = CIEvidenceIdentity(
        repository="Blummer92/agent-os", pr_number=1540, head_sha=head,
        run_id=10, run_attempt=1, job_id=20,
    )
    return CIEvidenceRecoveryPlan(
        identity=identity,
        current_head_sha=head,
        current_run_attempt=1,
        attempted_paths=("structured",),
        next_path="direct-actions-log",
        reason_codes=("run-log-unavailable",),
        actionable_failure="FAILED tests/test_widget.py::test_case\nAssertionError: expected safe state",
        evidence_usable_for_attribution=True,
        retry_count=0,
        retry_limit=2,
        user_handoff_required=False,
    )


def _aggregate(*, head=HEAD):
    return AggregateFailureEvidence(
        provenance=AggregateFailureProvenance.PR_ATTRIBUTABLE,
        tested_sha=head,
        current_head_sha=head,
        main_sha=BASE,
        failure_fingerprint="pytest:test_case",
        blocking_pr_failure=True,
        requires_manual_review=False,
        reason_codes=("changed-contract-reaches-failure",),
    )


def test_composes_canonical_ci_and_provenance_without_reclassifying():
    result = compose_repair_evidence(
        _summary(), ci_recovery=_ci(), aggregate_failure=_aggregate(),
        post_repair_validation=("focused", "aggregate"),
    )
    assert result.actionable_failure.startswith("FAILED tests/test_widget.py")
    assert result.aggregate_failure_provenance == "pr-attributable"
    assert result.aggregate_failure_blocking_pr is True
    assert result.aggregate_failure_requires_manual_review is False
    assert result.next_diagnostic_path == "direct-actions-log"
    assert result.post_repair_validation == ("aggregate", "focused")
    assert result.execution_authorized is False
    assert result.external_write_authorized is False


def test_render_preserves_skipped_and_rate_limited_review_truth():
    rendered = compose_repair_evidence(
        _summary(), ci_recovery=_ci(), aggregate_failure=_aggregate()
    ).rendered_summary
    assert "normal: skipped" in rendered
    assert "adversarial: unavailable" in rendered
    assert "performed-clear" not in rendered
    assert "aggregate provenance: pr-attributable" in rendered
    assert "actionable failure (sanitized canonical evidence)" in rendered
    assert "next diagnostic route: direct-actions-log" in rendered
    assert "fix this" not in rendered.lower()


def test_stale_ci_evidence_fails_closed():
    with pytest.raises(EvidenceValidationError, match="CI recovery evidence is not current"):
        compose_repair_evidence(_summary(), ci_recovery=_ci(head="c" * 40))


def test_mismatched_aggregate_tested_sha_fails_closed():
    with pytest.raises(EvidenceValidationError, match="aggregate tested SHA"):
        compose_repair_evidence(_summary(), aggregate_failure=_aggregate(head="c" * 40))


def test_composition_rejects_authorizing_upstream_evidence():
    evidence = AggregateFailureEvidence(
        provenance=AggregateFailureProvenance.PR_ATTRIBUTABLE,
        tested_sha=HEAD,
        current_head_sha=HEAD,
        main_sha=BASE,
        failure_fingerprint="pytest:test_case",
        blocking_pr_failure=True,
        requires_manual_review=False,
        reason_codes=(),
        merge_authorized=True,
    )
    with pytest.raises(EvidenceValidationError, match="non-authorizing"):
        compose_repair_evidence(_summary(), aggregate_failure=evidence)
