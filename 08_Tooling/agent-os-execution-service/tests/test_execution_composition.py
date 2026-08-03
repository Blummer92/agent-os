"""Focused and bounded-integration tests for the #697 composition boundary."""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from unittest.mock import create_autospec

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
EXEC_SERVICE_SRC = REPOSITORY_ROOT / "08_Tooling/agent-os-execution-service/src"
SCHEDULER_SRC = REPOSITORY_ROOT / "08_Tooling/workflow-scheduler/src"
SCHEDULER_TESTS = REPOSITORY_ROOT / "08_Tooling/workflow-scheduler/tests"
for path in (REPOSITORY_ROOT, EXEC_SERVICE_SRC, SCHEDULER_SRC, SCHEDULER_TESTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import test_single_issue_pilot as tsp  # noqa: E402
from test_concrete_runtime_adapters import ScenarioGitRunner  # noqa: E402

from scripts.agent_os_execution_capabilities import RepositoryIdentity  # noqa: E402
from scripts.agent_os_remote_validation import MAX_PLAN_STRING_LENGTH  # noqa: E402

from agent_os_execution_service import command_planning as command_planning_module  # noqa: E402
from agent_os_execution_service import request_validation as request_validation_module  # noqa: E402
from agent_os_execution_service import execution_composition as module  # noqa: E402
from agent_os_execution_service.command_planning import (  # noqa: E402
    COMMAND_PLAN_SCHEMA_VERSION,
    COMMAND_REGISTRY_VERSION,
    CommandOperation,
    CommandPlanEntry,
    ValidationCommandPlan,
    validation_command_plan_id,
)
from agent_os_execution_service.execution_composition import (  # noqa: E402
    EXECUTION_COMPOSITION_SCHEMA_VERSION,
    ExecutionAuthorizationEvidence,
    ExecutionCompositionResult,
    ExecutionCompositionStatus,
    compose_and_run_validation,
)
from agent_os_execution_service.models import (  # noqa: E402
    EvidenceVisibilityPolicy,
    ExecutionServiceCapability,
    ExecutionServiceInvalidationCondition,
    ExecutionServiceRequest,
)

from workflow_scheduler.execution import concrete_runtime_adapters as adapters_module  # noqa: E402
from workflow_scheduler.execution.concrete_runtime_adapters import (  # noqa: E402
    ConcreteRuntimeConfiguration,
    ConcreteRuntimeExecutionOutcome,
    build_concrete_runtime_adapters,
    run_concrete_runtime_entrypoint_with_validation_evidence,
)
from workflow_scheduler.execution.single_issue_runtime import (  # noqa: E402
    run_single_issue_runtime_entrypoint,
)
from workflow_scheduler.execution.frozen_test_validation_adapter import (  # noqa: E402
    FrozenTestCommand,
)
from workflow_scheduler.execution.single_issue_pilot import (  # noqa: E402
    VALIDATION_ONLY_EXECUTION_MODE,
)

MODULE_PATH = (
    EXEC_SERVICE_SRC
    / "agent_os_execution_service"
    / "execution_composition.py"
)

EVALUATED_AT = "2026-07-29T15:30:00Z"
AUTHORIZED_AT = "2026-07-29T15:20:00Z"
EXPIRES_AT = "2026-07-29T16:20:00Z"


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def _identity() -> RepositoryIdentity:
    return tsp._identity()


def _request(**changes: object) -> ExecutionServiceRequest:
    values: dict[str, object] = {
        "schema_version": "1.0",
        "request_id": "req-560",
        "request_revision": 1,
        "created_at": "2026-07-29T15:00:00Z",
        "expires_at": "2026-07-29T18:00:00Z",
        "repository_identity": _identity(),
        "issue_or_handoff_identity": "560",
        "canonical_owner": "blummer92",
        "requesting_actor": "blummer92",
        "capability": ExecutionServiceCapability.VERIFY_REPOSITORY_STATE,
        "base_branch": tsp.BASE_BRANCH,
        "base_sha": tsp.BASE_SHA,
        "requested_ref": tsp.BRANCH,
        "expected_sha": tsp.HEAD_SHA,
        "allowed_paths": tsp.ALLOWED_FILES,
        "forbidden_paths": tsp.FORBIDDEN_PATHS,
        "inspected_file_count_limit": 10,
        "inspected_byte_limit": 1_000_000,
        "evidence_visibility_policy": EvidenceVisibilityPolicy.PUBLIC_SUMMARY_ONLY,
        "invalidation_conditions": (
            ExecutionServiceInvalidationCondition.EXPECTED_SHA_CHANGED,
        ),
    }
    values.update(changes)
    return ExecutionServiceRequest(**values)  # type: ignore[arg-type]


def _plan_argv() -> tuple[str, ...]:
    """The canonical, registry-recognized argv every ``ValidationCommandPlan``
    entry in this file uses.

    ``execution_composition._identity_mismatches`` unconditionally calls
    ``validation_command_plan_id(command_plan)`` -- with no surrounding
    try/except -- to cross-check the supplied authorization. Since #804,
    that call runs the public command-plan validator and raises for any
    entry argv that is not a member of the private command registry, so
    every ``ValidationCommandPlan`` this file builds must use only
    registry-real argv, not an arbitrary executable one-liner.
    """
    return command_planning_module._COMMAND_REGISTRY["python -m pytest"]


_SECONDARY_REGISTRY_ARGV = command_planning_module._COMMAND_REGISTRY[
    "python -m pytest tests/agent_os_issue_acceptance"
]

# Arbitrary executable argv belongs only here, at the runtime-configuration /
# adapter layer: passed to ``ConcreteRuntimeConfiguration.required_test_commands``
# for a real subprocess run built directly through the real adapters (see
# ``_canonical_outcome`` below), never through a ``ValidationCommandPlan``
# entry passed to ``compose_and_run_validation``.
_PASSING_ADAPTER_ARGV = (sys.executable, "-c", "pass")
_FAILING_ADAPTER_ARGV = (sys.executable, "-c", "import sys; sys.exit(1)")


def _command_plan(
    request: ExecutionServiceRequest, *, profile: str = "focused", argv: tuple[str, ...] | None = None
) -> ValidationCommandPlan:
    operation = {
        "static": CommandOperation.VALIDATION_STATIC,
        "focused": CommandOperation.VALIDATION_FOCUSED,
        "aggregate": CommandOperation.VALIDATION_AGGREGATE,
    }[profile]
    entries: tuple[CommandPlanEntry, ...] = ()
    if profile != "static":
        entries = (CommandPlanEntry(operation=operation, argv=argv or _plan_argv()),)
    return ValidationCommandPlan(
        schema_version=COMMAND_PLAN_SCHEMA_VERSION,
        registry_version=COMMAND_REGISTRY_VERSION,
        repository=request.repository_identity.owner + "/" + request.repository_identity.repository,
        issue_or_handoff_identity=request.issue_or_handoff_identity,
        requested_ref=request.requested_ref,
        expected_sha=request.expected_sha,
        request_revision=request.request_revision,
        request_fingerprint=request.request_fingerprint,
        validation_plan_id=_pilot_input().expected_plan_id,
        validation_plan_schema_version="1.0",
        selector_version="1.0",
        profile=profile,
        command_set_digest="0" * 64,
        entries=entries,
    )


def _authorization(
    request: ExecutionServiceRequest,
    plan: ValidationCommandPlan,
    *,
    execution_authorized: bool = True,
    authorized_at: str = AUTHORIZED_AT,
    expires_at: str = EXPIRES_AT,
) -> ExecutionAuthorizationEvidence:
    return ExecutionAuthorizationEvidence(
        authorization_id="auth-560",
        request_fingerprint=request.request_fingerprint,
        command_plan_id=validation_command_plan_id(plan),
        repository=plan.repository,
        expected_sha=plan.expected_sha,
        authorized_at=authorized_at,
        expires_at=expires_at,
        execution_authorized=execution_authorized,
    )


def _pilot_input(**changes: object):
    values: dict[str, object] = {"execution_mode": VALIDATION_ONLY_EXECUTION_MODE}
    values.update(changes)
    return tsp._pilot_input(**values)


_CONFIGURATION_COUNTER = 0


def _configuration(
    tmp_path: Path, *, argv: tuple[str, ...] | None = None
) -> ConcreteRuntimeConfiguration:
    global _CONFIGURATION_COUNTER
    _CONFIGURATION_COUNTER += 1
    root = tmp_path / f"repository-{_CONFIGURATION_COUNTER}"
    parent = tmp_path / f"worktrees-{_CONFIGURATION_COUNTER}"
    root.mkdir()
    parent.mkdir()
    commands = tuple(
        FrozenTestCommand(test_id=test_id, argv=argv or _plan_argv())
        for test_id in tsp.REQUIRED_TESTS
    )
    return ConcreteRuntimeConfiguration.bind(
        _pilot_input(),
        repository_identity=_identity(),
        repository_root=str(root),
        workspace_parent=str(parent),
        required_test_commands=commands,
        execution_mode=VALIDATION_ONLY_EXECUTION_MODE,
        executor_grace_period_seconds=0.05,
        validation_per_command_timeout_seconds=1.0,
        validation_total_timeout_seconds=5.0,
    )


def _compose(
    tmp_path: Path,
    *,
    profile: str = "focused",
    argv: tuple[str, ...] | None = None,
    execution_authorized: bool = True,
    fail_remove: bool = False,
    cancelled=None,
) -> ExecutionCompositionResult:
    request = _request()
    plan = _command_plan(request, profile=profile, argv=argv)
    authorization = _authorization(request, plan, execution_authorized=execution_authorized)
    configuration = _configuration(tmp_path, argv=argv)
    git_runner = ScenarioGitRunner(configuration, fail_remove=fail_remove)
    return compose_and_run_validation(
        request=request,
        command_plan=plan,
        authorization=authorization,
        evaluated_at=EVALUATED_AT,
        pilot_input=_pilot_input(),
        configuration=configuration,
        cancelled=cancelled or tsp.never_cancelled,
        git_runner=git_runner,
        changed_paths_inspector=lambda: (),
    )


def _canonical_outcome(
    tmp_path: Path,
    *,
    argv: tuple[str, ...],
    lease: object | None = None,
    fail_remove: bool = False,
) -> ConcreteRuntimeExecutionOutcome:
    """Build one real canonical outcome directly through the real adapters.

    This is the runtime-configuration / adapter layer: it never goes through
    ``compose_and_run_validation`` or its command-plan identity check, so an
    arbitrary executable ``argv`` (never a registry command) belongs here.
    The real adapters are built by ``build_concrete_runtime_adapters``, the
    real orchestrator runs once through
    ``run_single_issue_runtime_entrypoint``, and the returned outcome carries
    the real ``SingleIssuePilotResult`` plus the exact
    ``FrozenTestValidationResult`` retained by the real validator. Nothing
    about the outcome is fabricated.
    """
    configuration = _configuration(tmp_path, argv=argv)
    adapters = build_concrete_runtime_adapters(
        _pilot_input(),
        configuration,
        git_runner=ScenarioGitRunner(configuration, fail_remove=fail_remove),
        changed_paths_inspector=lambda: (),
    )
    runtime_outcome = run_single_issue_runtime_entrypoint(
        _pilot_input(),
        lease=lease or tsp.FakeLease(),
        workspace=adapters.workspace,
        executor=adapters.executor,
        validator=adapters.validator,
        cancelled=tsp.never_cancelled,
    )
    return ConcreteRuntimeExecutionOutcome(
        runtime_outcome=runtime_outcome,
        validation_result=adapters.validator.last_result,
    )


def _canonical_passing_outcome(
    tmp_path: Path, *, fail_remove: bool = False
) -> ConcreteRuntimeExecutionOutcome:
    return _canonical_outcome(
        tmp_path, argv=_PASSING_ADAPTER_ARGV, fail_remove=fail_remove
    )


def _canonical_failing_outcome(tmp_path: Path) -> ConcreteRuntimeExecutionOutcome:
    return _canonical_outcome(tmp_path, argv=_FAILING_ADAPTER_ARGV)


def _canonical_outcome_with_failing_release(
    tmp_path: Path,
) -> ConcreteRuntimeExecutionOutcome:
    """One real canonical outcome with passing validation whose lease release
    fails -- reached through the canonical runtime entrypoint one level down.
    """
    return _canonical_outcome(
        tmp_path,
        argv=_PASSING_ADAPTER_ARGV,
        lease=tsp.FakeLease(release_error=RuntimeError("release unavailable")),
    )


def _compose_with_outcome(
    tmp_path: Path,
    outcome: ConcreteRuntimeExecutionOutcome,
    monkeypatch: pytest.MonkeyPatch,
    *,
    profile: str,
) -> ExecutionCompositionResult:
    monkeypatch.setattr(
        module,
        "run_concrete_runtime_entrypoint_with_validation_evidence",
        lambda *a, **k: outcome,
    )
    return _compose(tmp_path, profile=profile)


# --------------------------------------------------------------------------
# Bounded real-current-main integration
# --------------------------------------------------------------------------


def test_focused_pass_uses_real_current_main_and_retains_exact_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The ValidationCommandPlan compose_and_run_validation checks (built by
    # _compose via _compose_with_outcome) uses canonical registry argv; the
    # real pass/fail outcome is built separately, at the runtime-configuration
    # / adapter layer, with its own arbitrary executable argv.
    outcome = _canonical_passing_outcome(tmp_path)
    result = _compose_with_outcome(tmp_path, outcome, monkeypatch, profile="focused")

    assert result.status is ExecutionCompositionStatus.FOCUSED_PASS_AGGREGATE_PENDING
    assert result.aggregate_pending is True
    assert result.merge_authorized is False
    assert result.execution_authorized is True
    assert result.side_effects_performed is True
    assert result.validation_result is not None
    assert result.validation_result.passed is True
    assert result.validation_result.completed_tests == tsp.REQUIRED_TESTS


def test_aggregate_pass_projects_final_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outcome = _canonical_passing_outcome(tmp_path)
    result = _compose_with_outcome(tmp_path, outcome, monkeypatch, profile="aggregate")

    assert result.status is ExecutionCompositionStatus.AGGREGATE_PASS
    assert result.aggregate_pending is False
    assert result.merge_authorized is False


def test_focused_fail_preserves_aggregate_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outcome = _canonical_failing_outcome(tmp_path)
    result = _compose_with_outcome(tmp_path, outcome, monkeypatch, profile="focused")

    assert result.status is ExecutionCompositionStatus.FOCUSED_FAIL
    assert result.aggregate_pending is True
    assert result.validation_result.passed is False


def test_aggregate_fail_is_not_focused_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outcome = _canonical_failing_outcome(tmp_path)
    result = _compose_with_outcome(tmp_path, outcome, monkeypatch, profile="aggregate")

    assert result.status is ExecutionCompositionStatus.AGGREGATE_FAIL
    assert result.aggregate_pending is False


def test_focused_and_aggregate_have_distinct_evidence_identities(tmp_path: Path) -> None:
    focused = _compose(tmp_path, profile="focused")
    aggregate = _compose(tmp_path, profile="aggregate")

    assert focused.evidence_id != aggregate.evidence_id
    assert focused.command_plan_id != aggregate.command_plan_id


def test_static_profile_performs_no_process_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("no entrypoint call is expected for a static plan")

    monkeypatch.setattr(module, "run_concrete_runtime_entrypoint_with_validation_evidence", forbidden)

    result = _compose(tmp_path, profile="static")

    assert result.status is ExecutionCompositionStatus.MANUAL_REVIEW
    assert result.validation_result is None
    assert result.side_effects_performed is False
    assert "unsupported-profile-no-execution" in result.reason_codes


# --------------------------------------------------------------------------
# Identity-binding fail-closed behavior
# --------------------------------------------------------------------------


def test_request_fingerprint_mismatch_fails_closed(tmp_path: Path) -> None:
    request = _request()
    plan = _command_plan(request)
    bad_plan = command_planning_module.ValidationCommandPlan(
        schema_version=plan.schema_version,
        registry_version=plan.registry_version,
        repository=plan.repository,
        issue_or_handoff_identity=plan.issue_or_handoff_identity,
        requested_ref=plan.requested_ref,
        expected_sha=plan.expected_sha,
        request_revision=plan.request_revision,
        request_fingerprint="0" * 64,
        validation_plan_id=plan.validation_plan_id,
        validation_plan_schema_version=plan.validation_plan_schema_version,
        selector_version=plan.selector_version,
        profile=plan.profile,
        command_set_digest=plan.command_set_digest,
        entries=plan.entries,
    )
    authorization = _authorization(request, bad_plan)
    configuration = _configuration(tmp_path)

    result = compose_and_run_validation(
        request=request,
        command_plan=bad_plan,
        authorization=authorization,
        evaluated_at=EVALUATED_AT,
        pilot_input=_pilot_input(),
        configuration=configuration,
        cancelled=tsp.never_cancelled,
        git_runner=ScenarioGitRunner(configuration),
        changed_paths_inspector=lambda: (),
    )

    assert result.status is ExecutionCompositionStatus.MANUAL_REVIEW
    assert "request-fingerprint-mismatch" in result.reason_codes
    assert result.validation_result is None
    assert result.side_effects_performed is False
    assert result.execution_authorized is False


def test_authorization_not_granted_fails_closed(tmp_path: Path) -> None:
    request = _request()
    plan = _command_plan(request)
    authorization = _authorization(request, plan, execution_authorized=False)
    configuration = _configuration(tmp_path)

    result = compose_and_run_validation(
        request=request,
        command_plan=plan,
        authorization=authorization,
        evaluated_at=EVALUATED_AT,
        pilot_input=_pilot_input(),
        configuration=configuration,
        cancelled=tsp.never_cancelled,
        git_runner=ScenarioGitRunner(configuration),
        changed_paths_inspector=lambda: (),
    )

    assert result.status is ExecutionCompositionStatus.MANUAL_REVIEW
    assert "authorization-not-granted" in result.reason_codes


def test_expired_authorization_fails_closed(tmp_path: Path) -> None:
    request = _request()
    plan = _command_plan(request)
    authorization = _authorization(
        request, plan, authorized_at="2026-07-29T10:00:00Z", expires_at="2026-07-29T11:00:00Z"
    )
    configuration = _configuration(tmp_path)

    result = compose_and_run_validation(
        request=request,
        command_plan=plan,
        authorization=authorization,
        evaluated_at=EVALUATED_AT,
        pilot_input=_pilot_input(),
        configuration=configuration,
        cancelled=tsp.never_cancelled,
        git_runner=ScenarioGitRunner(configuration),
        changed_paths_inspector=lambda: (),
    )

    assert result.status is ExecutionCompositionStatus.MANUAL_REVIEW
    assert "authorization-expired-or-not-yet-active" in result.reason_codes


def test_authorization_plan_id_mismatch_fails_closed(tmp_path: Path) -> None:
    request = _request()
    plan = _command_plan(request)
    other_plan = _command_plan(request, argv=_SECONDARY_REGISTRY_ARGV)
    authorization = _authorization(request, other_plan)
    configuration = _configuration(tmp_path)

    result = compose_and_run_validation(
        request=request,
        command_plan=plan,
        authorization=authorization,
        evaluated_at=EVALUATED_AT,
        pilot_input=_pilot_input(),
        configuration=configuration,
        cancelled=tsp.never_cancelled,
        git_runner=ScenarioGitRunner(configuration),
        changed_paths_inspector=lambda: (),
    )

    assert result.status is ExecutionCompositionStatus.MANUAL_REVIEW
    assert "authorization-plan-id-mismatch" in result.reason_codes


def test_argv_mismatch_between_plan_and_configuration_fails_closed(tmp_path: Path) -> None:
    # The plan carries canonical registry argv; the configuration is
    # deliberately bound to a different, arbitrary adapter-layer argv, which
    # ConcreteRuntimeConfiguration never requires to be a registry command.
    request = _request()
    plan = _command_plan(request)
    authorization = _authorization(request, plan)
    configuration = _configuration(tmp_path, argv=_PASSING_ADAPTER_ARGV)

    result = compose_and_run_validation(
        request=request,
        command_plan=plan,
        authorization=authorization,
        evaluated_at=EVALUATED_AT,
        pilot_input=_pilot_input(),
        configuration=configuration,
        cancelled=tsp.never_cancelled,
        git_runner=ScenarioGitRunner(configuration),
        changed_paths_inspector=lambda: (),
    )

    assert result.status is ExecutionCompositionStatus.MANUAL_REVIEW
    assert "command-plan-argv-mismatch" in result.reason_codes


def test_pilot_input_drift_fails_closed_before_execution(tmp_path: Path) -> None:
    request = _request()
    plan = _command_plan(request)
    authorization = _authorization(request, plan)
    configuration = _configuration(tmp_path)
    drifted_input = _pilot_input(invocation_id="different-invocation")

    result = compose_and_run_validation(
        request=request,
        command_plan=plan,
        authorization=authorization,
        evaluated_at=EVALUATED_AT,
        pilot_input=drifted_input,
        configuration=configuration,
        cancelled=tsp.never_cancelled,
        git_runner=ScenarioGitRunner(configuration),
        changed_paths_inspector=lambda: (),
    )

    assert result.status is ExecutionCompositionStatus.MANUAL_REVIEW
    assert "configuration-pilot-input-drift" in result.reason_codes


def test_expected_sha_mismatch_fails_closed(tmp_path: Path) -> None:
    request = _request()
    plan = _command_plan(request)
    bad_plan = command_planning_module.ValidationCommandPlan(
        schema_version=plan.schema_version,
        registry_version=plan.registry_version,
        repository=plan.repository,
        issue_or_handoff_identity=plan.issue_or_handoff_identity,
        requested_ref=plan.requested_ref,
        expected_sha="f" * 40,
        request_revision=plan.request_revision,
        request_fingerprint=plan.request_fingerprint,
        validation_plan_id=plan.validation_plan_id,
        validation_plan_schema_version=plan.validation_plan_schema_version,
        selector_version=plan.selector_version,
        profile=plan.profile,
        command_set_digest=plan.command_set_digest,
        entries=plan.entries,
    )
    authorization = _authorization(request, bad_plan)
    configuration = _configuration(tmp_path)

    result = compose_and_run_validation(
        request=request,
        command_plan=bad_plan,
        authorization=authorization,
        evaluated_at=EVALUATED_AT,
        pilot_input=_pilot_input(),
        configuration=configuration,
        cancelled=tsp.never_cancelled,
        git_runner=ScenarioGitRunner(configuration),
        changed_paths_inspector=lambda: (),
    )

    assert result.status is ExecutionCompositionStatus.MANUAL_REVIEW
    assert "expected-sha-mismatch" in result.reason_codes


def test_requested_ref_and_revision_drift_fail_closed(tmp_path: Path) -> None:
    request = _request()
    plan = _command_plan(request)
    drifted = command_planning_module.ValidationCommandPlan(
        schema_version=plan.schema_version,
        registry_version=plan.registry_version,
        repository=plan.repository,
        issue_or_handoff_identity=plan.issue_or_handoff_identity,
        requested_ref="agent/some-other-branch",
        expected_sha=plan.expected_sha,
        request_revision=plan.request_revision + 1,
        request_fingerprint=plan.request_fingerprint,
        validation_plan_id=plan.validation_plan_id,
        validation_plan_schema_version=plan.validation_plan_schema_version,
        selector_version=plan.selector_version,
        profile=plan.profile,
        command_set_digest=plan.command_set_digest,
        entries=plan.entries,
    )
    configuration = _configuration(tmp_path)

    result = compose_and_run_validation(
        request=request,
        command_plan=drifted,
        authorization=_authorization(request, drifted),
        evaluated_at=EVALUATED_AT,
        pilot_input=_pilot_input(),
        configuration=configuration,
        cancelled=tsp.never_cancelled,
        git_runner=ScenarioGitRunner(configuration),
        changed_paths_inspector=lambda: (),
    )

    assert result.status is ExecutionCompositionStatus.MANUAL_REVIEW
    assert "requested-ref-mismatch" in result.reason_codes
    assert "request-revision-mismatch" in result.reason_codes
    assert result.validation_result is None


def test_command_plan_operation_drift_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An operation/profile-mismatched command plan fails closed to bounded
    manual-review evidence without ever reaching the runtime entrypoint.

    ``compose_and_run_validation`` calls the public command-plan validator
    before ``_identity_mismatches`` or ``_fail_closed`` ever touch the plan,
    so this is caught -- and reported with a stable reason code derived from
    that validator -- before either of those functions' unconditional
    ``validation_command_plan_id`` calls would otherwise raise.
    """

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("no entrypoint call is expected for an invalid command plan")

    monkeypatch.setattr(module, "run_concrete_runtime_entrypoint_with_validation_evidence", forbidden)

    request = _request()
    plan = _command_plan(request, profile="focused")
    drifted = command_planning_module.ValidationCommandPlan(
        schema_version=plan.schema_version,
        registry_version=plan.registry_version,
        repository=plan.repository,
        issue_or_handoff_identity=plan.issue_or_handoff_identity,
        requested_ref=plan.requested_ref,
        expected_sha=plan.expected_sha,
        request_revision=plan.request_revision,
        request_fingerprint=plan.request_fingerprint,
        validation_plan_id=plan.validation_plan_id,
        validation_plan_schema_version=plan.validation_plan_schema_version,
        selector_version=plan.selector_version,
        profile=plan.profile,
        command_set_digest=plan.command_set_digest,
        entries=(
            CommandPlanEntry(
                operation=CommandOperation.VALIDATION_AGGREGATE, argv=_plan_argv()
            ),
        ),
    )
    assert command_planning_module.validate_validation_command_plan(drifted) == (
        "command-plan.profile-operation-mismatch",
    )
    configuration = _configuration(tmp_path)

    result = compose_and_run_validation(
        request=request,
        command_plan=drifted,
        authorization=_authorization(request, plan),
        evaluated_at=EVALUATED_AT,
        pilot_input=_pilot_input(),
        configuration=configuration,
        cancelled=tsp.never_cancelled,
        git_runner=ScenarioGitRunner(configuration),
        changed_paths_inspector=lambda: (),
    )

    assert result.status is ExecutionCompositionStatus.MANUAL_REVIEW
    assert "command-plan-invalid" in result.reason_codes
    assert "command-plan.profile-operation-mismatch" in result.reason_codes
    assert result.validation_result is None
    assert result.execution_authorized is False
    assert result.side_effects_performed is False
    assert result.merge_authorized is False
    assert result.command_plan_id == module._INVALID_COMMAND_PLAN_ID


def test_arbitrary_argv_command_plan_fails_closed_without_runtime_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A command plan whose argv is not a member of the canonical registry
    fails closed to bounded manual-review evidence without ever reaching the
    runtime entrypoint, and without a fabricated canonical command-plan ID.
    """

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("no entrypoint call is expected for an invalid command plan")

    monkeypatch.setattr(module, "run_concrete_runtime_entrypoint_with_validation_evidence", forbidden)

    request = _request()
    plan = _command_plan(request, profile="focused")
    rogue = command_planning_module.ValidationCommandPlan(
        schema_version=plan.schema_version,
        registry_version=plan.registry_version,
        repository=plan.repository,
        issue_or_handoff_identity=plan.issue_or_handoff_identity,
        requested_ref=plan.requested_ref,
        expected_sha=plan.expected_sha,
        request_revision=plan.request_revision,
        request_fingerprint=plan.request_fingerprint,
        validation_plan_id=plan.validation_plan_id,
        validation_plan_schema_version=plan.validation_plan_schema_version,
        selector_version=plan.selector_version,
        profile=plan.profile,
        command_set_digest=plan.command_set_digest,
        entries=(
            CommandPlanEntry(
                operation=CommandOperation.VALIDATION_FOCUSED,
                argv=("rm", "-rf", "/"),
            ),
        ),
    )
    assert command_planning_module.validate_validation_command_plan(rogue) == (
        "command-plan.argv-not-registered",
    )
    configuration = _configuration(tmp_path)

    result = compose_and_run_validation(
        request=request,
        command_plan=rogue,
        authorization=_authorization(request, plan),
        evaluated_at=EVALUATED_AT,
        pilot_input=_pilot_input(),
        configuration=configuration,
        cancelled=tsp.never_cancelled,
        git_runner=ScenarioGitRunner(configuration),
        changed_paths_inspector=lambda: (),
    )

    assert result.status is ExecutionCompositionStatus.MANUAL_REVIEW
    assert "command-plan-invalid" in result.reason_codes
    assert "command-plan.argv-not-registered" in result.reason_codes
    assert result.validation_result is None
    assert result.execution_authorized is False
    assert result.side_effects_performed is False
    assert result.merge_authorized is False
    assert result.command_plan_id == module._INVALID_COMMAND_PLAN_ID


def test_malformed_command_plan_field_fails_closed_without_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An exact-type ``ValidationCommandPlan`` with a malformed field (it
    performs no field validation of its own) fails closed to bounded
    manual-review evidence instead of raising ``AttributeError`` out of
    ``_identity_mismatches``'s unguarded ``command_plan.repository.casefold()``.
    """

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("no entrypoint call is expected for an invalid command plan")

    monkeypatch.setattr(module, "run_concrete_runtime_entrypoint_with_validation_evidence", forbidden)

    request = _request()
    plan = _command_plan(request, profile="focused")
    tampered = command_planning_module.ValidationCommandPlan(
        schema_version=plan.schema_version,
        registry_version=plan.registry_version,
        repository=plan.repository,
        issue_or_handoff_identity=plan.issue_or_handoff_identity,
        requested_ref=plan.requested_ref,
        expected_sha=plan.expected_sha,
        request_revision=plan.request_revision,
        request_fingerprint=plan.request_fingerprint,
        validation_plan_id=plan.validation_plan_id,
        validation_plan_schema_version=plan.validation_plan_schema_version,
        selector_version=plan.selector_version,
        profile=plan.profile,
        command_set_digest=plan.command_set_digest,
        entries=plan.entries,
    )
    object.__setattr__(tampered, "repository", 12345)  # type: ignore[arg-type]
    assert "command-plan.malformed-runtime" in (
        command_planning_module.validate_validation_command_plan(tampered)
    )
    configuration = _configuration(tmp_path)

    result = compose_and_run_validation(
        request=request,
        command_plan=tampered,
        authorization=_authorization(request, plan),
        evaluated_at=EVALUATED_AT,
        pilot_input=_pilot_input(),
        configuration=configuration,
        cancelled=tsp.never_cancelled,
        git_runner=ScenarioGitRunner(configuration),
        changed_paths_inspector=lambda: (),
    )

    assert result.status is ExecutionCompositionStatus.MANUAL_REVIEW
    assert "command-plan-invalid" in result.reason_codes
    assert "command-plan.malformed-runtime" in result.reason_codes
    assert result.repository == "unavailable"
    assert result.command_plan_id == module._INVALID_COMMAND_PLAN_ID


def test_tampered_command_plan_entry_argv_fails_closed_without_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ``CommandPlanEntry`` tampered via ``object.__setattr__`` to carry a
    non-tuple ``argv`` (#804 finding 1) fails the command plan closed to
    bounded manual-review evidence -- never raising out of the public
    command-plan validator's frozenset-membership check, and never reaching
    the runtime entrypoint.
    """

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("no entrypoint call is expected for an invalid command plan")

    monkeypatch.setattr(module, "run_concrete_runtime_entrypoint_with_validation_evidence", forbidden)

    request = _request()
    plan = _command_plan(request, profile="focused")
    authorization = _authorization(request, plan)
    entry = plan.entries[0]
    object.__setattr__(entry, "argv", list(entry.argv))  # type: ignore[arg-type]

    reasons = command_planning_module.validate_validation_command_plan(plan)
    assert reasons == ("command-plan.malformed-runtime",)

    configuration = _configuration(tmp_path)
    result = compose_and_run_validation(
        request=request,
        command_plan=plan,
        authorization=authorization,
        evaluated_at=EVALUATED_AT,
        pilot_input=_pilot_input(),
        configuration=configuration,
        cancelled=tsp.never_cancelled,
        git_runner=ScenarioGitRunner(configuration),
        changed_paths_inspector=lambda: (),
    )

    assert result.status is ExecutionCompositionStatus.MANUAL_REVIEW
    assert "command-plan-invalid" in result.reason_codes
    assert "command-plan.malformed-runtime" in result.reason_codes
    assert result.validation_result is None
    assert result.execution_authorized is False
    assert result.side_effects_performed is False
    assert result.merge_authorized is False
    assert result.command_plan_id == module._INVALID_COMMAND_PLAN_ID


_OVERSIZED_PLAN_TEXT = "y" * (MAX_PLAN_STRING_LENGTH + 1)
_CONTROL_CHARACTER_PLAN_TEXT = "bad\x07text"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("repository", _OVERSIZED_PLAN_TEXT),
        ("profile", _OVERSIZED_PLAN_TEXT),
        ("expected_sha", _OVERSIZED_PLAN_TEXT),
        ("repository", _CONTROL_CHARACTER_PLAN_TEXT),
        ("profile", _CONTROL_CHARACTER_PLAN_TEXT),
        ("expected_sha", _CONTROL_CHARACTER_PLAN_TEXT),
        ("repository", 12345),
        ("profile", 12345),
        ("expected_sha", 12345),
    ],
)
def test_unsafe_command_plan_scalar_text_becomes_unavailable_in_invalid_plan_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    """An invalid ``ValidationCommandPlan`` carrying oversized, control-
    character, or non-string scalar text on ``repository``/``profile``/
    ``expected_sha`` (#804 finding 2) never reflects that raw value into
    ``ExecutionCompositionResult`` or the evidence hash: ``_safe_plan_text``
    bounds it to ``"unavailable"`` instead.
    """

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("no entrypoint call is expected for an invalid command plan")

    monkeypatch.setattr(module, "run_concrete_runtime_entrypoint_with_validation_evidence", forbidden)

    request = _request()
    plan = _command_plan(request, profile="focused")
    tampered = command_planning_module.ValidationCommandPlan(
        schema_version=plan.schema_version,
        registry_version=plan.registry_version,
        repository=plan.repository,
        issue_or_handoff_identity=plan.issue_or_handoff_identity,
        requested_ref=plan.requested_ref,
        expected_sha=plan.expected_sha,
        request_revision=plan.request_revision,
        request_fingerprint=plan.request_fingerprint,
        validation_plan_id=plan.validation_plan_id,
        validation_plan_schema_version=plan.validation_plan_schema_version,
        selector_version=plan.selector_version,
        profile=plan.profile,
        command_set_digest=plan.command_set_digest,
        entries=plan.entries,
    )
    # A bounded control-character repository alone would not trip any
    # existing validator reason (identity-bounds only checks length), so
    # schema_version drift forces the invalid-plan path independently of the
    # field under test.
    object.__setattr__(tampered, "schema_version", "9.9")  # type: ignore[arg-type]
    object.__setattr__(tampered, field, value)  # type: ignore[arg-type]

    reasons = command_planning_module.validate_validation_command_plan(tampered)
    assert reasons
    configuration = _configuration(tmp_path)

    result = compose_and_run_validation(
        request=request,
        command_plan=tampered,
        authorization=_authorization(request, plan),
        evaluated_at=EVALUATED_AT,
        pilot_input=_pilot_input(),
        configuration=configuration,
        cancelled=tsp.never_cancelled,
        git_runner=ScenarioGitRunner(configuration),
        changed_paths_inspector=lambda: (),
    )

    assert result.status is ExecutionCompositionStatus.MANUAL_REVIEW
    assert "command-plan-invalid" in result.reason_codes
    assert result.validation_result is None
    assert result.execution_authorized is False
    assert result.side_effects_performed is False
    assert result.merge_authorized is False
    assert result.command_plan_id == module._INVALID_COMMAND_PLAN_ID
    assert getattr(result, field) == "unavailable"


def test_expired_request_fails_closed(tmp_path: Path) -> None:
    request = _request(expires_at="2026-07-29T15:10:00Z")
    plan = _command_plan(request)
    authorization = _authorization(request, plan)
    configuration = _configuration(tmp_path)

    result = compose_and_run_validation(
        request=request,
        command_plan=plan,
        authorization=authorization,
        evaluated_at=EVALUATED_AT,
        pilot_input=_pilot_input(),
        configuration=configuration,
        cancelled=tsp.never_cancelled,
        git_runner=ScenarioGitRunner(configuration),
        changed_paths_inspector=lambda: (),
    )

    assert result.status is ExecutionCompositionStatus.MANUAL_REVIEW
    assert any(item.startswith("request-invalid:") for item in result.reason_codes)


# --------------------------------------------------------------------------
# Exception policy
# --------------------------------------------------------------------------


def test_ordinary_exception_becomes_bounded_infrastructure_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("adapter exploded")

    monkeypatch.setattr(module, "run_concrete_runtime_entrypoint_with_validation_evidence", boom)

    result = _compose(tmp_path, profile="focused")

    assert result.status is ExecutionCompositionStatus.INFRASTRUCTURE_FAILURE
    assert result.validation_result is None
    assert "infrastructure-failure:runtime-entrypoint-exception" in result.reason_codes


@pytest.mark.parametrize("exc_type", [KeyboardInterrupt, SystemExit, GeneratorExit])
def test_process_control_exceptions_propagate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exc_type: type[BaseException]
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise exc_type()

    monkeypatch.setattr(module, "run_concrete_runtime_entrypoint_with_validation_evidence", boom)

    with pytest.raises(exc_type):
        _compose(tmp_path, profile="focused")


def test_unexpected_return_shape_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        module,
        "run_concrete_runtime_entrypoint_with_validation_evidence",
        lambda *a, **k: "not-an-outcome",
    )

    result = _compose(tmp_path, profile="focused")

    assert result.status is ExecutionCompositionStatus.INFRASTRUCTURE_FAILURE
    assert "infrastructure-failure:unexpected-return-shape" in result.reason_codes


# --------------------------------------------------------------------------
# Validation is never regenerated or rerun
# --------------------------------------------------------------------------


def test_canonical_entrypoint_called_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[object, ...]] = []
    original = module.run_concrete_runtime_entrypoint_with_validation_evidence

    def counting(*args: object, **kwargs: object) -> ConcreteRuntimeExecutionOutcome:
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "run_concrete_runtime_entrypoint_with_validation_evidence", counting)

    _compose(tmp_path, profile="focused")

    assert len(calls) == 1


def test_result_retains_exact_validation_result_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The retained result must be the *same object* the canonical adapter
    # produced, not a rebuilt copy that merely shares its type or values.
    captured: list[ConcreteRuntimeExecutionOutcome] = []
    original = module.run_concrete_runtime_entrypoint_with_validation_evidence

    def capturing(*args: object, **kwargs: object) -> ConcreteRuntimeExecutionOutcome:
        outcome = original(*args, **kwargs)
        captured.append(outcome)
        return outcome

    monkeypatch.setattr(
        module, "run_concrete_runtime_entrypoint_with_validation_evidence", capturing
    )

    result = _compose(tmp_path, profile="focused")

    assert len(captured) == 1
    outcome = captured[0]
    assert result.validation_result is outcome.validation_result
    assert type(result.validation_result).__name__ == "FrozenTestValidationResult"
    assert result.validation_result.attempted is True


# --------------------------------------------------------------------------
# Runtime-status projection: a pass requires a completed canonical lifecycle
# --------------------------------------------------------------------------


def test_aggregate_pass_requires_completed_runtime_not_only_passing_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Real canonical run: validation passes, then worktree removal fails, so
    # the canonical runtime quarantines. Final aggregate success must not be
    # projected over an incomplete lifecycle.
    outcome = _canonical_passing_outcome(tmp_path, fail_remove=True)
    result = _compose_with_outcome(tmp_path, outcome, monkeypatch, profile="aggregate")

    assert result.validation_result is not None
    assert result.validation_result.passed is True
    assert result.status is not ExecutionCompositionStatus.AGGREGATE_PASS
    assert result.status is ExecutionCompositionStatus.INFRASTRUCTURE_FAILURE
    assert result.aggregate_pending is True
    assert result.merge_authorized is False
    assert "runtime-status:quarantined" in result.reason_codes
    assert "runtime-cleanup-errors-present" in result.reason_codes
    assert "runtime-incomplete:pass-withheld" in result.reason_codes
    assert "workspace.filesystem-cleanup-failed" in result.reason_codes
    assert result.side_effects_performed is True


def test_focused_pass_requires_completed_runtime_not_only_passing_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outcome = _canonical_passing_outcome(tmp_path, fail_remove=True)
    result = _compose_with_outcome(tmp_path, outcome, monkeypatch, profile="focused")

    assert result.validation_result is not None
    assert result.validation_result.passed is True
    assert result.status is not ExecutionCompositionStatus.FOCUSED_PASS_AGGREGATE_PENDING
    assert result.status is ExecutionCompositionStatus.INFRASTRUCTURE_FAILURE
    # Aggregate validation is still unproven, so it stays pending.
    assert result.aggregate_pending is True
    assert "runtime-status:quarantined" in result.reason_codes
    assert "runtime-cleanup-errors-present" in result.reason_codes
    assert "workspace.metadata-cleanup-failed" in result.reason_codes


def test_lease_release_failure_is_never_a_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outcome = _canonical_outcome_with_failing_release(tmp_path)
    # Precondition: the canonical run really did pass validation and really
    # did fail release.
    assert outcome.validation_result is not None
    assert outcome.validation_result.passed is True
    assert outcome.runtime_outcome.result.release_errors
    assert outcome.runtime_outcome.result.status == "quarantined"

    result = _compose_with_outcome(tmp_path, outcome, monkeypatch, profile="aggregate")

    assert result.status is ExecutionCompositionStatus.INFRASTRUCTURE_FAILURE
    assert result.aggregate_pending is True
    assert "runtime-release-errors-present" in result.reason_codes
    assert "runtime-incomplete:pass-withheld" in result.reason_codes
    assert "lease.release-failed" in result.reason_codes
    assert result.side_effects_performed is True
    # The exact canonical validation evidence is still retained unchanged.
    assert result.validation_result is outcome.validation_result


def test_quarantined_runtime_with_passing_validation_is_bounded_non_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outcome = _canonical_passing_outcome(tmp_path, fail_remove=True)
    result = _compose_with_outcome(tmp_path, outcome, monkeypatch, profile="aggregate")

    assert result.status in {
        ExecutionCompositionStatus.INFRASTRUCTURE_FAILURE,
        ExecutionCompositionStatus.MANUAL_REVIEW,
    }
    assert result.status not in {
        ExecutionCompositionStatus.AGGREGATE_PASS,
        ExecutionCompositionStatus.FOCUSED_PASS_AGGREGATE_PENDING,
    }
    assert result.merge_authorized is False
    # Quarantine evidence is preserved, never replaced by a success reason.
    assert "runtime-status:quarantined" in result.reason_codes


@pytest.mark.parametrize(
    ("profile", "expected_status", "expected_pending"),
    [
        ("focused", ExecutionCompositionStatus.FOCUSED_PASS_AGGREGATE_PENDING, True),
        ("aggregate", ExecutionCompositionStatus.AGGREGATE_PASS, False),
    ],
)
def test_completed_runtime_with_passing_validation_still_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: str,
    expected_status: ExecutionCompositionStatus,
    expected_pending: bool,
) -> None:
    outcome = _canonical_passing_outcome(tmp_path)
    result = _compose_with_outcome(tmp_path, outcome, monkeypatch, profile=profile)

    assert result.status is expected_status
    assert result.aggregate_pending is expected_pending
    assert "runtime-status:completed" in result.reason_codes
    assert "runtime-incomplete:pass-withheld" not in result.reason_codes
    assert "runtime-cleanup-errors-present" not in result.reason_codes
    assert "runtime-release-errors-present" not in result.reason_codes


def test_canonical_cancellation_maps_to_cancelled(tmp_path: Path) -> None:
    result = _compose(
        tmp_path, profile="aggregate", cancelled=tsp.cancel_at("pre-lease")
    )

    assert result.status is ExecutionCompositionStatus.CANCELLED
    assert result.aggregate_pending is True
    assert result.validation_result is None
    assert "runtime-status:cancelled" in result.reason_codes
    assert "cancellation.requested" in result.reason_codes
    assert result.merge_authorized is False


# --------------------------------------------------------------------------
# No generic pass boolean / authority separation
# --------------------------------------------------------------------------


def test_result_has_no_generic_pass_field() -> None:
    field_names = {f for f in ExecutionCompositionResult.__dataclass_fields__}
    assert "passed" not in field_names
    assert "pass_" not in field_names


def test_merge_authorized_is_always_false(tmp_path: Path) -> None:
    result = _compose(tmp_path, profile="aggregate")
    assert result.merge_authorized is False
    with pytest.raises(Exception):
        result.merge_authorized = True  # type: ignore[misc]


def test_execution_composition_result_is_frozen(tmp_path: Path) -> None:
    result = _compose(tmp_path, profile="focused")
    with pytest.raises(Exception):
        result.status = ExecutionCompositionStatus.AGGREGATE_PASS  # type: ignore[misc]


# --------------------------------------------------------------------------
# Signature-drift protection (autospecced canonical callables)
# --------------------------------------------------------------------------


def test_validate_execution_service_request_signature_drift_fails() -> None:
    autospec = create_autospec(
        request_validation_module.validate_execution_service_request, spec_set=True
    )
    with pytest.raises(TypeError):
        autospec(unexpected_kw="x")


def test_validation_command_plan_id_signature_drift_fails() -> None:
    autospec = create_autospec(command_planning_module.validation_command_plan_id, spec_set=True)
    with pytest.raises(TypeError):
        autospec(plan=object(), unexpected_kw=1)


def test_concrete_runtime_configuration_verify_signature_drift_fails() -> None:
    autospec = create_autospec(ConcreteRuntimeConfiguration.verify, spec_set=True)
    with pytest.raises(TypeError):
        autospec(pilot_input=object(), unexpected_kw=1)


def test_run_concrete_runtime_entrypoint_with_validation_evidence_signature_drift_fails() -> None:
    autospec = create_autospec(
        run_concrete_runtime_entrypoint_with_validation_evidence, spec_set=True
    )
    with pytest.raises(TypeError):
        autospec(unexpected_kw=1)


def test_omitted_required_argument_fails_under_autospec() -> None:
    autospec = create_autospec(
        run_concrete_runtime_entrypoint_with_validation_evidence, spec_set=True
    )
    with pytest.raises(TypeError):
        autospec()


def test_module_imports_real_current_main_symbols_not_a_shadow_copy() -> None:
    assert module.run_concrete_runtime_entrypoint_with_validation_evidence is (
        run_concrete_runtime_entrypoint_with_validation_evidence
    )
    assert module.validate_execution_service_request is (
        request_validation_module.validate_execution_service_request
    )
    assert module.validation_command_plan_id is command_planning_module.validation_command_plan_id


# --------------------------------------------------------------------------
# Architecture-boundary test
# --------------------------------------------------------------------------


_FORBIDDEN_IMPORT_NAMES = frozenset(
    (
        "subprocess",
        "os.system",
        "os.popen",
        "asyncio.create_subprocess_exec",
        "asyncio.create_subprocess_shell",
        "run_bounded_posix_process",
    )
)
_FORBIDDEN_DEFINITION_NAMES = frozenset(
    (
        "lease",
        "retry",
        "queue",
        "scheduler",
        "persistence",
        "parser",
        "validator",
        "runner",
        "commandregistry",
    )
)


def test_no_direct_process_execution_or_duplicate_runtime_imports() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))

    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imported_names.add(f"{node.module}.{alias.name}")
                imported_names.add(alias.name)

    for forbidden in ("subprocess", "os.system", "os.popen", "run_bounded_posix_process"):
        assert forbidden not in imported_names, f"forbidden import found: {forbidden}"

    calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Attribute):
                calls.add(target.attr)
            elif isinstance(target, ast.Name):
                calls.add(target.id)
    assert "system" not in calls
    assert "popen" not in calls
    assert "create_subprocess_exec" not in calls
    assert "create_subprocess_shell" not in calls

    class_names = {
        node.name.lower()
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
    }
    for forbidden in _FORBIDDEN_DEFINITION_NAMES:
        assert not any(forbidden in name for name in class_names), (
            f"a competing '{forbidden}' implementation must not be defined here"
        )

    function_names = {
        node.name.lower()
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert not any("worktree" in name and ("create" in name or "remove" in name) for name in function_names)
