from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_os_execution_service.first_run_invalidation_projection import (
    FirstRunInvalidationProjectionError,
    canonical_invalidation_events,
    project_first_run_residual_invalidation,
)
from scripts.agent_os_candidate_packet.approval_stage import ApprovalProjectionStageStatus
from scripts.agent_os_candidate_packet.execution_packet_stage import ExecutionPacketDisposition
from scripts.agent_os_candidate_packet.models import CandidatePacketPhase
from scripts.agent_os_issue_acceptance import APPROVAL_INVALIDATION_REASON_CODES, ApprovalState


MODULE = (
    Path(__file__).resolve().parents[1]
    / "src/agent_os_execution_service/first_run_invalidation_projection.py"
)


def test_canonical_invalidation_events_reuses_exact_347_vocabulary() -> None:
    canonical = tuple(sorted(APPROVAL_INVALIDATION_REASON_CODES))
    assert canonical_invalidation_events(canonical) == canonical
    with pytest.raises(ValueError, match="unsupported invalidation_events"):
        canonical_invalidation_events(("proposal-revised",))
    with pytest.raises(ValueError, match="unsupported invalidation_events"):
        canonical_invalidation_events(("approval-record-superseded",))


def test_canonical_invalidation_events_remains_sorted_unique_and_bounded() -> None:
    with pytest.raises(ValueError, match="unique"):
        canonical_invalidation_events(("approval.expired", "approval.expired"))
    with pytest.raises(ValueError, match="canonically sorted"):
        canonical_invalidation_events(("source.revision-changed", "approval.expired"))
    with pytest.raises(ValueError, match="bounded count"):
        canonical_invalidation_events(tuple("approval.expired" for _ in range(257)))


def test_projection_does_not_treat_absence_as_positive_proof() -> None:
    candidate = SimpleNamespace(
        phase=CandidatePacketPhase.EXECUTION_CANDIDATE,
        evidence_completeness="incomplete",
        disposition="verified",
    )
    with pytest.raises(FirstRunInvalidationProjectionError, match="candidate evidence"):
        project_first_run_residual_invalidation(candidate, object(), object(), object())


def test_projection_requires_existing_approval_owner_to_be_applicable() -> None:
    candidate = SimpleNamespace(
        phase=CandidatePacketPhase.EXECUTION_CANDIDATE,
        evidence_completeness="complete",
        disposition="verified",
    )
    approval = SimpleNamespace(
        status=ApprovalProjectionStageStatus.COMPLETE,
        decision_revision=SimpleNamespace(state=ApprovalState.APPROVED),
        applicability=SimpleNamespace(status="stale", approval_applicable=False),
        projection=object(),
    )
    with pytest.raises(FirstRunInvalidationProjectionError, match="approval is not applicable"):
        project_first_run_residual_invalidation(candidate, approval, object(), object())


def test_projection_requires_existing_execution_packet_owner_to_be_go() -> None:
    candidate = SimpleNamespace(
        phase=CandidatePacketPhase.EXECUTION_CANDIDATE,
        evidence_completeness="complete",
        disposition="verified",
    )
    approval = SimpleNamespace(
        status=ApprovalProjectionStageStatus.COMPLETE,
        decision_revision=SimpleNamespace(state=ApprovalState.APPROVED),
        applicability=SimpleNamespace(status="applicable", approval_applicable=True),
        projection=object(),
    )
    execution = SimpleNamespace(
        disposition=ExecutionPacketDisposition.BLOCKED,
        packet_complete=False,
        runtime_configuration=None,
        validation_stage=None,
        request=None,
        command_plan=None,
    )
    with pytest.raises(FirstRunInvalidationProjectionError, match="execution-packet evidence"):
        project_first_run_residual_invalidation(candidate, approval, execution, object())


def test_module_is_pure_and_has_no_runtime_or_persistence_imports() -> None:
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imported = set()
    calls = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                calls.add(node.func.attr)

    forbidden_import_fragments = (
        "subprocess",
        "requests",
        "github",
        "checkpoint",
        "scheduler_client",
        "production_authorized_validation_caller",
    )
    assert not any(
        fragment in module
        for module in imported
        for fragment in forbidden_import_fragments
    )
    assert not ({"open", "write_text", "write_bytes", "run", "Popen"} & calls)


def test_composer_has_no_caller_supplied_invalidation_parameter() -> None:
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "build_first_run_authorized_validation_request"
    )
    names = {argument.arg for argument in (*function.args.args, *function.args.kwonlyargs)}
    assert "invalidation_events" not in names
