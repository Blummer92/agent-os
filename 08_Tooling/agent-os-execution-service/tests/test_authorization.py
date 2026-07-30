from __future__ import annotations

import ast
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from agent_os_execution_service import ExecutionAuthorizationEvidence
from agent_os_execution_service.authorization import (
    ExecutionAuthorizationEvidence as DirectExecutionAuthorizationEvidence,
)

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "08_Tooling/agent-os-execution-service/src"
PACKAGE = SRC / "agent_os_execution_service"


def _evidence(**changes: object) -> ExecutionAuthorizationEvidence:
    values: dict[str, object] = {
        "authorization_id": "auth-811",
        "request_fingerprint": "a" * 64,
        "command_plan_id": "plan-811",
        "repository": "Blummer92/agent-os",
        "expected_sha": "b" * 40,
        "authorized_at": "2026-07-30T20:00:00Z",
        "expires_at": "2026-07-30T21:00:00Z",
        "execution_authorized": True,
    }
    values.update(changes)
    return ExecutionAuthorizationEvidence(**values)  # type: ignore[arg-type]


def _isolated_import(code: str) -> subprocess.CompletedProcess[str]:
    bootstrap = (
        "import sys; "
        f"sys.path.insert(0, {str(ROOT)!r}); "
        f"sys.path.insert(0, {str(SRC)!r}); "
        + code
    )
    return subprocess.run(
        [sys.executable, "-I", "-c", bootstrap],
        check=False,
        capture_output=True,
        text=True,
    )


def test_valid_evidence_is_frozen_and_side_effect_free() -> None:
    evidence = _evidence()
    assert evidence.side_effects_performed is False
    with pytest.raises(FrozenInstanceError):
        evidence.authorization_id = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "field",
    ("authorization_id", "request_fingerprint", "command_plan_id", "repository", "expected_sha"),
)
def test_required_strings_fail_closed(field: str) -> None:
    with pytest.raises(TypeError):
        _evidence(**{field: ""})
    with pytest.raises(TypeError):
        _evidence(**{field: 1})


@pytest.mark.parametrize("field", ("authorized_at", "expires_at"))
def test_malformed_timestamps_fail_closed(field: str) -> None:
    with pytest.raises((TypeError, ValueError)):
        _evidence(**{field: "not-a-timestamp"})


def test_execution_authorized_requires_exact_boolean() -> None:
    with pytest.raises(TypeError):
        _evidence(execution_authorized=1)


def test_side_effect_state_cannot_be_supplied() -> None:
    with pytest.raises(TypeError):
        ExecutionAuthorizationEvidence(
            authorization_id="auth-811",
            request_fingerprint="a" * 64,
            command_plan_id="plan-811",
            repository="Blummer92/agent-os",
            expected_sha="b" * 40,
            authorized_at="2026-07-30T20:00:00Z",
            expires_at="2026-07-30T21:00:00Z",
            execution_authorized=True,
            side_effects_performed=True,  # type: ignore[call-arg]
        )


def test_package_export_is_exact_pure_class() -> None:
    assert ExecutionAuthorizationEvidence is DirectExecutionAuthorizationEvidence


def test_direct_import_does_not_load_workflow_scheduler() -> None:
    result = _isolated_import(
        "from agent_os_execution_service.authorization import ExecutionAuthorizationEvidence; "
        "assert not any(k == 'workflow_scheduler' or k.startswith('workflow_scheduler.') "
        "for k in sys.modules)"
    )
    assert result.returncode == 0, result.stderr


def test_package_level_import_does_not_load_workflow_scheduler() -> None:
    result = _isolated_import(
        "from agent_os_execution_service import ExecutionAuthorizationEvidence; "
        "assert not any(k == 'workflow_scheduler' or k.startswith('workflow_scheduler.') "
        "for k in sys.modules)"
    )
    assert result.returncode == 0, result.stderr


def test_composition_consumes_exact_extracted_class() -> None:
    source = (PACKAGE / "execution_composition.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = [
        node
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and node.level == 1
        and node.module == "authorization"
    ]
    assert len(imports) == 1
    assert [alias.name for alias in imports[0].names] == ["ExecutionAuthorizationEvidence"]


def test_only_one_authorization_class_definition_exists() -> None:
    definitions: list[Path] = []
    for path in PACKAGE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(
            isinstance(node, ast.ClassDef)
            and node.name == "ExecutionAuthorizationEvidence"
            for node in ast.walk(tree)
        ):
            definitions.append(path)
    assert definitions == [PACKAGE / "authorization.py"]
