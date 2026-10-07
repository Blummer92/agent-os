"""Production consumer: admitted implementation mission -> Codespaces transport (#3333).

This module is the single repository-owned production seam that wires an
already lane-admitted ChatGPT Orchestrator implementation mission through the
documented #2299 composition chain into the #3335 transport:

.. code-block:: text

    choose_governed_runner(...)
    -> require CODESPACES selected
    -> executor_route_inputs(...)
    -> select_executor_route(...)
    -> require CHATGPT_GOVERNED_RUNNER
    -> TransportRequest(...)
    -> run_codespace_transport(...)
    -> TransportResult consumed into the mission evidence record

It creates no executor router, transport, Scheduler, queue, continuation
framework, shell, credential system, or source of truth: every step calls an
existing component. It grants no authority of its own: lane admission
(``issue_identity`` / ``admission_id``), the bounded argv, the runner
observations, and the #918 decision metadata are caller-held evidence, and
every GitHub / publication / merge / external-write authority flag is passed
to #918 as an explicit deny.

Fail-closed junctions, stated plainly:

- governed runner not CODESPACES (GCE selected, none capable, stale, or
  autonomous-host-required) -> NOT_DISPATCHED before any #918 selection;
- #918 does not select CHATGPT_GOVERNED_RUNNER (including HUMAN_DECISION_REQUIRED
  forced by any caller-supplied ambiguity/staleness flag) -> NOT_DISPATCHED
  before any transport;
- forbidden argv, zero/multiple/mismatched Codespaces, timeout, transport
  errors -> the transport itself returns the reason-coded TransportResult; the
  outcome stays DISPATCHED because the transport was genuinely invoked.

Currentness boundary, stated plainly: the dispatcher BINDS admission,
base-SHA, workdir, Codespace-identity, and execution-surface/profile evidence
into the deterministic request id and the returned TransportResult; it does not
re-verify lane-admission staleness and does not prove the remote Codespace HEAD
against ``base_sha_or_none`` before execution. Stale admission/scope/base
evidence is the Safe Implementation Lane currentness gate's canonical owner;
the transport's recorded-only base-SHA/workdir semantics are #3335's merged
contract. A future scoped change may compose a remote-HEAD preflight out of
this same transport without changing the seam.

All external effects are injected (``list_candidates`` / ``run`` are passed
through to the transport), so the module is fully testable with fakes and
performs no network or subprocess I/O unless the caller supplies the default
implementations.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

from agent_os_execution_service.executor_routing import (
    ExecutorCapability,
    ExecutorRoute,
    ExecutorRouteDecision,
    select_executor_route,
)

from scripts.agent_os_execution_interface.codespaces_orchestrator_transport import (
    DEFAULT_TIMEOUT_SECONDS,
    REPOSITORY,
    CodespaceCandidate,
    TransportRequest,
    TransportResult,
    default_list_candidates,
    default_run,
    run_codespace_transport,
)
from scripts.agent_os_execution_interface.governed_runner_preference import (
    GovernedRunnerCandidate,
    GovernedRunnerKind,
    GovernedRunnerPreference,
    choose_governed_runner,
    executor_route_inputs,
)


class DispatchStatus(str, Enum):
    """Whether the admitted operation reached the Codespaces transport."""

    DISPATCHED = "dispatched"
    NOT_DISPATCHED = "not-dispatched"


class DispatchReason(str, Enum):
    """Reason-coded outcomes. Every outcome carries at least one."""

    OK = "ok"
    GOVERNED_RUNNER_NOT_CODESPACES = "governed-runner-not-codespaces"
    ROUTE_NOT_CHATGPT_GOVERNED_RUNNER = "route-not-chatgpt-governed-runner"


@dataclass(frozen=True, slots=True, kw_only=True)
class CodespaceDispatchOutcome:
    """Deterministic evidence for one dispatch attempt.

    DISPATCHED means ``run_codespace_transport`` was genuinely invoked; the
    transport's own reason-coded TransportResult (including its rejections and
    failures) is carried verbatim. NOT_DISPATCHED means a fail-closed junction
    stopped the attempt before any transport; ``transport_result_or_none`` is
    then None and no Codespace was contacted.
    """

    status: DispatchStatus
    reason_codes: tuple[DispatchReason, ...]
    issue_identity: str
    admission_id: str
    preference: GovernedRunnerPreference
    route_decision_or_none: ExecutorRouteDecision | None
    transport_result_or_none: TransportResult | None

    def __post_init__(self) -> None:
        if type(self.status) is not DispatchStatus:
            raise TypeError("status must be an exact DispatchStatus")
        if (
            type(self.reason_codes) is not tuple
            or not self.reason_codes
            or any(type(item) is not DispatchReason for item in self.reason_codes)
        ):
            raise ValueError("reason_codes must be a non-empty tuple of DispatchReason")
        if type(self.preference) is not GovernedRunnerPreference:
            raise TypeError("preference must be an exact GovernedRunnerPreference")
        decision = self.route_decision_or_none
        if decision is not None and type(decision) is not ExecutorRouteDecision:
            raise TypeError(
                "route_decision_or_none must be an exact ExecutorRouteDecision or None"
            )
        result = self.transport_result_or_none
        if result is not None and type(result) is not TransportResult:
            raise TypeError(
                "transport_result_or_none must be an exact TransportResult or None"
            )
        if self.status is DispatchStatus.DISPATCHED:
            if result is None:
                raise ValueError("dispatched outcomes must carry a TransportResult")
            if DispatchReason.OK not in self.reason_codes:
                raise ValueError("dispatched outcomes must carry the ok reason")
        else:
            if result is not None:
                raise ValueError(
                    "not-dispatched outcomes must not carry a TransportResult"
                )
            if decision is None and (
                self.preference.selected is not None
                and self.preference.selected.kind is GovernedRunnerKind.CODESPACES
            ):
                raise ValueError(
                    "a CODESPACES preference requires a route decision before "
                    "not-dispatched"
                )


def dispatch_admitted_operation_to_codespace(
    *,
    issue_identity: str,
    admission_id: str,
    requested_operation: str,
    required_capabilities: tuple[ExecutorCapability, ...],
    codespaces_candidate: GovernedRunnerCandidate,
    gce_candidate: GovernedRunnerCandidate,
    argv: tuple[str, ...],
    created_at: str,
    expires_at: str,
    execution_service_request_fingerprint: str,
    operating_mode_decision_id: str,
    executable_lane_selection_id: str,
    autonomous_host_required: bool = False,
    invalidation_conditions: tuple[str, ...] = (),
    external_fallback_available: bool = False,
    external_fallback_explicitly_permitted: bool = False,
    external_fallback_capabilities: tuple[ExecutorCapability, ...] | None = None,
    validation_command_plan_id_or_none: str | None = None,
    authority_ambiguous: bool = False,
    ownership_ambiguous: bool = False,
    source_of_truth_ambiguous: bool = False,
    target_ambiguous: bool = False,
    scope_ambiguous: bool = False,
    excluded_surface_involved: bool = False,
    evidence_stale: bool = False,
    evidence_contradictory: bool = False,
    irreversible_or_uncertain_mutation: bool = False,
    codespace_name_or_none: str | None = None,
    base_sha_or_none: str | None = None,
    workdir_or_none: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    list_candidates: Callable[
        [], tuple[CodespaceCandidate, ...]
    ] = default_list_candidates,
    run: Callable[..., tuple[int, str, str]] = default_run,
) -> CodespaceDispatchOutcome:
    """Dispatch one admitted bounded operation to the current qualified Codespace.

    The caller is the already lane-authorized ChatGPT Orchestrator mission loop:
    it holds the Safe Implementation Lane admission, composes the bounded argv,
    and supplies the runner observations plus the #918 decision metadata. This
    function only wires those existing pieces together and fails closed at
    every junction. It never invents commands, never grants GitHub authority,
    and never contacts a Codespace unless #918 selects CHATGPT_GOVERNED_RUNNER
    for the CODESPACES governed runner.
    """
    preference = choose_governed_runner(
        required_capabilities=required_capabilities,
        codespaces=codespaces_candidate,
        gce=gce_candidate,
        autonomous_host_required=autonomous_host_required,
    )
    selected = preference.selected
    if selected is None or selected.kind is not GovernedRunnerKind.CODESPACES:
        return CodespaceDispatchOutcome(
            status=DispatchStatus.NOT_DISPATCHED,
            reason_codes=(DispatchReason.GOVERNED_RUNNER_NOT_CODESPACES,),
            issue_identity=issue_identity,
            admission_id=admission_id,
            preference=preference,
            route_decision_or_none=None,
            transport_result_or_none=None,
        )

    route_inputs = executor_route_inputs(preference)
    decision = select_executor_route(
        repository=REPOSITORY,
        issue_or_handoff_identity=issue_identity,
        requested_operation=requested_operation,
        required_capabilities=required_capabilities,
        external_fallback_available=external_fallback_available,
        external_fallback_explicitly_permitted=external_fallback_explicitly_permitted,
        external_fallback_capabilities=external_fallback_capabilities,
        created_at=created_at,
        expires_at=expires_at,
        invalidation_conditions=invalidation_conditions,
        authority_ambiguous=authority_ambiguous,
        ownership_ambiguous=ownership_ambiguous,
        source_of_truth_ambiguous=source_of_truth_ambiguous,
        target_ambiguous=target_ambiguous,
        scope_ambiguous=scope_ambiguous,
        excluded_surface_involved=excluded_surface_involved,
        evidence_stale=evidence_stale,
        evidence_contradictory=evidence_contradictory,
        irreversible_or_uncertain_mutation=irreversible_or_uncertain_mutation,
        execution_service_request_fingerprint_or_none=(
            execution_service_request_fingerprint
        ),
        validation_command_plan_id_or_none=validation_command_plan_id_or_none,
        operating_mode_decision_id_or_none=operating_mode_decision_id,
        executable_lane_selection_id_or_none=executable_lane_selection_id,
        execution_authorized=False,
        github_writes_authorized=False,
        external_writes_authorized=False,
        merge_authorized=False,
        **route_inputs,
    )
    if decision.selected_route is not ExecutorRoute.CHATGPT_GOVERNED_RUNNER:
        return CodespaceDispatchOutcome(
            status=DispatchStatus.NOT_DISPATCHED,
            reason_codes=(DispatchReason.ROUTE_NOT_CHATGPT_GOVERNED_RUNNER,),
            issue_identity=issue_identity,
            admission_id=admission_id,
            preference=preference,
            route_decision_or_none=decision,
            transport_result_or_none=None,
        )

    request = TransportRequest(
        repository=REPOSITORY,
        issue_identity=issue_identity,
        admission_id=admission_id,
        argv=argv,
        codespace_name_or_none=codespace_name_or_none,
        base_sha_or_none=base_sha_or_none,
        workdir_or_none=workdir_or_none,
        timeout_seconds=timeout_seconds,
    )
    result = run_codespace_transport(
        request, list_candidates=list_candidates, run=run
    )
    return CodespaceDispatchOutcome(
        status=DispatchStatus.DISPATCHED,
        reason_codes=(DispatchReason.OK,),
        issue_identity=issue_identity,
        admission_id=admission_id,
        preference=preference,
        route_decision_or_none=decision,
        transport_result_or_none=result,
    )
