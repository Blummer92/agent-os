import json
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from workflow_scheduler.adapters.instructional_materials_contract import (
    MAX_RECEIPT_BYTES,
    validate_instructional_materials_contract,
)
from workflow_scheduler.models import ExecutionContext, ExecutionRequest


def _payload():
    return {
        "contract_version": "imc-materials-task-v1",
        "operation": "build_materials_bundle",
        "dry_run": True,
        "execution_authorized": False,
        "content_path": "lessons/unit-1.yaml",
        "slides_template_id": "slides-template_123",
        "doc_template_id": "doc-template_123",
        "target_drive_folder_id": "folder_123",
        "lessons_dir": "reports/lessons",
        "production_gates": {
            "source_confidence": "approved",
            "unit_readiness": "ready",
            "modeling_readiness": "ready_for_slides",
            "evidence_target": "modeling-handoff-123",
            "blockers": "none",
        },
        "governed_field_risk": False,
        "writes_governed_field": False,
    }


def _request(**overrides):
    values = {
        "task_id": "build-materials-bundle",
        "workflow_id": "classroom-artifact-dry-run-v1",
        "owner": "instructional-materials-coach",
        "payload": _payload(),
        "idempotency_key": "operator-key-123",
        "mode": "Draft",
        "approval_required": False,
        "production_ready": False,
        "execution_id": "exec-1",
        "run_id": "run-1",
        "attempt_number": 1,
        "created_at": datetime(2026, 8, 15, tzinfo=timezone.utc),
        "execution_context": ExecutionContext(),
        "batch_id": None,
    }
    values.update(overrides)
    return ExecutionRequest(**values)


def _serialized(result):
    return json.dumps(result, sort_keys=True, separators=(",", ":"))


def test_valid_request_returns_exact_bounded_deterministic_receipt():
    first = validate_instructional_materials_contract(_request())
    second = validate_instructional_materials_contract(_request())
    assert first == second
    assert first["status"] == "success"
    assert first["message"] == (
        "Instructional Materials Coach command plan validated; no execution performed."
    )
    assert first["output"]["command"] == [
        "imc-build",
        "build",
        "--content",
        "lessons/unit-1.yaml",
        "--slides-template",
        "slides-template_123",
        "--doc-template",
        "doc-template_123",
        "--target-folder",
        "folder_123",
        "--lessons-dir",
        "reports/lessons",
    ]
    assert isinstance(first["output"]["command"], list)
    assert first["output"]["authority"] == {
        "approval": False,
        "execution": False,
        "external_write": False,
        "freshness": False,
        "capability": False,
    }
    assert first["output"]["external_calls"] == []
    assert first["output"]["files_created"] == []
    assert len(_serialized(first).encode()) <= MAX_RECEIPT_BYTES


@pytest.mark.parametrize(
    "field", ["contract_version", "operation", "content_path", "lessons_dir"]
)
def test_missing_and_blank_required_payload_fields_fail(field):
    payload = _payload()
    payload.pop(field)
    assert (
        validate_instructional_materials_contract(_request(payload=payload))["status"]
        == "failure"
    )
    payload = _payload()
    payload[field] = ""
    assert (
        validate_instructional_materials_contract(_request(payload=payload))["status"]
        == "failure"
    )


@pytest.mark.parametrize(
    "key",
    [
        "token",
        "credentials",
        "client_secret",
        "oauth_path",
        "environment",
        "env",
        "command",
        "shell",
        "executable",
        "unexpected",
    ],
)
def test_unknown_and_secret_like_keys_fail_without_echo(key):
    payload = _payload()
    payload[key] = "do-not-echo"
    result = validate_instructional_materials_contract(_request(payload=payload))
    assert result["status"] == "failure"
    assert key not in _serialized(result)
    assert "do-not-echo" not in _serialized(result)


@pytest.mark.parametrize(
    "value",
    [
        "$(id)",
        "`id`",
        "x;y",
        "x>y",
        "x&&y",
        "x||y",
        "${HOME}",
        "x\ry",
        "x\ny",
        "x\x00y",
        "-rf",
        "/tmp/x",
        "../secret",
        "a/../secret",
        "C:/secret",
    ],
)
def test_hostile_paths_fail(value):
    payload = _payload()
    payload["content_path"] = value
    assert (
        validate_instructional_materials_contract(_request(payload=payload))["status"]
        == "failure"
    )


@pytest.mark.parametrize(
    "field", ["slides_template_id", "doc_template_id", "target_drive_folder_id"]
)
@pytest.mark.parametrize("value", ["$(id)", "x y", "../x", "-x", "x;y", "x\ny"])
def test_opaque_ids_use_safe_token_syntax(field, value):
    payload = _payload()
    payload[field] = value
    assert (
        validate_instructional_materials_contract(_request(payload=payload))["status"]
        == "failure"
    )


@pytest.mark.parametrize(
    ("request_changes", "payload_changes", "gate_changes", "reason"),
    [
        ({}, {"dry_run": False}, {}, "live-execution-not-authorized"),
        ({}, {"execution_authorized": True}, {}, "live-execution-not-authorized"),
        ({"mode": "Production"}, {}, {}, "production-mode-not-authorized"),
        ({"approval_required": True}, {}, {}, "approval-path-not-authorized"),
        ({"production_ready": True}, {}, {}, "production-mode-not-authorized"),
        ({"batch_id": "batch-1"}, {}, {}, "batching-not-authorized"),
        ({}, {"governed_field_risk": True}, {}, "governed-field-risk"),
        ({}, {"writes_governed_field": True}, {}, "governed-field-risk"),
        ({}, {}, {"blockers": "present"}, "production-gate-not-satisfied"),
    ],
)
def test_valid_but_prohibited_states_are_blocked(
    request_changes, payload_changes, gate_changes, reason
):
    payload = _payload()
    payload.update(payload_changes)
    payload["production_gates"].update(gate_changes)
    result = validate_instructional_materials_contract(
        _request(payload=payload, **request_changes)
    )
    assert result == {
        "status": "blocked",
        "message": "Instructional Materials Coach dry-run request is not authorized.",
        "blocked_reason": reason,
    }


class EvilString(str):
    pass


class EvilDict(dict):
    def __iter__(self):
        raise AssertionError("custom iteration must not run")

    def __repr__(self):
        raise AssertionError("repr must not run")


class EvilRequest(ExecutionRequest):
    pass


def test_subclassed_and_custom_values_fail_closed_without_custom_behavior():
    payload = _payload()
    payload["content_path"] = EvilString("safe/path")
    assert (
        validate_instructional_materials_contract(_request(payload=payload))["status"]
        == "failure"
    )
    assert (
        validate_instructional_materials_contract(
            _request(payload=EvilDict(_payload()))
        )["status"]
        == "failure"
    )
    base = _request()
    evil = EvilRequest(**base.__dict__)
    assert validate_instructional_materials_contract(evil)["status"] == "failure"


def test_malformed_types_and_bounds_fail_closed():
    payload = _payload()
    payload["dry_run"] = 1
    assert (
        validate_instructional_materials_contract(_request(payload=payload))["status"]
        == "failure"
    )
    payload = _payload()
    payload["content_path"] = "a" * 257
    assert (
        validate_instructional_materials_contract(_request(payload=payload))["status"]
        == "failure"
    )
    payload = _payload()
    payload["production_gates"]["evidence_target"] = "a" * 513
    assert (
        validate_instructional_materials_contract(_request(payload=payload))["status"]
        == "failure"
    )
    assert (
        validate_instructional_materials_contract(_request(idempotency_key="a" * 257))[
            "status"
        ]
        == "failure"
    )


def test_request_payload_and_context_are_not_mutated():
    request = _request(
        execution_context=ExecutionContext(approval_context={"note": "unchanged"})
    )
    payload_before = deepcopy(request.payload)
    context_before = deepcopy(request.execution_context)
    validate_instructional_materials_contract(request)
    assert request.payload == payload_before
    assert request.execution_context == context_before


def test_wrong_contract_operation_owner_and_gate_shape_fail_closed():
    for field, value in (("contract_version", "v2"), ("operation", "other")):
        payload = _payload()
        payload[field] = value
        assert (
            validate_instructional_materials_contract(_request(payload=payload))["status"]
            == "failure"
        )
    assert (
        validate_instructional_materials_contract(_request(owner="other"))["status"]
        == "failure"
    )
    payload = _payload()
    payload["production_gates"]["extra"] = "x"
    assert (
        validate_instructional_materials_contract(_request(payload=payload))["status"]
        == "failure"
    )


class ExplosiveValue:
    def __iter__(self):
        raise AssertionError("custom iteration must not run")

    def __repr__(self):
        raise AssertionError("repr must not run")

    def __str__(self):
        raise AssertionError("str must not run")

    def __hash__(self):
        raise AssertionError("hash must not run")

    def __eq__(self, other):
        raise AssertionError("comparison must not run")


class EvilBoolLike:
    def __bool__(self):
        raise AssertionError("bool coercion must not run")


class EvilIterable:
    def __iter__(self):
        raise AssertionError("iteration must not run")


class EvilException(Exception):
    def __repr__(self):
        raise AssertionError("repr must not run")

    def __str__(self):
        raise AssertionError("str must not run")


def test_semantically_identical_builtin_payload_order_is_byte_stable():
    first_payload = _payload()
    second_payload = dict(reversed(list(first_payload.items())))
    second_payload["production_gates"] = dict(
        reversed(list(first_payload["production_gates"].items()))
    )
    first = validate_instructional_materials_contract(_request(payload=first_payload))
    second = validate_instructional_materials_contract(_request(payload=second_payload))
    assert _serialized(first) == _serialized(second)


@pytest.mark.parametrize(
    "field,value",
    [
        ("content_path", ExplosiveValue()),
        ("slides_template_id", EvilIterable()),
        ("dry_run", EvilBoolLike()),
        ("operation", EvilException("do-not-inspect")),
    ],
)
def test_hostile_custom_values_fail_without_arbitrary_behavior(field, value):
    payload = _payload()
    payload[field] = value
    assert (
        validate_instructional_materials_contract(_request(payload=payload))["status"]
        == "failure"
    )


def test_hostile_nested_gate_values_fail_without_arbitrary_behavior():
    payload = _payload()
    payload["production_gates"]["evidence_target"] = ExplosiveValue()
    assert (
        validate_instructional_materials_contract(_request(payload=payload))["status"]
        == "failure"
    )


def test_execution_context_subclass_fails_closed_before_nested_inspection():
    class EvilContext(ExecutionContext):
        def __getattribute__(self, name):
            if name not in {"__class__"}:
                raise AssertionError("context attributes must not be inspected")
            return super().__getattribute__(name)

    request = _request(execution_context=EvilContext())
    assert validate_instructional_materials_contract(request)["status"] == "failure"
