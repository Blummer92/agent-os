"""Regression tests for #1830 first-publication source capture."""
from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
EXEC_SERVICE_SRC = REPOSITORY_ROOT / "08_Tooling/agent-os-execution-service/src"
SCHEDULER_SRC = REPOSITORY_ROOT / "08_Tooling/workflow-scheduler/src"
for _path in (REPOSITORY_ROOT, EXEC_SERVICE_SRC, SCHEDULER_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from agent_os_execution_service import first_publication_source_capture as module  # noqa: E402
from agent_os_execution_service.validation_lifecycle_evidence import (  # noqa: E402
    ValidationLifecycleTerminalStatus,
)

MODULE_PATH = (
    EXEC_SERVICE_SRC / "agent_os_execution_service" / "first_publication_source_capture.py"
)


def _call(monkeypatch, *, status=ValidationLifecycleTerminalStatus.SUCCEEDED):
    calls: list[tuple[str, object]] = []
    result = SimpleNamespace(status=status)
    request = SimpleNamespace(
        candidate_packet=object(),
        execution_packet_stage=SimpleNamespace(
            runtime_configuration=SimpleNamespace(required_environment_spec=object())
        ),
        execution_authorization=SimpleNamespace(expires_at="2026-09-03T20:00:00Z"),
    )
    pilot = object()
    capsule = SimpleNamespace(capsule_id="pre-publication-evidence:" + "a" * 64)

    def run(**kwargs):
        calls.append(("run", kwargs))
        return result

    def load_configuration():
        calls.append(("configuration", None))
        return SimpleNamespace(checkpoint_store_root=Path("/trusted/checkpoints"))

    def build(**kwargs):
        calls.append(("build", kwargs))
        return capsule

    def append(root, value):
        calls.append(("append", (root, value)))
        return SimpleNamespace(capsule_id=value.capsule_id)

    monkeypatch.setattr(module, "run_authorized_validation_lifecycle", run)
    monkeypatch.setattr(module, "load_production_host_configuration", load_configuration)
    monkeypatch.setattr(module, "build_source_pre_publication_evidence", build)
    monkeypatch.setattr(module, "append_pre_publication_evidence", append)
    monkeypatch.setattr(module, "_execution_identity", lambda value: "pilot-holder:" + "b" * 64)

    returned = module.run_production_authorized_validation_with_source_capture(
        admission_request=request,
        evaluated_at="2026-09-03T19:00:00Z",
        pilot_input=pilot,
        cancelled=lambda: False,
    )
    return returned, calls, request, pilot, capsule


def test_success_captures_exact_source_evidence_after_validation(monkeypatch) -> None:
    (result, capsule_id), calls, request, pilot, capsule = _call(monkeypatch)
    assert capsule_id == capsule.capsule_id
    assert [name for name, _ in calls] == ["run", "configuration", "build", "append"]
    build = dict(calls)["build"]
    assert build["candidate_packet"] is request.candidate_packet
    assert build["pilot_input"] is pilot
    assert build["required_environment_spec"] is request.execution_packet_stage.runtime_configuration.required_environment_spec
    assert build["execution_id"] == "pilot-holder:" + "b" * 64
    assert build["created_at"] == "2026-09-03T19:00:00Z"
    assert build["expires_at"] == request.execution_authorization.expires_at
    root, persisted = dict(calls)["append"]
    assert root == Path("/trusted/checkpoints")
    assert persisted is capsule


def test_non_success_performs_zero_source_writes(monkeypatch) -> None:
    (result, capsule_id), calls, *_ = _call(
        monkeypatch, status=ValidationLifecycleTerminalStatus.VALIDATION_FAILED
    )
    assert capsule_id is None
    assert [name for name, _ in calls] == ["run"]


def test_missing_required_environment_fails_before_source_write(monkeypatch) -> None:
    monkeypatch.setattr(
        module,
        "run_authorized_validation_lifecycle",
        lambda **kwargs: SimpleNamespace(status=ValidationLifecycleTerminalStatus.SUCCEEDED),
    )
    monkeypatch.setattr(
        module,
        "load_production_host_configuration",
        lambda: SimpleNamespace(checkpoint_store_root=Path("/trusted/checkpoints")),
    )
    request = SimpleNamespace(
        candidate_packet=object(),
        execution_packet_stage=SimpleNamespace(
            runtime_configuration=SimpleNamespace(required_environment_spec=None)
        ),
        execution_authorization=SimpleNamespace(expires_at="2026-09-03T20:00:00Z"),
    )
    with pytest.raises(module.FirstPublicationSourceCaptureError):
        module.run_production_authorized_validation_with_source_capture(
            admission_request=request,
            evaluated_at="2026-09-03T19:00:00Z",
            pilot_input=object(),
            cancelled=lambda: False,
        )


def test_external_surface_has_no_store_repository_or_workspace_path_arguments() -> None:
    parameters = set(
        inspect.signature(
            module.run_production_authorized_validation_with_source_capture
        ).parameters
    )
    forbidden = {
        "store_root",
        "checkpoint_store_root",
        "repository_root",
        "workspace_root",
        "workspace_parent",
        "lease_directory",
        "command",
        "argv",
        "environment",
    }
    assert not parameters & forbidden


def test_capture_defines_no_publication_checkpoint_resume_route_or_retry_calls() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    for token in (
        "publish_authorized_validation_handoff(",
        "publish_governed_handoff(",
        "activate_first_publication_source(",
        "append_checkpoint(",
        "plan_resume(",
        "append_resume_plan(",
        "select_executor_route(",
        "append_route_decision(",
        "prepare(",
        "subprocess",
        "retry",
    ):
        assert token not in source, token


def test_capture_calls_validation_build_and_append_once() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "run_production_authorized_validation_with_source_capture"
    )
    body = ast.get_source_segment(source, function) or ""
    assert body.count("run_authorized_validation_lifecycle(") == 1
    assert body.count("build_source_pre_publication_evidence(") == 1
    assert body.count("append_pre_publication_evidence(") == 1
