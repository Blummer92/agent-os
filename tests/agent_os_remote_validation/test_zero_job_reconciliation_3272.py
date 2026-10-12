"""Focused reconciliation tests for the #3272 classifier binding (#3272 lane).

These tests pin the single canonical entry point
``reconcile_zero_job_run_evidence``: the EXISTING #3277 classifier
(``classify_workflow_run_evidence``) is applied to #3272's outstanding
lifecycle evidence, and the #3272 diagnostic is rendered per the
classifier's output. No classification logic is reimplemented here; the
tests prove the binding, the precedence, and the fail-closed shapes.

No test performs network I/O. Run evidence mirrors the recorded GitHub
workflow runs from #3272 (runs 37142321205 and 37142333162, both
completed/failure with zero jobs on
``.github/workflows/agent-os-validation.yml``).
"""
from __future__ import annotations

import pytest

from scripts.agent_os_issue_acceptance.zero_job_validation_recovery import (
    WorkflowRunConclusionEvidence,
)
from scripts.agent_os_remote_validation.zero_job_definition_diagnostic import (
    ZeroJobDiagnosticKind,
    reconcile_zero_job_run_evidence,
)

WORKFLOW_PATH = ".github/workflows/agent-os-validation.yml"


def _run(run_id: int, conclusion: str | None, job_count: int) -> WorkflowRunConclusionEvidence:
    return WorkflowRunConclusionEvidence(
        run_id=run_id, conclusion=conclusion, job_count=job_count
    )


def test_3272_full_reproduction_reconciles_to_pre_job_rejection():
    # Both runs recorded in #3272's reproduction: completed/failure + 0 jobs.
    runs = (
        _run(37142321205, "failure", 0),
        _run(37142333162, "failure", 0),
    )
    diagnostic = reconcile_zero_job_run_evidence(
        runs, workflow_path=WORKFLOW_PATH, workflow_name=WORKFLOW_PATH
    )

    assert diagnostic.kind is ZeroJobDiagnosticKind.PRE_JOB_DEFINITION_REJECTION
    assert "diagnostic.pre-job-failure-proven" in diagnostic.reason_codes
    assert "diagnostic.redispatch-cannot-clear" in diagnostic.reason_codes
    assert "diagnostic.parser-diagnostic-not-proven" in diagnostic.reason_codes

    proven = "\n".join(diagnostic.proven)
    assert "zero jobs executed" in proven
    assert "no test code ran" in proven  # never a candidate code-test failure

    not_proven = "\n".join(diagnostic.not_proven)
    assert "never inferred" in not_proven  # GitHub's parser message is not invented

    action = diagnostic.recommended_action
    assert WORKFLOW_PATH in action
    assert "do not treat" in action and "code-test failure" in action
    assert "do not re-dispatch" in action


def test_pending_zero_jobs_reconciles_to_currentness_delegation():
    # The #3269 shape: pending + 0 jobs delegates, never duplicated.
    runs = (_run(37134507655, None, 0),)
    diagnostic = reconcile_zero_job_run_evidence(runs, workflow_path=WORKFLOW_PATH)

    assert diagnostic.kind is ZeroJobDiagnosticKind.CURRENTNESS_DELEGATED
    assert "diagnostic.delegated-to-currentness-path" in diagnostic.reason_codes
    assert "diagnostic.pre-job-failure-proven" not in diagnostic.reason_codes
    assert "3269" in diagnostic.recommended_action


def test_executed_failure_reconciles_to_ordinary_test_failure():
    runs = (_run(37142333162, "failure", 3),)
    diagnostic = reconcile_zero_job_run_evidence(runs)

    assert diagnostic.kind is ZeroJobDiagnosticKind.ORDINARY_TEST_FAILURE
    assert "diagnostic.executed-failure-observed" in diagnostic.reason_codes
    assert "diagnostic.pre-job-failure-proven" not in diagnostic.reason_codes


def test_mixed_evidence_renders_classifier_precedence():
    # The existing classifier gives executed failure precedence over the
    # pre-job shape; the binding must render the classifier's verdict,
    # never re-decide precedence itself.
    runs = (
        _run(37142333162, "failure", 0),
        _run(37142340000, "failure", 2),
    )
    diagnostic = reconcile_zero_job_run_evidence(runs)

    assert diagnostic.kind is ZeroJobDiagnosticKind.ORDINARY_TEST_FAILURE


def test_indeterminate_shape_fails_closed_with_no_action():
    runs = (_run(1, "stale", 0),)
    diagnostic = reconcile_zero_job_run_evidence(runs)

    assert diagnostic.kind is ZeroJobDiagnosticKind.INDETERMINATE
    assert "diagnostic.insufficient-evidence" in diagnostic.reason_codes
    assert diagnostic.recommended_action == ""


def test_empty_evidence_fails_closed_with_no_action():
    diagnostic = reconcile_zero_job_run_evidence(())

    assert diagnostic.kind is ZeroJobDiagnosticKind.INDETERMINATE
    assert diagnostic.recommended_action == ""


def test_rejects_non_tuple_input():
    runs = (_run(37142333162, "failure", 0),)
    with pytest.raises(TypeError):
        reconcile_zero_job_run_evidence([runs[0]])  # type: ignore[arg-type]


def test_rejects_non_evidence_elements():
    with pytest.raises(TypeError):
        reconcile_zero_job_run_evidence(("not-evidence",))  # type: ignore[arg-type]
