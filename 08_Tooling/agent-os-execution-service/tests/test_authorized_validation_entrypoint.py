"""Table-driven adversarial/end-to-end tests for the #762 authorized-validation entrypoint.

Every accepted-admission scenario here reuses #761's own real, cross-verified
fixtures (``_accepted_admission``/``_pilot_result``/``_workspace_lifecycle_evidence``)
so the evidence objects flowing through the entrypoint are genuine, identity-checked
objects -- never hand-waved stand-ins. The one seam this module owns (the single call
to ``compose_and_run_validation``) is monkeypatched per scenario so each terminal
status in the failure matrix is reachable deterministically and fast; the runtime
call itself (real subprocess execution through the real #758/#759 adapters) is
already covered end-to-end by ``test_execution_composition.py`` and
``test_concrete_runtime_adapters.py``, unchanged and still green.
"""

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

from test_validation_lifecycle_evidence import (  # noqa: E402
    _accepted_admission,
    _admission_request,
    _execution_composition,
    _pilot_result,
    _validation_result,
    _workspace_lifecycle_evidence,
)

from agent_os_execution_service import authorized_validation_entrypoint as module  # noqa: E402
from agent_os_execution_service.authorized_validation import (  # noqa: E402
    AuthorizedValidationAdmissionStatus,
)
from agent_os_execution_service.authorized_validation_entrypoint import (  # noqa: E402
    run_authorized_validation_lifecycle,
)
from agent_os_execution_service.execution_composition import (  # noqa: E402
    ExecutionCompositionStatus,
)
from agent_os_execution_service.validation_lifecycle_evidence import (  # noqa: E402
    ValidationLifecycleTerminalStatus,
)

MODULE_PATH = (
    EXEC_SERVICE_SRC / "agent_os_execution_service" / "authorized_validation_entrypoint.py"
)

_EVALUATED_AT = "2026-08-11T12:10:00Z"


class _CompositionSpy:
    """Records every call; the fixture attaches the response it should return."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.response = None

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self.response is None:
            raise AssertionError("compose_and_run_validation must not be called")
        return self.response


def _never_cancelled() -> bool:
    return False


# --------------------------------------------------------------------------
# Pre-execution admission gates: zero side effects, zero runtime calls
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("override_field", "override_value", "expected_status"),
    [
        (
            "authorized_operation",
            "standard",
            ValidationLifecycleTerminalStatus.BLOCKED,
        ),
    ],
)
def test_blocked_admission_never_spawns_validation(
    tmp_path, monkeypatch, override_field, override_value, expected_status
) -> None:
    request = _admission_request(tmp_path, **{override_field: override_value})
    spy = _CompositionSpy()
    monkeypatch.setattr(module, "compose_and_run_validation", spy)

    result = run_authorized_validation_lifecycle(
        admission_request=request,
        evaluated_at=_EVALUATED_AT,
        pilot_input=object(),
        cancelled=_never_cancelled,
    )

    assert spy.calls == []
    assert result.status is expected_status
    assert result.execution_authorized is False
    assert result.side_effects_performed is False


def test_stale_admission_never_spawns_validation(tmp_path, monkeypatch) -> None:
    request, _ = _accepted_admission(tmp_path)
    stale_authorization = replace(request.execution_authorization, expires_at="2026-08-11T12:06:00Z")
    stale_request = replace(request, execution_authorization=stale_authorization, request_id="")
    spy = _CompositionSpy()
    monkeypatch.setattr(module, "compose_and_run_validation", spy)

    result = run_authorized_validation_lifecycle(
        admission_request=stale_request,
        evaluated_at=_EVALUATED_AT,
        pilot_input=object(),
        cancelled=_never_cancelled,
    )

    assert spy.calls == []
    assert result.status is ValidationLifecycleTerminalStatus.STALE
    assert result.side_effects_performed is False


def test_needs_decision_admission_maps_to_blocked_and_never_spawns_validation(
    tmp_path, monkeypatch
) -> None:
    """#757's NEEDS_DECISION status projects to #761's BLOCKED, the same
    not-yet-authorized posture -- this module adds no status mapping of its
    own, so a pending-approval admission proves the pass-through end to end."""
    from tests.agent_os_candidate_packet.test_compiler import _pending_approval, _pipeline

    _, _, proposal = _pipeline()
    pending_approval = _pending_approval(proposal)
    request = _admission_request(tmp_path, approval_stage=pending_approval)
    spy = _CompositionSpy()
    monkeypatch.setattr(module, "compose_and_run_validation", spy)

    result = run_authorized_validation_lifecycle(
        admission_request=request,
        evaluated_at=_EVALUATED_AT,
        pilot_input=object(),
        cancelled=_never_cancelled,
    )

    assert spy.calls == []
    assert result.status is ValidationLifecycleTerminalStatus.BLOCKED
    assert result.side_effects_performed is False


# --------------------------------------------------------------------------
# Accepted admission: exactly one delegated composition call
# --------------------------------------------------------------------------


def test_accepted_admission_calls_composition_exactly_once_with_unmodified_evidence(
    tmp_path, monkeypatch
) -> None:
    request, admission = _accepted_admission(tmp_path)
    execution_stage = request.execution_packet_stage
    spy = _CompositionSpy()
    validation_result = _validation_result(request, passed=True)
    composition = replace(
        _execution_composition(
            request,
            validation_result=validation_result,
            status=ExecutionCompositionStatus.FOCUSED_PASS_AGGREGATE_PENDING,
        ),
        pilot_result=_pilot_result(request),
        workspace_lifecycle_evidence=_workspace_lifecycle_evidence(request),
    )
    spy.response = composition
    monkeypatch.setattr(module, "compose_and_run_validation", spy)

    pilot_input_sentinel = object()
    cancelled_sentinel = _never_cancelled
    result = run_authorized_validation_lifecycle(
        admission_request=request,
        evaluated_at=_EVALUATED_AT,
        pilot_input=pilot_input_sentinel,
        cancelled=cancelled_sentinel,
    )

    assert len(spy.calls) == 1
    call = spy.calls[0]
    assert call["request"] is execution_stage.request
    assert call["command_plan"] is execution_stage.command_plan
    assert call["configuration"] is execution_stage.runtime_configuration
    assert call["authorization"] is request.execution_authorization
    assert call["pilot_input"] is pilot_input_sentinel
    assert call["cancelled"] is cancelled_sentinel
    assert result.request_id == request.request_id
    assert result.side_effects_performed == composition.side_effects_performed


def test_succeeded_when_composition_and_pilot_and_workspace_all_agree(
    tmp_path, monkeypatch
) -> None:
    request, admission = _accepted_admission(tmp_path, zero_expected_paths=True)
    validation_result = _validation_result(request, passed=True)
    spy = _CompositionSpy()
    spy.response = replace(
        _execution_composition(
            request,
            validation_result=validation_result,
            status=ExecutionCompositionStatus.FOCUSED_PASS_AGGREGATE_PENDING,
        ),
        pilot_result=_pilot_result(request),
        workspace_lifecycle_evidence=_workspace_lifecycle_evidence(request),
    )
    monkeypatch.setattr(module, "compose_and_run_validation", spy)

    result = run_authorized_validation_lifecycle(
        admission_request=request,
        evaluated_at=_EVALUATED_AT,
        pilot_input=object(),
        cancelled=_never_cancelled,
    )

    assert result.status is ValidationLifecycleTerminalStatus.SUCCEEDED
    assert result.execution_authorized is True


def test_validation_failed_is_distinct_from_infrastructure_failure(tmp_path, monkeypatch) -> None:
    request, admission = _accepted_admission(tmp_path)
    validation_result = _validation_result(request, passed=False, outcome="failed")
    spy = _CompositionSpy()
    spy.response = replace(
        _execution_composition(
            request,
            validation_result=validation_result,
            status=ExecutionCompositionStatus.FOCUSED_FAIL,
            pilot_reason_codes=("validation.failed",),
        ),
        pilot_result=_pilot_result(
            request,
            status="failed",
            validation_passed=False,
            reason_codes=("validation.failed",),
        ),
        workspace_lifecycle_evidence=_workspace_lifecycle_evidence(request),
    )
    monkeypatch.setattr(module, "compose_and_run_validation", spy)

    result = run_authorized_validation_lifecycle(
        admission_request=request,
        evaluated_at=_EVALUATED_AT,
        pilot_input=object(),
        cancelled=_never_cancelled,
    )

    assert result.status is ValidationLifecycleTerminalStatus.VALIDATION_FAILED
    assert result.execution_authorized is True


def test_quarantined_dominates_a_passing_validation_result(tmp_path, monkeypatch) -> None:
    from workflow_scheduler.execution.quarantine_review import build_quarantine_evidence_packet

    request, admission = _accepted_admission(tmp_path)
    validation_result = _validation_result(request, passed=True)
    pilot = _pilot_result(request, status="quarantined", reason_codes=("pilot.unexpected-error",))
    spy = _CompositionSpy()
    spy.response = replace(
        _execution_composition(
            request,
            validation_result=validation_result,
            status=ExecutionCompositionStatus.INFRASTRUCTURE_FAILURE,
            pilot_reason_codes=("pilot.unexpected-error",),
        ),
        pilot_result=pilot,
        workspace_lifecycle_evidence=_workspace_lifecycle_evidence(request),
        quarantine_packet=build_quarantine_evidence_packet(pilot),
    )
    monkeypatch.setattr(module, "compose_and_run_validation", spy)

    result = run_authorized_validation_lifecycle(
        admission_request=request,
        evaluated_at=_EVALUATED_AT,
        pilot_input=object(),
        cancelled=_never_cancelled,
    )

    assert result.status is ValidationLifecycleTerminalStatus.QUARANTINED


def test_infrastructure_exception_inside_composition_becomes_evidence_incomplete(
    tmp_path, monkeypatch
) -> None:
    """A #759 preflight failure (or any other runtime exception) is caught inside
    ``compose_and_run_validation`` itself and returned as bounded evidence -- this
    module adds no exception handling or status mapping of its own for it."""
    request, admission = _accepted_admission(tmp_path)
    spy = _CompositionSpy()
    spy.response = replace(
        _execution_composition(
            request,
            validation_result=None,
            status=ExecutionCompositionStatus.INFRASTRUCTURE_FAILURE,
            pilot_reason_codes=("infrastructure-failure:runtime-entrypoint-exception",),
        ),
    )
    monkeypatch.setattr(module, "compose_and_run_validation", spy)

    result = run_authorized_validation_lifecycle(
        admission_request=request,
        evaluated_at=_EVALUATED_AT,
        pilot_input=object(),
        cancelled=_never_cancelled,
    )

    assert result.status is ValidationLifecycleTerminalStatus.EVIDENCE_INCOMPLETE
    # Fail-closed: an infrastructure failure conservatively assumes side
    # effects occurred rather than asserting none did.
    assert result.side_effects_performed is True


# --------------------------------------------------------------------------
# Input contract
# --------------------------------------------------------------------------


def test_rejects_a_non_exact_admission_request_type() -> None:
    with pytest.raises(TypeError):
        run_authorized_validation_lifecycle(
            admission_request=object(),
            evaluated_at=_EVALUATED_AT,
            pilot_input=object(),
            cancelled=_never_cancelled,
        )


# --------------------------------------------------------------------------
# Architecture boundary: thin composition, reuse exactly once
# --------------------------------------------------------------------------


def test_reuses_every_canonical_call_exactly_once() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert source.count("verify_authorized_validation_admission(") == 1
    assert source.count("compose_and_run_validation(") == 1
    assert source.count("build_validation_lifecycle_evidence_bundle(") == 1
    assert source.count("project_validation_lifecycle_result(") == 1


def test_defines_no_second_orchestrator_lease_containment_or_status_model() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    forbidden_tokens = (
        "subprocess",
        "InMemoryLeaseAdapter",
        "HostLocalLeaseAdapter",
        "ContainmentConfig",
        "cgroup_v2_containment",
        "RetryManager",
        "GitWorktreeAdapter",
        "class ",  # this module defines pure functions only, no new types
    )
    for token in forbidden_tokens:
        assert token not in source, token


def test_module_defines_no_status_literals_of_its_own() -> None:
    """Every terminal-status token in this module must come from an imported
    enum member access, never a bare string literal this module invented."""
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    status_like_literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value
        in {
            "succeeded",
            "blocked",
            "stale",
            "timed-out",
            "cancelled",
            "quarantined",
            "cleanup-failed",
            "release-failed",
            "termination-uncertain",
            "evidence-incomplete",
            "validation-failed",
        }
    }
    assert status_like_literals == set()
