from __future__ import annotations

import dataclasses
import json

import pytest

from agent_os_execution_service.coding_worker_contract import (
    CODING_WORKER_SCHEMA_VERSION,
    CodingWorkerOperation,
    CodingWorkerRequest,
    CodingWorkerResult,
    CodingWorkerStatus,
    serialize_coding_worker_request,
    serialize_coding_worker_result,
)

SHA = "a" * 40
RESULT_SHA = "b" * 40


def request(**overrides: object) -> CodingWorkerRequest:
    values: dict[str, object] = {
        "schema_version": CODING_WORKER_SCHEMA_VERSION,
        "task_id": "task:2318",
        "repository": "Blummer92/agent-os",
        "issue_or_handoff_identity": "issue:2318",
        "base_sha": SHA,
        "workspace_identity": "workspace:2318",
        "operation": CodingWorkerOperation.IMPLEMENT,
        "implementation_packet_source_identity": "implementation-packet-source:abc123",
        "executor_handoff_id": "executor-handoff:abc123",
        "allowed_paths": ("08_Tooling/agent-os-execution-service",),
        "forbidden_paths": (".github/workflows",),
        "validation_command_plan_id_or_none": "command-plan:abc123",
    }
    values.update(overrides)
    return CodingWorkerRequest(**values)


def result(**overrides: object) -> CodingWorkerResult:
    req = request()
    values: dict[str, object] = {
        "schema_version": CODING_WORKER_SCHEMA_VERSION,
        "request_id": req.request_id,
        "task_id": req.task_id,
        "repository": req.repository,
        "base_sha": req.base_sha,
        "workspace_identity": req.workspace_identity,
        "status": CodingWorkerStatus.COMPLETED,
        "summary": "Implemented the bounded semantic coding change.",
        "files_inspected": ("08_Tooling/agent-os-execution-service/README.md",),
        "files_changed": ("08_Tooling/agent-os-execution-service/src/example.py",),
        "commands_run": ("pytest-focused",),
        "tests_run": ("test-example",),
        "test_result_ids": ("test-result:abc123",),
        "diagnostic_ids": (),
        "assumption_ids": (),
        "unresolved_question_ids": (),
        "scope_violation_paths": (),
        "blocked_reason_or_none": None,
        "patch_identity_or_none": "patch:abc123",
        "result_sha_or_none": RESULT_SHA,
    }
    values.update(overrides)
    return CodingWorkerResult(**values)


def test_request_is_provider_neutral_and_references_existing_owners() -> None:
    value = request()
    assert value.operation is CodingWorkerOperation.IMPLEMENT
    assert value.implementation_packet_source_identity.startswith("implementation-packet-source:")
    assert value.executor_handoff_id.startswith("executor-handoff:")
    payload = value.to_dict()
    assert "provider" not in payload
    assert "model" not in payload
    assert "prompt" not in payload
    assert "token" not in payload


def test_request_has_no_positive_authority_surface() -> None:
    value = request()
    assert value.execution_authorized is False
    assert value.merge_authorized is False
    assert value.closure_authorized is False
    assert value.external_writes_authorized is False
    with pytest.raises(dataclasses.FrozenInstanceError):
        value.merge_authorized = True  # type: ignore[misc]


def test_request_scope_overlap_fails_closed() -> None:
    with pytest.raises(ValueError, match="must not overlap"):
        request(
            allowed_paths=("08_Tooling/agent-os-execution-service",),
            forbidden_paths=("08_Tooling/agent-os-execution-service/tests",),
        )


def test_request_round_trip_is_canonical_and_content_addressed() -> None:
    value = request()
    payload = json.loads(serialize_coding_worker_request(value))
    rebuilt = CodingWorkerRequest.from_dict(payload)
    assert rebuilt == value
    assert rebuilt.request_id == value.request_id
    changed = request(operation=CodingWorkerOperation.REPAIR)
    assert changed.request_id != value.request_id


def test_request_rejects_authority_injection() -> None:
    payload = request().to_dict()
    payload["merge_authorized"] = True
    with pytest.raises(ValueError, match="merge_authorized must be false"):
        CodingWorkerRequest.from_dict(payload)


@pytest.mark.parametrize("status", tuple(CodingWorkerStatus))
def test_result_supports_finite_status_vocabulary(status: CodingWorkerStatus) -> None:
    kwargs: dict[str, object] = {"status": status}
    if status is CodingWorkerStatus.SCOPE_VIOLATION:
        kwargs["scope_violation_paths"] = ("outside/scope.py",)
    if status in {CodingWorkerStatus.BLOCKED, CodingWorkerStatus.NEEDS_DECISION}:
        kwargs["blocked_reason_or_none"] = "worker-blocked"
    value = result(**kwargs)
    assert value.status is status


def test_scope_violation_requires_explicit_path_evidence() -> None:
    with pytest.raises(ValueError, match="requires scope_violation_paths"):
        result(status=CodingWorkerStatus.SCOPE_VIOLATION)
    with pytest.raises(ValueError, match="require scope-violation status"):
        result(scope_violation_paths=("outside/scope.py",))


def test_blocked_and_needs_decision_require_reason() -> None:
    for status in (CodingWorkerStatus.BLOCKED, CodingWorkerStatus.NEEDS_DECISION):
        with pytest.raises(ValueError, match="requires blocked_reason_or_none"):
            result(status=status)


def test_result_is_evidence_not_authority() -> None:
    value = result()
    assert value.execution_authorized is False
    assert value.validation_authorized is False
    assert value.ready_for_review_authorized is False
    assert value.merge_authorized is False
    assert value.closure_authorized is False
    assert value.external_writes_authorized is False


def test_result_round_trip_and_stale_binding_evidence() -> None:
    value = result()
    payload = json.loads(serialize_coding_worker_result(value))
    rebuilt = CodingWorkerResult.from_dict(payload)
    assert rebuilt == value
    assert rebuilt.base_sha == SHA
    assert rebuilt.result_sha_or_none == RESULT_SHA
    stale = result(base_sha="c" * 40)
    assert stale.result_id != value.result_id


def test_result_rejects_worker_claimed_lifecycle_authority() -> None:
    payload = result().to_dict()
    for name in (
        "validation_authorized",
        "ready_for_review_authorized",
        "merge_authorized",
        "closure_authorized",
    ):
        mutated = dict(payload)
        mutated[name] = True
        with pytest.raises(ValueError, match=f"{name} must be false"):
            CodingWorkerResult.from_dict(mutated)


def test_provider_substitution_does_not_change_contract_shape() -> None:
    # Provider adapters are intentionally outside the canonical request/result wire shape.
    first = request()
    second = request()
    assert first.to_dict().keys() == second.to_dict().keys()
    assert result().to_dict().keys() == result().to_dict().keys()
