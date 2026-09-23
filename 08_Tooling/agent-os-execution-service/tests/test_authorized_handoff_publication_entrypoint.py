"""Focused #1409 tests for the authorized-lifecycle publication caller."""

from __future__ import annotations

import ast
import sys
from dataclasses import replace
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
EXEC_SERVICE_SRC = REPOSITORY_ROOT / "08_Tooling/agent-os-execution-service/src"
SCHEDULER_SRC = REPOSITORY_ROOT / "08_Tooling/workflow-scheduler/src"
TESTS_DIR = Path(__file__).resolve().parent
for _path in (REPOSITORY_ROOT, EXEC_SERVICE_SRC, SCHEDULER_SRC, TESTS_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from test_validation_lifecycle_evidence import _accepted_admission  # noqa: E402

from agent_os_execution_service import authorized_validation_entrypoint as module  # noqa: E402
from agent_os_execution_service.authorized_validation_entrypoint import (  # noqa: E402
    publish_authorized_validation_handoff,
)

MODULE_PATH = (
    EXEC_SERVICE_SRC / "agent_os_execution_service" / "authorized_validation_entrypoint.py"
)
_EVALUATED_AT = "2026-08-11T12:10:00Z"


class _PublicationSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self.response = object()

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.response


def _call(request, monkeypatch):
    spy = _PublicationSpy()
    monkeypatch.setattr(module, "publish_governed_handoff", spy)
    sentinels = {
        "route_decision": object(),
        "checkpoint": object(),
        "resume_plan": object(),
        "dependency_readiness": object(),
        "pilot_input": object(),
    }
    result = publish_authorized_validation_handoff(
        "/tmp/store",
        admission_request=request,
        evaluated_at=_EVALUATED_AT,
        required_return_evidence=("result",),
        stop_conditions=("stop",),
        **sentinels,
    )
    return spy, sentinels, result


def test_accepted_lifecycle_delegates_once_with_existing_canonical_objects(
    tmp_path, monkeypatch
) -> None:
    request, _ = _accepted_admission(tmp_path)
    execution_stage = request.execution_packet_stage

    spy, sentinels, result = _call(request, monkeypatch)

    assert result is spy.response
    assert len(spy.calls) == 1
    args, call = spy.calls[0]
    assert args == ("/tmp/store",)
    assert call["request"] is execution_stage.request
    assert call["authorization"] is request.execution_authorization
    assert call["candidate_packet"] is request.candidate_packet
    assert call["runtime_configuration"] is execution_stage.runtime_configuration
    for name, sentinel in sentinels.items():
        assert call[name] is sentinel
    assert call["evaluated_at"] == _EVALUATED_AT
    assert call["required_return_evidence"] == ("result",)
    assert call["stop_conditions"] == ("stop",)


def test_stale_authorization_exposes_no_handoff(tmp_path, monkeypatch) -> None:
    request, _ = _accepted_admission(tmp_path)
    stale_authorization = replace(
        request.execution_authorization,
        expires_at="2026-08-11T12:06:00Z",
    )
    stale_request = replace(
        request,
        execution_authorization=stale_authorization,
        request_id="",
    )
    spy = _PublicationSpy()
    monkeypatch.setattr(module, "publish_governed_handoff", spy)

    with pytest.raises(RuntimeError, match="requires accepted"):
        publish_authorized_validation_handoff(
            "/tmp/store",
            admission_request=stale_request,
            route_decision=object(),
            checkpoint=object(),
            resume_plan=object(),
            dependency_readiness=object(),
            evaluated_at=_EVALUATED_AT,
            pilot_input=object(),
            required_return_evidence=("result",),
            stop_conditions=("stop",),
        )

    assert spy.calls == []


def test_non_request_type_is_rejected_before_publication(monkeypatch) -> None:
    spy = _PublicationSpy()
    monkeypatch.setattr(module, "publish_governed_handoff", spy)

    with pytest.raises(TypeError, match="admission_request"):
        publish_authorized_validation_handoff(
            "/tmp/store",
            admission_request=object(),
            route_decision=object(),
            checkpoint=object(),
            resume_plan=object(),
            dependency_readiness=object(),
            evaluated_at=_EVALUATED_AT,
            pilot_input=object(),
            required_return_evidence=("result",),
            stop_conditions=("stop",),
        )

    assert spy.calls == []


def test_publication_logic_is_not_duplicated() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "publish_authorized_validation_handoff"
    )
    calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)]
    publication_calls = [
        node
        for node in calls
        if isinstance(node.func, ast.Name)
        and node.func.id == "publish_governed_handoff"
    ]
    assert len(publication_calls) == 1

    forbidden = (
        "build_executor_handoff",
        "persist_current_invocation_descriptor",
        "append_executor_handoff",
        "append_resume_plan",
        "append_restart_capsule",
        "Scheduler",
        "subprocess",
        "retry",
        "fallback",
    )
    function_source = ast.get_source_segment(source, function) or ""
    for token in forbidden:
        assert token not in function_source
