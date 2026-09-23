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
    STANDARD_EXECUTION_MODE,
    VALIDATION_ONLY_EXECUTION_MODE,
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


# --------------------------------------------------------------------------
# Aggregate observation-size enforcement (review fix)
# --------------------------------------------------------------------------

# A 4-byte-in-UTF-8 code point. Using it lets a field stay within
# MAX_FIELD_LENGTH (a Python character count) while contributing far more
# than MAX_FIELD_LENGTH bytes to the canonical UTF-8 serialized payload.
_WIDE_CHAR = "\U0001F600"


def _wide_named(base_cls: type) -> type:
    """Return a subclass of ``base_cls`` whose ``__name__`` is exactly
    ``MAX_FIELD_LENGTH`` wide (multibyte) characters -- long enough in UTF-8
    bytes to blow the aggregate observation limit once several such names
    are combined, but not long enough (in characters) to violate the
    per-field bound on its own.
    """
    name = _WIDE_CHAR * runtime_module.MAX_FIELD_LENGTH
    assert len(name) == runtime_module.MAX_FIELD_LENGTH
    assert len(name.encode("utf-8")) > runtime_module.MAX_FIELD_LENGTH
    return type(name, (base_cls,), {})


class _ProbeBase:
    def __call__(self, checkpoint: str) -> bool:
        return False


def test_normal_bounded_result_still_succeeds_after_fix() -> None:
    outcome = _entrypoint()
    assert outcome.result.status == "completed"
    assert isinstance(outcome.observation, RuntimeObservation)
    serialize_runtime_observation(outcome.observation)


def test_orchestrator_still_called_exactly_once_after_fix(monkeypatch) -> None:
    calls = []
    original = runtime_module.run_single_issue_pilot

    def counting(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(runtime_module, "run_single_issue_pilot", counting)
    _entrypoint()
    assert calls == [1]


def test_oversized_aggregate_observation_fails_before_outcome_is_returned() -> None:
    lease = _wide_named(tsp.FakeLease)()
    workspace = _wide_named(tsp.FakeWorkspace)()
    executor = _wide_named(tsp.FakeExecutor)()
    validator = _wide_named(tsp.FakeValidator)()
    cancelled = _wide_named(_ProbeBase)()

    with pytest.raises(RuntimeEntrypointError):
        run_single_issue_runtime_entrypoint(
            tsp._pilot_input(),
            lease=lease,
            workspace=workspace,
            executor=executor,
            validator=validator,
            cancelled=cancelled,
        )


def test_oversized_observation_field_lengths_individually_stay_bounded() -> None:
    # Every adapter type name used above is exactly MAX_FIELD_LENGTH
    # characters -- it does not violate the per-field character bound. Only
    # the aggregate UTF-8 byte size is what trips the limit.
    for base_cls in (tsp.FakeLease, tsp.FakeWorkspace, tsp.FakeExecutor, tsp.FakeValidator):
        wide_cls = _wide_named(base_cls)
        assert len(wide_cls.__name__) == runtime_module.MAX_FIELD_LENGTH


def test_utf8_encoded_bytes_govern_the_size_check_not_character_count() -> None:
    name = _WIDE_CHAR * runtime_module.MAX_FIELD_LENGTH
    # Character count alone would never trip MAX_FIELD_LENGTH...
    assert len(name) == runtime_module.MAX_FIELD_LENGTH
    # ...but the UTF-8 encoded byte count is four times larger.
    assert len(name.encode("utf-8")) == runtime_module.MAX_FIELD_LENGTH * 4

    lease = _wide_named(tsp.FakeLease)()
    workspace = _wide_named(tsp.FakeWorkspace)()
    executor = _wide_named(tsp.FakeExecutor)()
    validator = _wide_named(tsp.FakeValidator)()
    cancelled = _wide_named(_ProbeBase)()

    with pytest.raises(RuntimeEntrypointError):
        run_single_issue_runtime_entrypoint(
            tsp._pilot_input(),
            lease=lease,
            workspace=workspace,
            executor=executor,
            validator=validator,
            cancelled=cancelled,
        )


def test_canonical_result_is_unaltered_by_the_size_check(monkeypatch) -> None:
    captured = {}
    original = runtime_module.run_single_issue_pilot

    def capturing(*args, **kwargs):
        result = original(*args, **kwargs)
        captured["result_id"] = result.result_id
        captured["status"] = result.status
        return result

    monkeypatch.setattr(runtime_module, "run_single_issue_pilot", capturing)

    lease = _wide_named(tsp.FakeLease)()
    workspace = _wide_named(tsp.FakeWorkspace)()
    executor = _wide_named(tsp.FakeExecutor)()
    validator = _wide_named(tsp.FakeValidator)()
    cancelled = _wide_named(_ProbeBase)()

    with pytest.raises(RuntimeEntrypointError):
        run_single_issue_runtime_entrypoint(
            tsp._pilot_input(),
            lease=lease,
            workspace=workspace,
            executor=executor,
            validator=validator,
            cancelled=cancelled,
        )

    assert captured["status"] == "completed"

    # The same canonical input still produces the identical result outside
    # the oversized-observation path: the size check does not mutate or
    # otherwise corrupt the orchestrator's canonical result.
    direct = tsp._run(
        lease=tsp.FakeLease(),
        workspace=tsp.FakeWorkspace(),
        executor=tsp.FakeExecutor(),
        validator=tsp.FakeValidator(),
    )
    assert direct.result_id == captured["result_id"]


def test_oversized_observation_does_not_introduce_quarantine_recovery() -> None:
    lease = _wide_named(tsp.FakeLease)()
    workspace = _wide_named(tsp.FakeWorkspace)()
    executor = _wide_named(tsp.FakeExecutor)()
    validator = _wide_named(tsp.FakeValidator)()
    cancelled = _wide_named(_ProbeBase)()

    try:
        run_single_issue_runtime_entrypoint(
            tsp._pilot_input(),
            lease=lease,
            workspace=workspace,
            executor=executor,
            validator=validator,
            cancelled=cancelled,
        )
        raise AssertionError("expected RuntimeEntrypointError")
    except RuntimeEntrypointError:
        pass

    source = inspect.getsource(runtime_module)
    for forbidden_token in ("append_review_event", "ReviewEvent", "recovery", "rollback"):
        assert forbidden_token not in source


# --------------------------------------------------------------------------
# Additive validation-only execution mode (#707)
# --------------------------------------------------------------------------


def _validation_only_input(**changes):
    values: dict[str, object] = {
        "execution_mode": VALIDATION_ONLY_EXECUTION_MODE
    }
    values.update(changes)
    return tsp._pilot_input(**values)


def _validation_only_entrypoint(pilot_input=None, **adapters) -> SingleIssueRuntimeOutcome:
    """Invoke the entrypoint with no executor argument at all."""
    return run_single_issue_runtime_entrypoint(
        pilot_input if pilot_input is not None else _validation_only_input(),
        lease=adapters.pop("lease", None) or tsp.FakeLease(),
        workspace=adapters.pop("workspace", None) or tsp.FakeWorkspace(),
        validator=adapters.pop("validator", None) or tsp.FakeValidator(),
        cancelled=adapters.pop("cancelled", None) or tsp.never_cancelled,
    )


def test_validation_only_runs_the_orchestrator_exactly_once(monkeypatch) -> None:
    calls = []
    original = runtime_module.run_single_issue_pilot

    def counting(*args, **kwargs):
        calls.append(kwargs.get("executor", "missing"))
        return original(*args, **kwargs)

    monkeypatch.setattr(runtime_module, "run_single_issue_pilot", counting)

    outcome = _validation_only_entrypoint()

    assert calls == [None]
    assert outcome.observation.orchestrator_invocation_count == 1
    assert outcome.result.status == "completed"


def test_validation_only_observation_records_no_executor_adapter() -> None:
    lease, workspace, validator = (
        tsp.FakeLease(),
        tsp.FakeWorkspace(),
        tsp.FakeValidator(),
    )
    outcome = _validation_only_entrypoint(
        lease=lease, workspace=workspace, validator=validator
    )

    assert outcome.observation.execution_mode == VALIDATION_ONLY_EXECUTION_MODE
    assert outcome.observation.executor_adapter_type is None
    assert outcome.observation.validator_adapter_type == "FakeValidator"
    assert outcome.result.execution_mode == VALIDATION_ONLY_EXECUTION_MODE
    assert outcome.result.executor_dispatch_attempts == 0
    assert outcome.result.executor_called is False
    assert outcome.result.executor_started is False
    assert outcome.result.termination_confirmed is False
    assert outcome.result.validation_attempts == 1
    assert len(validator.calls) == 1
    assert len(lease.release_calls) == 1
    assert len(workspace.cleanup_calls) == 1


def test_standard_mode_observation_still_names_its_executor() -> None:
    outcome = _entrypoint()
    assert outcome.observation.execution_mode == STANDARD_EXECUTION_MODE
    assert outcome.observation.executor_adapter_type == "FakeExecutor"


def test_validation_only_rejects_a_supplied_executor_before_any_adapter() -> None:
    lease, workspace, executor, validator = (
        tsp.FakeLease(),
        tsp.FakeWorkspace(),
        tsp.FakeExecutor(),
        tsp.FakeValidator(),
    )
    with pytest.raises(RuntimeEntrypointError, match="validation-only"):
        run_single_issue_runtime_entrypoint(
            _validation_only_input(),
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


def test_standard_mode_still_rejects_a_missing_executor() -> None:
    lease, workspace, validator = (
        tsp.FakeLease(),
        tsp.FakeWorkspace(),
        tsp.FakeValidator(),
    )
    with pytest.raises(RuntimeEntrypointError):
        run_single_issue_runtime_entrypoint(
            tsp._pilot_input(),
            lease=lease,
            workspace=workspace,
            validator=validator,
            cancelled=tsp.never_cancelled,
        )
    assert lease.acquire_calls == []
    assert workspace.create_calls == []
    assert validator.calls == []


def test_standard_mode_still_rejects_a_non_conforming_executor() -> None:
    lease, validator = tsp.FakeLease(), tsp.FakeValidator()
    with pytest.raises(RuntimeEntrypointError):
        run_single_issue_runtime_entrypoint(
            tsp._pilot_input(),
            lease=lease,
            workspace=tsp.FakeWorkspace(),
            executor=object(),  # type: ignore[arg-type]
            validator=validator,
            cancelled=tsp.never_cancelled,
        )
    assert lease.acquire_calls == []
    assert validator.calls == []


def test_drifted_execution_mode_fails_before_any_adapter() -> None:
    pilot_input = tsp._pilot_input()
    object.__setattr__(pilot_input, "execution_mode", "dry-run")
    lease, workspace, executor, validator = (
        tsp.FakeLease(),
        tsp.FakeWorkspace(),
        tsp.FakeExecutor(),
        tsp.FakeValidator(),
    )
    with pytest.raises(RuntimeEntrypointError, match="execution mode"):
        run_single_issue_runtime_entrypoint(
            pilot_input,
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


def test_validation_only_observation_is_deterministic_and_tamper_evident() -> None:
    first = _validation_only_entrypoint()
    second = _validation_only_entrypoint()
    standard = _entrypoint()

    assert first.observation.observation_id == second.observation.observation_id
    assert first.observation.observation_id != standard.observation.observation_id
    assert serialize_runtime_observation(first.observation)["execution_mode"] == (
        VALIDATION_ONLY_EXECUTION_MODE
    )
    with pytest.raises(RuntimeEntrypointError):
        serialize_runtime_observation(
            replace(first.observation, execution_mode=STANDARD_EXECUTION_MODE)
        )


def test_only_validation_only_may_record_an_absent_executor_adapter() -> None:
    outcome = _validation_only_entrypoint()
    with pytest.raises(RuntimeEntrypointError):
        replace(outcome.observation, execution_mode=STANDARD_EXECUTION_MODE)
    with pytest.raises(RuntimeEntrypointError):
        replace(outcome.observation, execution_mode="dry-run")


def test_validation_only_quarantine_uses_the_existing_evidence_contract() -> None:
    outcome = _validation_only_entrypoint(lease=_quarantined_lease())

    assert outcome.result.status == "quarantined"
    assert isinstance(outcome.quarantine_evidence, QuarantineEvidencePacket)
    assert outcome.observation.quarantine_evidence_built is True
    assert outcome.quarantine_evidence.result_id == outcome.result.result_id
    assert outcome.result.executor_dispatch_attempts == 0


def test_validation_only_returns_the_canonical_pilot_result_unchanged() -> None:
    direct = tsp._run_validation_only()
    outcome = _validation_only_entrypoint()

    assert isinstance(outcome.result, SingleIssuePilotResult)
    assert outcome.result.result_id == direct.result_id
    with pytest.raises(FrozenInstanceError):
        outcome.result.status = "blocked"  # type: ignore[misc]


def test_no_second_runner_or_no_op_executor_exists_in_the_runtime() -> None:
    source = inspect.getsource(runtime_module)
    for forbidden_token in (
        "NoOpExecutor",
        "NullExecutor",
        "RetryManager(",
        "Queue(",
        "Thread(",
    ):
        assert forbidden_token not in source
    # Exactly one orchestrator call site serves both modes.
    assert source.count("result = run_single_issue_pilot(") == 1
