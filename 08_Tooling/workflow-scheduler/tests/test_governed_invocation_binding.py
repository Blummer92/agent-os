from __future__ import annotations

import ast
from pathlib import Path

import pytest

import workflow_scheduler.governance.governed_invocation_binding as binding
from workflow_scheduler.governance.gce_control_path import GceResourceTuple
from workflow_scheduler.governance.github_issue_comment_ingress import (
    IssueCommentIngressResult,
)

HANDOFF = "executor-handoff:" + "a" * 64


def _ingress(**overrides: object) -> IssueCommentIngressResult:
    values = dict(
        schema_version="1.1",
        status="accepted",
        reason="accepted-envelope",
        repository="Blummer92/agent-os",
        issue_number=1203,
        comment_id=99,
        actor="Blummer92",
        operation_or_none="resume",
        handoff_id_or_none=HANDOFF,
        logical_trigger_id_or_none="issue-comment-trigger:" + "b" * 64,
        run_attempt=1,
    )
    values.update(overrides)
    return IssueCommentIngressResult(**values)


def _resource() -> GceResourceTuple:
    return GceResourceTuple(
        project="agent-os-502614",
        zone="us-central1-a",
        instance="agent-os-test",
    )


def test_accepted_ingress_binds_to_exact_fixed_resource() -> None:
    result = binding.bind_ingress_to_gce(_ingress(), resource=_resource())
    assert result.repository == "Blummer92/agent-os"
    assert result.issue_number == 1203
    assert result.handoff_id == HANDOFF
    assert result.resource == _resource()
    assert result.control_request_id.startswith("gce-control-request:")
    assert result.binding_id.startswith("governed-invocation-binding:")
    assert result.execution_authorized is False
    assert result.scheduler_authorized_by_transport is False
    assert result.cloud_authorized_by_transport is False
    assert result.github_writes_authorized is False
    assert result.retry_authorized is False
    assert result.arbitrary_command_authorized is False


def test_binding_is_deterministic_for_duplicate_transport_identity() -> None:
    first = binding.bind_ingress_to_gce(_ingress(), resource=_resource())
    second = binding.bind_ingress_to_gce(_ingress(), resource=_resource())
    assert first == second


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "blocked", "reason": "actor-not-allowed"},
        {"status": "ignored", "reason": "malformed-trigger"},
        {"run_attempt": 2},
        {"handoff_id_or_none": None},
        {"logical_trigger_id_or_none": None},
    ],
)
def test_noncanonical_transport_never_binds(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        binding.bind_ingress_to_gce(_ingress(**overrides), resource=_resource())


def test_module_has_no_external_effect_surface() -> None:
    path = Path(binding.__file__)
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    for module_name in imported:
        assert not any(
            token in module_name.lower()
            for token in ("subprocess", "socket", "requests", "google.cloud", "boto")
        )
    for token in (".start(", ".stop(", ".invoke(", "subprocess.", "os.system("):
        assert token not in source
