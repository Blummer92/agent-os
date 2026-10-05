"""Fixture-first characterization tests for the #3272 zero-job diagnostic.

These tests encode the three evidence shapes from recorded GitHub workflow
runs and pin the diagnostic contract BEFORE the implementation exists:

- completed/failure + zero jobs  -> workflow-definition/pre-job rejection
- pending + zero jobs             -> delegate to the #3269 currentness path
- completed/failure + jobs       -> ordinary candidate test failure

No test performs network I/O. All run evidence comes from the JSON fixtures
under tests/agent_os_remote_validation/fixtures/, recorded from live GitHub
workflow runs (see fixture notes).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.agent_os_issue_acceptance.zero_job_validation_recovery import (
    WorkflowRunConclusionEvidence,
    ZeroJobRunDisposition,
    classify_workflow_run_evidence,
)
from scripts.agent_os_remote_validation.zero_job_definition_diagnostic import (
    ZeroJobDiagnosticInput,
    ZeroJobDiagnosticKind,
    diagnose_zero_job_run,
    serialize_zero_job_definition_diagnostic,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    with open(FIXTURES / name, encoding="utf-8") as handle:
        return json.load(handle)


def _evidence_from_fixture(fixture: dict) -> tuple[WorkflowRunConclusionEvidence, ...]:
    return tuple(
        WorkflowRunConclusionEvidence(
            run_id=int(run["run_id"]),
            conclusion=run["conclusion"],
            job_count=int(run["job_count"]),
        )
        for run in fixture["runs"]
    )


def _diagnose_fixture(name: str):
    fixture = _load_fixture(name)
    runs = _evidence_from_fixture(fixture)
    disposition = classify_workflow_run_evidence(runs)
    assert disposition.value == fixture["expected_disposition"], (
        f"fixture {name}: existing classifier returned {disposition.value}, "
        f"expected {fixture['expected_disposition']}"
    )
    diagnostic_input = ZeroJobDiagnosticInput(
        disposition=disposition,
        runs=runs,
        workflow_path=fixture.get("workflow_path"),
        workflow_name=fixture.get("workflow_name"),
    )
    return diagnose_zero_job_run(diagnostic_input), fixture


def test_pre_job_failure_shape_renders_actionable_diagnostic():
    diagnostic, fixture = _diagnose_fixture("zero_job_pre_job_failure.json")

    assert diagnostic.kind is ZeroJobDiagnosticKind.PRE_JOB_DEFINITION_REJECTION
    assert "diagnostic.pre-job-failure-proven" in diagnostic.reason_codes
    assert "diagnostic.redispatch-cannot-clear" in diagnostic.reason_codes

    proven = "\n".join(diagnostic.proven)
    assert "zero jobs executed" in proven
    assert "no test code ran" in proven

    not_proven = "\n".join(diagnostic.not_proven)
    assert "parser" in not_proven  # never infer GitHub's parser diagnostics

    action = diagnostic.recommended_action
    assert fixture["workflow_path"] in action  # names the workflow to inspect
    assert "do not treat" in action and "code-test failure" in action

    # The diagnostic is connector-facing: it must serialize deterministically
    # for the evidence bundle.
    first = serialize_zero_job_definition_diagnostic(diagnostic)
    second = serialize_zero_job_definition_diagnostic(diagnostic)
    assert json.loads(first) == json.loads(second)
    assert json.loads(first)["kind"] == "pre-job-definition-rejection"


def test_pending_zero_jobs_delegates_to_currentness_path():
    diagnostic, _ = _diagnose_fixture("zero_job_pending_currentness.json")

    assert diagnostic.kind is ZeroJobDiagnosticKind.CURRENTNESS_DELEGATED
    assert "diagnostic.delegated-to-currentness-path" in diagnostic.reason_codes
    # The #3269 currentness logic must not be duplicated here: the diagnostic
    # only names the delegation target.
    assert "3269" in diagnostic.recommended_action
    assert "diagnostic.pre-job-failure-proven" not in diagnostic.reason_codes


def test_ordinary_failure_with_jobs_is_test_failure():
    diagnostic, _ = _diagnose_fixture("zero_job_ordinary_failure.json")

    assert diagnostic.kind is ZeroJobDiagnosticKind.ORDINARY_TEST_FAILURE
    assert "diagnostic.executed-failure-observed" in diagnostic.reason_codes
    assert "diagnostic.pre-job-failure-proven" not in diagnostic.reason_codes


def test_indeterminate_disposition_fails_closed():
    runs = (
        WorkflowRunConclusionEvidence(run_id=1, conclusion="stale", job_count=0),
    )
    disposition = classify_workflow_run_evidence(runs)
    assert disposition is ZeroJobRunDisposition.INDETERMINATE

    diagnostic = diagnose_zero_job_run(
        ZeroJobDiagnosticInput(disposition=disposition, runs=runs)
    )
    assert diagnostic.kind is ZeroJobDiagnosticKind.INDETERMINATE
    assert "diagnostic.insufficient-evidence" in diagnostic.reason_codes
    # Fail-closed: no recommended repair action is emitted for unknown shapes.
    assert diagnostic.recommended_action == ""


def test_malformed_input_is_rejected():
    runs = (
        WorkflowRunConclusionEvidence(run_id=1, conclusion="failure", job_count=0),
    )
    with pytest.raises(TypeError):
        ZeroJobDiagnosticInput(
            disposition="pre-job-failure",  # type: ignore[arg-type]
            runs=runs,
        )
    with pytest.raises(TypeError):
        ZeroJobDiagnosticInput(
            disposition=ZeroJobRunDisposition.PRE_JOB_FAILURE,
            runs=[runs[0]],  # type: ignore[arg-type]
        )


def test_mixed_precedence_renders_classifier_result():
    # The existing classifier gives executed failure precedence over the
    # pre-job shape; the diagnostic must render the classifier's verdict,
    # never re-decide precedence itself.
    runs = (
        WorkflowRunConclusionEvidence(run_id=1, conclusion="failure", job_count=0),
        WorkflowRunConclusionEvidence(run_id=2, conclusion="failure", job_count=2),
    )
    disposition = classify_workflow_run_evidence(runs)
    assert disposition is ZeroJobRunDisposition.REAL_FAILURE
    diagnostic = diagnose_zero_job_run(
        ZeroJobDiagnosticInput(disposition=disposition, runs=runs)
    )
    assert diagnostic.kind is ZeroJobDiagnosticKind.ORDINARY_TEST_FAILURE
