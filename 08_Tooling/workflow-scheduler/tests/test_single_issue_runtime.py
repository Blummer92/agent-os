"""Tests for the WSC5B1 pure bounded single-issue runtime entrypoint.

Reuses the real canonical fixtures and in-memory fakes already proven in
``test_single_issue_pilot.py`` (approved projection, IssuePlan evidence,
approval record, validation plan/bundle/advisory/render, and the five
in-memory adapters) instead of duplicating that setup.
"""

from __future__ import annotations

import ast
import inspect
import sys
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCHEDULER_SRC = REPOSITORY_ROOT / "08_Tooling/workflow-scheduler/src"
TESTS_DIR = Path(__file__).resolve().parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
if str(SCHEDULER_SRC) not in sys.path:
    sys.path.insert(0, str(SCHEDULER_SRC))
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

import test_single_issue_pilot as tsp  # noqa: E402

from workflow_scheduler.execution import single_issue_runtime as runtime_module  # noqa: E402
from workflow_scheduler.execution.quarantine_review import (  # noqa: E402
    QuarantineEvidencePacket,
)
from workflow_scheduler.execution.single_issue_pilot import (  # noqa: E402
    PilotLeaseGrant,
    SingleIssuePilotInput,
    SingleIssuePilotResult,
    pilot_lease_identity,
)
from workflow_scheduler.execution.single_issue_runtime import (  # noqa: E402
    RuntimeEntrypointError,
    RuntimeObservation,
    SingleIssueRuntimeOutcome,
    run_single_issue_runtime_entrypoint,
    runtime_observation_id,
    serialize_runtime_observation,
)

MODULE_PATH = (
    SCHEDULER_SRC / "workflow_scheduler" / "execution" / "single_issue_runtime.py"
)


def _entrypoint(pilot_input=None, **adapters) -> SingleIssueRuntimeOutcome:
    return run_single_issue_runtime_entrypoint(
        pilot_input if pilot_input is not None else tsp._pilot_input(),
        lease=adapters.pop("lease", None) or tsp.FakeLease(),
        workspace=adapters.pop("workspace", None) or tsp.FakeWorkspace(),
        executor=adapters.pop("executor", None) or tsp.FakeExecutor(),
        validator=adapters.pop("validator", None) or tsp.FakeValidator(),
        cancelled=adapters.pop("cancelled", None) or tsp.never_cancelled,
    )


def _quarantined_lease() -> tsp.FakeLease:
    request = tsp.PilotLeaseRequest(
        repository=tsp.REPOSITORY,
        issue_number=tsp.ISSUE,
        invocation_id=tsp.INVOCATION_ID,
        branch=tsp.BRANCH,
        workspace_request_id=tsp.WORKSPACE_REQUEST_ID,
        projection_id=tsp.PROJECTION.projection_id,
        approval_id=tsp.PROJECTION.approval_id,
        source_head_sha=tsp.HEAD_SHA,
    )
    return tsp.FakeLease(
        grant=PilotLeaseGrant(
            acquired=True,
            lease_identity=pilot_lease_identity(request),
            holder_identity="pilot-holder:" + "0" * 64,
            generation=1,
        )
    )


# --------------------------------------------------------------------------
# Success path / exactly-once orchestration
# --------------------------------------------------------------------------


def test_valid_one_issue_request_calls_orchestrator_exactly_once(monkeypatch) -> None:
    calls = []
    original = runtime_module.run_single_issue_pilot

    def counting(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(runtime_module, "run_single_issue_pilot", counting)

    outcome = _entrypoint()

    assert len(calls) == 1
    assert outcome.observation.orchestrator_invocation_count == 1
    assert outcome.result.status == "completed"


def test_canonical_pilot_result_is_returned_unchanged() -> None:
    lease, workspace, executor, validator = (
        tsp.FakeLease(),
        tsp.FakeWorkspace(),
        tsp.FakeExecutor(),
        tsp.FakeValidator(),
    )
    direct = tsp._run(lease=lease, workspace=workspace, executor=executor, validator=validator)

    outcome = _entrypoint(
        lease=tsp.FakeLease(),
        workspace=tsp.FakeWorkspace(),
        executor=tsp.FakeExecutor(),
        validator=tsp.FakeValidator(),
    )

    assert outcome.result.result_id == direct.result_id
    assert isinstance(outcome.result, SingleIssuePilotResult)
    with pytest.raises(FrozenInstanceError):
        outcome.result.status = "blocked"  # type: ignore[misc]


def test_no_duplicate_orchestrator_invocation_is_possible(monkeypatch) -> None:
    calls = []
    original = runtime_module.run_single_issue_pilot

    def counting(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(runtime_module, "run_single_issue_pilot", counting)

    _entrypoint()
    _entrypoint()

    assert calls == [1, 1]


# --------------------------------------------------------------------------
# Fail-closed before any adapter is touched
# --------------------------------------------------------------------------


def test_malformed_input_fails_before_orchestrator_and_adapters() -> None:
    lease, workspace, executor, validator = (
        tsp.FakeLease(),
        tsp.FakeWorkspace(),
        tsp.FakeExecutor(),
        tsp.FakeValidator(),
    )
    with pytest.raises(RuntimeEntrypointError):
        run_single_issue_runtime_entrypoint(
            "not-a-pilot-input",  # type: ignore[arg-type]
            lease=lease,
            workspace=workspace,
            executor=executor,
            validator=validator,
            cancelled=tsp.never_cancelled,
        )
    assert lease.acquire_calls == []
    assert workspace.create_calls == []
    assert executor.calls == []
    assert validator.calls == []


def test_non_conforming_adapter_fails_before_orchestrator() -> None:
    workspace, executor, validator = tsp.FakeWorkspace(), tsp.FakeExecutor(), tsp.FakeValidator()
    with pytest.raises(RuntimeEntrypointError):
        run_single_issue_runtime_entrypoint(
            tsp._pilot_input(),
            lease=object(),  # type: ignore[arg-type]
            workspace=workspace,
            executor=executor,
            validator=validator,
            cancelled=tsp.never_cancelled,
        )
    assert workspace.create_calls == []
    assert executor.calls == []
    assert validator.calls == []


def test_zero_issues_fails_before_adapter_calls() -> None:
    lease, workspace, executor, validator = (
        tsp.FakeLease(),
        tsp.FakeWorkspace(),
        tsp.FakeExecutor(),
        tsp.FakeValidator(),
    )
    outcome = _entrypoint(
        pilot_input=tsp._pilot_input(issue_numbers=()),
        lease=lease,
        workspace=workspace,
        executor=executor,
        validator=validator,
    )
    assert outcome.result.status == "blocked"
    assert "input.no-issue" in outcome.result.reason_codes
    assert lease.acquire_calls == []
    assert workspace.create_calls == []
    assert executor.calls == []
    assert validator.calls == []


def test_multiple_issues_fails_before_adapter_calls() -> None:
    lease, workspace, executor, validator = (
        tsp.FakeLease(),
        tsp.FakeWorkspace(),
        tsp.FakeExecutor(),
        tsp.FakeValidator(),
    )
    outcome = _entrypoint(
        pilot_input=tsp._pilot_input(issue_numbers=(tsp.ISSUE, tsp.ISSUE + 1)),
        lease=lease,
        workspace=workspace,
        executor=executor,
        validator=validator,
    )
    assert outcome.result.status == "blocked"
    assert "input.multiple-issues" in outcome.result.reason_codes
    assert lease.acquire_calls == []
    assert executor.calls == []


def test_unsupported_concurrency_fails_before_adapter_calls() -> None:
    lease, executor = tsp.FakeLease(), tsp.FakeExecutor()
    outcome = _entrypoint(
        pilot_input=tsp._pilot_input(requested_concurrency=2),
        lease=lease,
        executor=executor,
    )
    assert outcome.result.status == "blocked"
    assert "input.concurrency-unsupported" in outcome.result.reason_codes
    assert lease.acquire_calls == []
    assert executor.calls == []


@pytest.mark.parametrize(
    ("changes", "expected_status"),
    [
        ({"tested_sha": "c" * 40}, "stale"),
        ({"base_sha": "9" * 40}, "blocked"),
        ({"expected_projection_id": "wrong-projection-id"}, "needs-decision"),
    ],
)
def test_non_passing_evidence_fails_before_lease_acquisition(changes, expected_status) -> None:
    lease, executor = tsp.FakeLease(), tsp.FakeExecutor()
    outcome = _entrypoint(pilot_input=tsp._pilot_input(**changes), lease=lease, executor=executor)
    assert outcome.result.status == expected_status
    assert lease.acquire_calls == []
    assert executor.calls == []


def test_approval_mismatch_fails_closed() -> None:
    lease = tsp.FakeLease()
    outcome = _entrypoint(pilot_input=tsp._pilot_input(approval_record=None), lease=lease)
    assert outcome.result.status == "blocked"
    assert lease.acquire_calls == []


def test_issueplan_current_state_mismatch_fails_closed() -> None:
    stale_issueplan = tsp._issueplan(tsp._handoff(), revision="stale-rev")
    lease = tsp.FakeLease()
    outcome = _entrypoint(
        pilot_input=tsp._pilot_input(current_issueplan_evidence=stale_issueplan), lease=lease
    )
    assert outcome.result.status == "stale"
    assert lease.acquire_calls == []


def test_repository_mismatch_fails_closed() -> None:
    lease = tsp.FakeLease()
    outcome = _entrypoint(pilot_input=tsp._pilot_input(repository="other/repo"), lease=lease)
    assert outcome.result.status == "blocked"
    assert lease.acquire_calls == []


def test_required_test_mismatch_fails_closed() -> None:
    lease = tsp.FakeLease()
    outcome = _entrypoint(
        pilot_input=tsp._pilot_input(required_tests=("pytest -k missing",)),
        lease=lease,
    )
    assert outcome.result.status != "completed"
    assert lease.acquire_calls == []


# --------------------------------------------------------------------------
# Adapter injection is exact
# --------------------------------------------------------------------------


def test_adapter_injection_is_exact_and_single_use() -> None:
    lease, workspace, executor, validator = (
        tsp.FakeLease(),
        tsp.FakeWorkspace(),
        tsp.FakeExecutor(),
        tsp.FakeValidator(),
    )
    outcome = _entrypoint(lease=lease, workspace=workspace, executor=executor, validator=validator)

    assert len(lease.acquire_calls) == 1
    assert len(lease.release_calls) == 1
    assert len(workspace.create_calls) == 1
    assert len(executor.calls) == 1
    assert len(validator.calls) == 1
    assert outcome.observation.lease_adapter_type == "FakeLease"
    assert outcome.observation.workspace_adapter_type == "FakeWorkspace"
    assert outcome.observation.executor_adapter_type == "FakeExecutor"
    assert outcome.observation.validator_adapter_type == "FakeValidator"


# --------------------------------------------------------------------------
# Quarantine evidence
# --------------------------------------------------------------------------


def test_quarantined_result_creates_local_quarantine_evidence_only() -> None:
    outcome = _entrypoint(lease=_quarantined_lease())

    assert outcome.result.status == "quarantined"
    assert isinstance(outcome.quarantine_evidence, QuarantineEvidencePacket)
    assert outcome.observation.quarantine_evidence_built is True
    assert outcome.observation.quarantine_packet_id == outcome.quarantine_evidence.packet_id


def test_quarantine_evidence_preserves_canonical_identities_from_result() -> None:
    outcome = _entrypoint(lease=_quarantined_lease())
    packet = outcome.quarantine_evidence
    result = outcome.result

    assert packet.result_id == result.result_id
    assert packet.repository == result.repository
    assert packet.invocation_id == result.invocation_id
    assert packet.base_sha == result.base_sha
    assert packet.source_head_sha == result.source_head_sha
    assert packet.tested_sha == result.tested_sha
    assert packet.projection_id == result.projection_id
    assert packet.approval_id == result.approval_id
    assert packet.bundle_id == result.bundle_id
    assert packet.advisory_result_id == result.advisory_result_id
    assert packet.advisory_render_id == result.advisory_render_id


def test_non_quarantined_result_has_no_quarantine_evidence() -> None:
    outcome = _entrypoint()
    assert outcome.result.status == "completed"
    assert outcome.quarantine_evidence is None
    assert outcome.observation.quarantine_evidence_built is False
    assert outcome.observation.quarantine_packet_id is None


def test_no_recovery_or_operator_review_event_is_executed() -> None:
    outcome = _entrypoint(lease=_quarantined_lease())
    assert not hasattr(outcome, "review_events")
    assert not hasattr(outcome.quarantine_evidence, "review_events")


# --------------------------------------------------------------------------
# Bounded, immutable, tamper-evident observation
# --------------------------------------------------------------------------


def test_runtime_observation_is_bounded_and_immutable() -> None:
    outcome = _entrypoint()
    with pytest.raises(FrozenInstanceError):
        outcome.observation.pilot_status = "blocked"  # type: ignore[misc]
    serialized = serialize_runtime_observation(outcome.observation)
    assert serialized["observation_id"] == outcome.observation.observation_id


def test_runtime_observation_is_deterministic() -> None:
    first = _entrypoint()
    second = _entrypoint()
    assert first.observation.observation_id == second.observation.observation_id


def test_runtime_observation_detects_tampering() -> None:
    outcome = _entrypoint()
    tampered = replace(outcome.observation, pilot_status="blocked")
    with pytest.raises(RuntimeEntrypointError):
        serialize_runtime_observation(tampered)


def test_runtime_observation_id_changes_when_identity_fields_change() -> None:
    baseline = _entrypoint()
    quarantined = _entrypoint(lease=_quarantined_lease())
    assert baseline.observation.observation_id != quarantined.observation.observation_id


def test_observation_rejects_non_single_invocation_count() -> None:
    outcome = _entrypoint()
    with pytest.raises(RuntimeEntrypointError):
        replace(outcome.observation, orchestrator_invocation_count=2)


# --------------------------------------------------------------------------
# Architecture boundary
# --------------------------------------------------------------------------


_FORBIDDEN_IMPORT_ROOTS = (
    "subprocess",
    "socket",
    "urllib",
    "http",
    "requests",
    "sqlite3",
    "threading",
    "multiprocessing",
    "asyncio",
    "queue",
    "shutil",
    "os",
)

_FORBIDDEN_MODULE_SUBSTRINGS = (
    "executor.py",
    "request_dispatch",
    "retry_manager",
    "github",
    "scheduler_core",
)


def test_module_imports_no_execution_persistence_or_network_authority() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    for module_name in imported_modules:
        root = module_name.split(".")[0]
        assert root not in _FORBIDDEN_IMPORT_ROOTS, f"forbidden import root: {module_name}"
        lowered = module_name.lower()
        for forbidden in _FORBIDDEN_MODULE_SUBSTRINGS:
            assert forbidden not in lowered, f"forbidden import: {module_name}"


def test_module_defines_no_network_subprocess_or_persistence_calls() -> None:
    source = inspect.getsource(runtime_module)
    for forbidden_token in (
        "subprocess.",
        "socket.",
        "sqlite3.",
        "requests.",
        "open(",
        "os.system",
    ):
        assert forbidden_token not in source


def test_no_pilot_workflow_issue_merge_or_concurrency_mutation_path_exists() -> None:
    source = inspect.getsource(runtime_module)
    for forbidden_token in (
        "merge",
        "close_issue",
        "set_label",
        "scheduler_execution_concurrency",
        "workflow_dispatch",
    ):
        assert forbidden_token not in source
