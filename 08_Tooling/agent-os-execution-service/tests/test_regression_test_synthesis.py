from __future__ import annotations

import pytest

from agent_os_execution_service.coding_worker_contract import (
    CODING_WORKER_SCHEMA_VERSION,
    CodingWorkerOperation,
    CodingWorkerRequest,
    CodingWorkerResult,
    CodingWorkerStatus,
)
from agent_os_execution_service.regression_test_synthesis import (
    RegressionTestDecision,
    decide_regression_test_need,
    validate_generated_regression_result,
)

SHA = "a" * 40


def worker_request(**overrides: object) -> CodingWorkerRequest:
    values: dict[str, object] = {
        "schema_version": CODING_WORKER_SCHEMA_VERSION,
        "task_id": "task:2315",
        "repository": "Blummer92/agent-os",
        "issue_or_handoff_identity": "issue:2315",
        "base_sha": SHA,
        "workspace_identity": "workspace:2315",
        "operation": CodingWorkerOperation.GENERATE_REGRESSION_TEST,
        "implementation_packet_source_identity": "implementation-packet-source:2315",
        "executor_handoff_id": "executor-handoff:2315",
        "allowed_paths": ("08_Tooling/agent-os-execution-service/tests",),
        "forbidden_paths": (".github/workflows",),
    }
    values.update(overrides)
    return CodingWorkerRequest(**values)


def worker_result(request: CodingWorkerRequest, **overrides: object) -> CodingWorkerResult:
    values: dict[str, object] = {
        "schema_version": CODING_WORKER_SCHEMA_VERSION,
        "request_id": request.request_id,
        "task_id": request.task_id,
        "repository": request.repository,
        "base_sha": request.base_sha,
        "workspace_identity": request.workspace_identity,
        "status": CodingWorkerStatus.COMPLETED,
        "summary": "Generated one bounded regression test.",
        "files_inspected": ("08_Tooling/agent-os-execution-service/tests/test_existing.py",),
        "files_changed": ("08_Tooling/agent-os-execution-service/tests/test_bug_2315.py",),
        "commands_run": ("pytest-focused",),
        "tests_run": ("test-bug-2315",),
        "test_result_ids": ("test-result:2315",),
        "diagnostic_ids": (),
        "assumption_ids": (),
        "unresolved_question_ids": (),
        "scope_violation_paths": (),
        "blocked_reason_or_none": None,
        "patch_identity_or_none": "patch:2315",
        "result_sha_or_none": "b" * 40,
    }
    values.update(overrides)
    return CodingWorkerResult(**values)


def test_clear_bug_without_regression_requires_one_test() -> None:
    evidence = decide_regression_test_need(
        behavior_changed=True,
        behavioral_requirement_id="acceptance:bug-reproduction",
    )
    assert evidence.decision is RegressionTestDecision.REGRESSION_TEST_REQUIRED


def test_exact_existing_regression_avoids_duplicate_test() -> None:
    evidence = decide_regression_test_need(
        behavior_changed=True,
        behavioral_requirement_id="acceptance:bug-reproduction",
        existing_exact_test_ids=("test:existing-regression",),
    )
    assert evidence.decision is RegressionTestDecision.EXISTING_TEST_SUFFICIENT
    assert evidence.existing_test_ids == ("test:existing-regression",)


def test_indirect_existing_coverage_is_sufficient() -> None:
    evidence = decide_regression_test_need(
        behavior_changed=True,
        behavioral_requirement_id="acceptance:bounded-behavior",
        existing_indirect_test_ids=("test:behavior-contract",),
    )
    assert evidence.decision is RegressionTestDecision.EXISTING_TEST_SUFFICIENT


def test_non_behavioral_refactor_does_not_generate_test() -> None:
    evidence = decide_regression_test_need(
        behavior_changed=False,
        behavioral_requirement_id="acceptance:no-behavior-change",
    )
    assert evidence.decision is RegressionTestDecision.TEST_NOT_NEEDED


@pytest.mark.parametrize(
    "unsafe",
    [
        {"expectation_is_ambiguous": True},
        {"canonical_test_surface_is_ambiguous": True},
        {"requires_forbidden_external_io": True},
        {"test_path_within_scope": False},
    ],
)
def test_unsafe_or_ambiguous_cases_fail_closed(unsafe: dict[str, bool]) -> None:
    evidence = decide_regression_test_need(
        behavior_changed=True,
        behavioral_requirement_id="acceptance:bug-reproduction",
        **unsafe,
    )
    assert evidence.decision is RegressionTestDecision.TEST_SYNTHESIS_UNSAFE_OR_AMBIGUOUS


def test_missing_behavior_anchor_fails_closed() -> None:
    evidence = decide_regression_test_need(behavior_changed=True, behavioral_requirement_id=None)
    assert evidence.decision is RegressionTestDecision.TEST_SYNTHESIS_UNSAFE_OR_AMBIGUOUS


def test_generated_test_reuses_coding_worker_contract_and_stays_in_scope() -> None:
    request = worker_request()
    decision = decide_regression_test_need(
        behavior_changed=True,
        behavioral_requirement_id="acceptance:bug-reproduction",
    )
    evidence = validate_generated_regression_result(
        request=request,
        result=worker_result(request),
        evidence=decision,
    )
    assert evidence.generated_test_paths == (
        "08_Tooling/agent-os-execution-service/tests/test_bug_2315.py",
    )


def test_stale_worker_result_is_rejected() -> None:
    request = worker_request()
    other = worker_request(base_sha="c" * 40)
    decision = decide_regression_test_need(
        behavior_changed=True,
        behavioral_requirement_id="acceptance:bug-reproduction",
    )
    with pytest.raises(ValueError, match="stale or belongs to another request"):
        validate_generated_regression_result(
            request=request,
            result=worker_result(other),
            evidence=decision,
        )


def test_scope_violation_is_rejected_before_regression_evidence_is_accepted() -> None:
    request = worker_request()
    decision = decide_regression_test_need(
        behavior_changed=True,
        behavioral_requirement_id="acceptance:bug-reproduction",
    )
    result = worker_result(request, files_changed=("scripts/outside_scope_test.py",))
    with pytest.raises(ValueError, match="exceeds allowed scope"):
        validate_generated_regression_result(request=request, result=result, evidence=decision)


def test_worker_authority_remains_false_for_generated_test_result() -> None:
    request = worker_request()
    result = worker_result(request)
    assert result.validation_authorized is False
    assert result.ready_for_review_authorized is False
    assert result.merge_authorized is False
    assert result.closure_authorized is False
    assert result.external_writes_authorized is False
