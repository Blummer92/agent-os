from __future__ import annotations

from agent_os_execution_service.coding_worker_contract import (
    CODING_WORKER_SCHEMA_VERSION,
    CodingWorkerOperation,
    CodingWorkerRequest,
    CodingWorkerResult,
    CodingWorkerStatus,
)

SHA = "a" * 40
PARTIAL_SHA = "b" * 40


def request(operation: CodingWorkerOperation = CodingWorkerOperation.IMPLEMENT) -> CodingWorkerRequest:
    return CodingWorkerRequest(
        schema_version=CODING_WORKER_SCHEMA_VERSION,
        task_id="task:2318",
        repository="Blummer92/agent-os",
        issue_or_handoff_identity="issue:2318",
        base_sha=SHA,
        workspace_identity="workspace:2318",
        operation=operation,
        implementation_packet_source_identity="implementation-packet-source:abc123",
        executor_handoff_id="executor-handoff:abc123",
        allowed_paths=("08_Tooling/agent-os-execution-service",),
        forbidden_paths=(".github/workflows",),
        validation_command_plan_id_or_none="command-plan:abc123",
    )


def worker_result(
    req: CodingWorkerRequest,
    *,
    status: CodingWorkerStatus,
    summary: str,
    files_changed: tuple[str, ...] = (),
    commands_run: tuple[str, ...] = (),
    tests_run: tuple[str, ...] = (),
    diagnostic_ids: tuple[str, ...] = (),
    blocked_reason_or_none: str | None = None,
    patch_identity_or_none: str | None = None,
    result_sha_or_none: str | None = None,
) -> CodingWorkerResult:
    return CodingWorkerResult(
        schema_version=CODING_WORKER_SCHEMA_VERSION,
        request_id=req.request_id,
        task_id=req.task_id,
        repository=req.repository,
        base_sha=req.base_sha,
        workspace_identity=req.workspace_identity,
        status=status,
        summary=summary,
        files_inspected=(),
        files_changed=files_changed,
        commands_run=commands_run,
        tests_run=tests_run,
        test_result_ids=(),
        diagnostic_ids=diagnostic_ids,
        assumption_ids=(),
        unresolved_question_ids=(),
        scope_violation_paths=(),
        blocked_reason_or_none=blocked_reason_or_none,
        patch_identity_or_none=patch_identity_or_none,
        result_sha_or_none=result_sha_or_none,
    )


def assert_non_authorizing(result: CodingWorkerResult) -> None:
    assert result.execution_authorized is False
    assert result.validation_authorized is False
    assert result.ready_for_review_authorized is False
    assert result.merge_authorized is False
    assert result.closure_authorized is False
    assert result.external_writes_authorized is False


def test_capability_mismatch_is_bounded_worker_evidence_not_a_second_router() -> None:
    req = request(CodingWorkerOperation.TEST)
    result = worker_result(
        req,
        status=CodingWorkerStatus.BLOCKED,
        summary="The selected execution surface cannot run the requested test operation.",
        diagnostic_ids=("executor-route:capability-mismatch",),
        blocked_reason_or_none="execution-capability-mismatch",
    )

    assert result.status is CodingWorkerStatus.BLOCKED
    assert result.files_changed == ()
    assert result.commands_run == ()
    assert result.tests_run == ()
    assert result.diagnostic_ids == ("executor-route:capability-mismatch",)
    assert_non_authorizing(result)


def test_partial_execution_failure_preserves_changed_path_and_patch_evidence() -> None:
    req = request(CodingWorkerOperation.IMPLEMENT)
    result = worker_result(
        req,
        status=CodingWorkerStatus.EXECUTION_FAILURE,
        summary="The worker failed after producing a bounded partial workspace change.",
        files_changed=(
            "08_Tooling/agent-os-execution-service/src/agent_os_execution_service/partial.py",
        ),
        commands_run=("focused-test-command",),
        diagnostic_ids=("worker-diagnostic:process-failed",),
        patch_identity_or_none="patch:partial123",
        result_sha_or_none=PARTIAL_SHA,
    )

    assert result.status is CodingWorkerStatus.EXECUTION_FAILURE
    assert result.files_changed
    assert result.patch_identity_or_none == "patch:partial123"
    assert result.result_sha_or_none == PARTIAL_SHA
    assert_non_authorizing(result)


def test_required_forbidden_path_change_returns_decision_evidence_without_editing() -> None:
    req = request(CodingWorkerOperation.IMPLEMENT)
    result = worker_result(
        req,
        status=CodingWorkerStatus.NEEDS_DECISION,
        summary="The requested implementation requires a separately governed workflow change.",
        diagnostic_ids=("scope:forbidden-path-required",),
        blocked_reason_or_none="forbidden-path-required",
    )

    assert result.status is CodingWorkerStatus.NEEDS_DECISION
    assert result.files_changed == ()
    assert result.patch_identity_or_none is None
    assert_non_authorizing(result)


def test_generated_regression_test_remains_worker_evidence_only() -> None:
    req = request(CodingWorkerOperation.GENERATE_REGRESSION_TEST)
    result = worker_result(
        req,
        status=CodingWorkerStatus.COMPLETED,
        summary="Generated one bounded regression-test change for downstream validation.",
        files_changed=(
            "08_Tooling/agent-os-execution-service/tests/test_generated_regression.py",
        ),
        tests_run=("generated-regression-test",),
        patch_identity_or_none="patch:regression123",
        result_sha_or_none=PARTIAL_SHA,
    )

    assert result.status is CodingWorkerStatus.COMPLETED
    assert req.operation is CodingWorkerOperation.GENERATE_REGRESSION_TEST
    assert_non_authorizing(result)
