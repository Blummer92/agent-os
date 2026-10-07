"""Unit tests for the admitted-mission -> Codespaces production consumer (#3333).

The dispatcher wires choose_governed_runner -> executor_route_inputs ->
select_executor_route -> TransportRequest -> run_codespace_transport. All
external effects are injected as fakes. No test touches the network,
subprocess, or a real Codespace.

The key regression: the happy-path test proves the production consumer
actually reaches run_codespace_transport (via the injected run spy observing
the exact ``gh codespace ssh`` argv), rather than merely testing the transport
in isolation.
"""

from __future__ import annotations

import subprocess

from agent_os_execution_service.executor_routing import (
    ExecutorCapability,
    ExecutorRoute,
)
from scripts.agent_os_execution_interface.codespace_implementation_dispatch import (
    CodespaceDispatchOutcome,
    DispatchReason,
    DispatchStatus,
    dispatch_admitted_operation_to_codespace,
)
from scripts.agent_os_execution_interface.codespaces_orchestrator_transport import (
    CodespaceCandidate,
    TransportReason,
    TransportStatus,
)
from scripts.agent_os_execution_interface.governed_runner_preference import (
    GovernedRunnerCandidate,
    GovernedRunnerKind,
    GovernedRunnerPreferenceReason,
    choose_governed_runner,
)

REPO = "Blummer92/agent-os"
BASE_SHA = "c1101391123c48ff28e91dc8ba0aa31b88598ef2"
CODESPACES_NAME = "happy-codespace"


def _caps(*values: ExecutorCapability) -> tuple[ExecutorCapability, ...]:
    return tuple(sorted(values, key=lambda item: item.value))


REQUIRED_CAPS = _caps(
    ExecutorCapability.CHECKOUT,
    ExecutorCapability.ISOLATED_WORKTREE,
    ExecutorCapability.DEPENDENCY_INSTALLATION,
    ExecutorCapability.PROCESS_EXECUTION,
    ExecutorCapability.TEST_EXECUTION,
    ExecutorCapability.GIT_RECONCILIATION,
)


def _runner_candidate(
    kind: GovernedRunnerKind,
    *,
    available: bool = True,
    current: bool = True,
) -> GovernedRunnerCandidate:
    label = kind.value
    return GovernedRunnerCandidate(
        kind=kind,
        available=available,
        current=current,
        capabilities=REQUIRED_CAPS,
        execution_surface_id=f"execution-surface:{label}",
        environment_profile_id=f"environment-profile:{label}",
        environment_health_evidence_id=f"environment-health:{label}",
        workflow_runtime_identity=f"workflow-runtime:{label}",
    )


def _codespace(name: str = CODESPACES_NAME, state: str = "Available") -> CodespaceCandidate:
    return CodespaceCandidate(
        name=name,
        state=state,
        repository_full_name=REPO,
        owner_login="Blummer92",
    )


def _list_one() -> tuple[CodespaceCandidate, ...]:
    return (_codespace(),)


def _base_kwargs(**overrides):
    kwargs = {
        "issue_identity": "issue:3333",
        "admission_id": "lane-admission:3333",
        "requested_operation": "bounded-implementation",
        "required_capabilities": REQUIRED_CAPS,
        "codespaces_candidate": _runner_candidate(GovernedRunnerKind.CODESPACES),
        "gce_candidate": _runner_candidate(GovernedRunnerKind.GCE),
        "argv": ("git", "status", "--short"),
        "created_at": "2026-10-07T13:00:00Z",
        "expires_at": "2026-10-07T14:00:00Z",
        "execution_service_request_fingerprint": "execution-request:3333-dispatch",
        "operating_mode_decision_id": "operating-mode:3333-dispatch",
        "executable_lane_selection_id": "lane-selection:3333-dispatch",
        "validation_command_plan_id_or_none": "command-plan:3333-dispatch",
        "base_sha_or_none": BASE_SHA,
        "list_candidates": _list_one,
    }
    kwargs.update(overrides)
    return kwargs


class _RunSpy:
    """Fake transport runner that records the exact argv it was given."""

    def __init__(self, result=(0, "stdout-ok", "")):
        self.calls: list[tuple[tuple[str, ...], int]] = []
        self.result = result

    def __call__(self, argv, *, timeout_seconds):
        self.calls.append((tuple(argv), timeout_seconds))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


# --- happy path: the production consumer reaches the transport --------------


def test_dispatched_reaches_run_codespace_transport() -> None:
    """The core regression: dispatching invokes the real transport function.

    The run spy observes the exact ``gh codespace ssh`` argv, which only
    run_codespace_transport constructs. This proves the production consumer
    reaches the transport rather than reimplementing or bypassing it.
    """
    spy = _RunSpy()
    outcome = dispatch_admitted_operation_to_codespace(
        **_base_kwargs(run=spy),
    )
    assert outcome.status is DispatchStatus.DISPATCHED
    assert outcome.reason_codes == (DispatchReason.OK,)
    # #918 evidence is carried on the outcome.
    assert outcome.preference.selected is not None
    assert outcome.preference.selected.kind is GovernedRunnerKind.CODESPACES
    assert outcome.preference.reason_codes == (
        GovernedRunnerPreferenceReason.CODESPACES_CAPABLE,
    )
    assert outcome.route_decision_or_none is not None
    assert (
        outcome.route_decision_or_none.selected_route
        is ExecutorRoute.CHATGPT_GOVERNED_RUNNER
    )
    # The transport was genuinely invoked exactly once, with the ssh argv.
    assert len(spy.calls) == 1
    argv, timeout_seconds = spy.calls[0]
    assert argv[:5] == ("gh", "codespace", "ssh", "-c", CODESPACES_NAME)
    assert argv[5] == "--"
    assert argv[6:] == ("git", "status", "--short")
    assert timeout_seconds == 600
    # The structured result is consumed verbatim into the outcome.
    result = outcome.transport_result_or_none
    assert result is not None
    assert result.status is TransportStatus.COMPLETED
    assert result.reason_codes == (TransportReason.OK,)
    assert result.codespace_name_or_none == CODESPACES_NAME
    assert result.exit_status_or_none == 0
    assert result.stdout_tail == "stdout-ok"
    assert result.issue_identity == "issue:3333"
    assert result.base_sha_or_none == BASE_SHA
    assert result.github_writes_authorized is False
    assert result.publication_authorized is False
    assert result.merge_authorized is False


def test_request_identity_is_deterministic() -> None:
    first = dispatch_admitted_operation_to_codespace(
        **_base_kwargs(run=_RunSpy()),
    )
    second = dispatch_admitted_operation_to_codespace(
        **_base_kwargs(run=_RunSpy()),
    )
    first_id = first.transport_result_or_none.request_id
    second_id = second.transport_result_or_none.request_id
    assert first_id and first_id == second_id


def test_exit_status_and_bounded_evidence_propagate() -> None:
    spy = _RunSpy(result=(1, "o" * 9000, "e" * 9000))
    outcome = dispatch_admitted_operation_to_codespace(
        **_base_kwargs(run=spy),
    )
    result = outcome.transport_result_or_none
    assert result.status is TransportStatus.COMPLETED
    assert result.exit_status_or_none == 1
    assert result.stdout_truncated is True
    assert result.stderr_truncated is True
    assert len(result.stdout_tail) == 4096
    assert len(result.stderr_tail) == 4096


# --- fail-closed before the transport: governed runner ------------------------


def test_gce_selected_does_not_dispatch() -> None:
    spy = _RunSpy()
    outcome = dispatch_admitted_operation_to_codespace(
        **_base_kwargs(
            codespaces_candidate=_runner_candidate(
                GovernedRunnerKind.CODESPACES, available=False
            ),
            run=spy,
        ),
    )
    assert outcome.status is DispatchStatus.NOT_DISPATCHED
    assert outcome.reason_codes == (DispatchReason.GOVERNED_RUNNER_NOT_CODESPACES,)
    assert outcome.route_decision_or_none is None
    assert outcome.transport_result_or_none is None
    assert spy.calls == []


def test_no_capable_runner_does_not_dispatch() -> None:
    spy = _RunSpy()
    outcome = dispatch_admitted_operation_to_codespace(
        **_base_kwargs(
            codespaces_candidate=_runner_candidate(
                GovernedRunnerKind.CODESPACES, available=False
            ),
            gce_candidate=_runner_candidate(GovernedRunnerKind.GCE, available=False),
            run=spy,
        ),
    )
    assert outcome.status is DispatchStatus.NOT_DISPATCHED
    assert outcome.reason_codes == (DispatchReason.GOVERNED_RUNNER_NOT_CODESPACES,)
    assert outcome.preference.selected is None
    assert spy.calls == []


def test_autonomous_host_required_does_not_dispatch() -> None:
    spy = _RunSpy()
    outcome = dispatch_admitted_operation_to_codespace(
        **_base_kwargs(autonomous_host_required=True, run=spy),
    )
    assert outcome.status is DispatchStatus.NOT_DISPATCHED
    assert outcome.reason_codes == (DispatchReason.GOVERNED_RUNNER_NOT_CODESPACES,)
    assert spy.calls == []


# --- fail-closed before the transport: #918 route ------------------------------


def test_stale_evidence_fails_closed() -> None:
    spy = _RunSpy()
    outcome = dispatch_admitted_operation_to_codespace(
        **_base_kwargs(evidence_stale=True, run=spy),
    )
    assert outcome.status is DispatchStatus.NOT_DISPATCHED
    assert outcome.reason_codes == (DispatchReason.ROUTE_NOT_CHATGPT_GOVERNED_RUNNER,)
    assert outcome.route_decision_or_none is not None
    assert (
        outcome.route_decision_or_none.selected_route
        is ExecutorRoute.HUMAN_DECISION_REQUIRED
    )
    assert outcome.transport_result_or_none is None
    assert spy.calls == []


def test_ambiguous_authority_fails_closed() -> None:
    spy = _RunSpy()
    outcome = dispatch_admitted_operation_to_codespace(
        **_base_kwargs(authority_ambiguous=True, run=spy),
    )
    assert outcome.status is DispatchStatus.NOT_DISPATCHED
    assert outcome.reason_codes == (DispatchReason.ROUTE_NOT_CHATGPT_GOVERNED_RUNNER,)
    assert spy.calls == []


def test_excluded_surface_fails_closed() -> None:
    spy = _RunSpy()
    outcome = dispatch_admitted_operation_to_codespace(
        **_base_kwargs(excluded_surface_involved=True, run=spy),
    )
    assert outcome.status is DispatchStatus.NOT_DISPATCHED
    assert spy.calls == []


# --- transport-level failures stay reason-coded on a DISPATCHED outcome -------


def test_zero_qualified_codespaces() -> None:
    spy = _RunSpy()
    outcome = dispatch_admitted_operation_to_codespace(
        **_base_kwargs(list_candidates=lambda: (), run=spy),
    )
    assert outcome.status is DispatchStatus.DISPATCHED
    result = outcome.transport_result_or_none
    assert result.status is TransportStatus.FAILED
    assert result.reason_codes == (TransportReason.NO_QUALIFIED_CODESPACE,)
    assert spy.calls == []


def test_multiple_qualified_codespaces() -> None:
    spy = _RunSpy()
    outcome = dispatch_admitted_operation_to_codespace(
        **_base_kwargs(
            list_candidates=lambda: (_codespace("one"), _codespace("two")),
            run=spy,
        ),
    )
    result = outcome.transport_result_or_none
    assert result.status is TransportStatus.FAILED
    assert result.reason_codes == (TransportReason.MULTIPLE_QUALIFIED_CODESPACES,)
    assert spy.calls == []


def test_codespace_identity_mismatch() -> None:
    spy = _RunSpy()
    outcome = dispatch_admitted_operation_to_codespace(
        **_base_kwargs(codespace_name_or_none="other-codespace", run=spy),
    )
    result = outcome.transport_result_or_none
    assert result.status is TransportStatus.FAILED
    assert result.reason_codes == (TransportReason.CODESPACE_IDENTITY_MISMATCH,)
    assert spy.calls == []


def test_git_push_rejected_through_dispatch() -> None:
    spy = _RunSpy()
    outcome = dispatch_admitted_operation_to_codespace(
        **_base_kwargs(argv=("git", "push", "origin", "branch"), run=spy),
    )
    assert outcome.status is DispatchStatus.DISPATCHED
    result = outcome.transport_result_or_none
    assert result.status is TransportStatus.REJECTED
    assert result.reason_codes == (TransportReason.FORBIDDEN_COMMAND,)
    assert spy.calls == []


def test_gh_payload_rejected_through_dispatch() -> None:
    spy = _RunSpy()
    outcome = dispatch_admitted_operation_to_codespace(
        **_base_kwargs(argv=("gh", "codespace", "list"), run=spy),
    )
    result = outcome.transport_result_or_none
    assert result.status is TransportStatus.REJECTED
    assert result.reason_codes == (TransportReason.FORBIDDEN_COMMAND,)
    assert spy.calls == []


def test_transport_timeout_propagates() -> None:
    spy = _RunSpy(result=subprocess.TimeoutExpired("gh", 600))
    outcome = dispatch_admitted_operation_to_codespace(
        **_base_kwargs(run=spy),
    )
    result = outcome.transport_result_or_none
    assert result.status is TransportStatus.FAILED
    assert result.reason_codes == (TransportReason.TRANSPORT_TIMEOUT,)
    assert result.codespace_name_or_none == CODESPACES_NAME


# --- outcome invariants --------------------------------------------------------


def test_not_dispatched_never_carries_transport_result() -> None:
    outcome = dispatch_admitted_operation_to_codespace(
        **_base_kwargs(evidence_stale=True, run=_RunSpy()),
    )
    assert outcome.status is DispatchStatus.NOT_DISPATCHED
    assert outcome.transport_result_or_none is None
    assert DispatchReason.OK not in outcome.reason_codes


def test_choose_governed_runner_evidence_is_reused_not_recomputed() -> None:
    """The dispatcher consumes the same preference object #918 projected."""
    kwargs = _base_kwargs(run=_RunSpy())
    preference = choose_governed_runner(
        required_capabilities=kwargs["required_capabilities"],
        codespaces=kwargs["codespaces_candidate"],
        gce=kwargs["gce_candidate"],
    )
    outcome = dispatch_admitted_operation_to_codespace(**kwargs)
    assert outcome.preference == preference


def test_missing_validation_plan_id_fails_closed_for_test_execution() -> None:
    """#918 requires a validation command plan id for TEST_EXECUTION."""
    import pytest

    with pytest.raises(ValueError, match="validation_command_plan_id"):
        dispatch_admitted_operation_to_codespace(
            **_base_kwargs(
                validation_command_plan_id_or_none=None, run=_RunSpy()
            ),
        )
