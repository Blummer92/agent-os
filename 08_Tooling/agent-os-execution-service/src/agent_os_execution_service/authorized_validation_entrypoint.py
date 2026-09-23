"""WSC-AUTO1F end-to-end authorized validation entrypoint (#762).

Composes the already-canonical #757 admission verifier, the #758/#759
concrete-runtime seams reused unmodified through
``execution_composition.compose_and_run_validation``, and the #761 unified
lifecycle evidence bundle / terminal-result projection into one call. This
module owns none of that logic: it is a thin ordering and evidence-assembly
layer only, and performs no execution, admission, or status-precedence
decision of its own.

#1409 also exposes the production publication boundary for an admitted
lifecycle. It reuses the exact admission request objects already owned here and
accepts only the missing canonical #1243 references (route decision, checkpoint,
ResumePlan, and dependency readiness) before delegating exactly once to
``publish_governed_handoff``. It creates no descriptor, handoff, persistence,
authorization, retry, lease, or Scheduler semantics of its own.

No validation is ever spawned unless #757 admission is ACCEPTED. #1201 may
additionally require a caller-supplied execution-dispatch compatibility decision;
that decision is consumed here only as a fail-closed pre-dispatch guard and does
not alter #757 admission semantics. #759 containment preflight (when the caller's
runtime configuration names a ``delegated_parent_cgroup``) happens inside the
single, already-canonical ``compose_and_run_validation`` call -- before the #758
lease or the worktree exist for this invocation -- see
``workflow_scheduler.execution.concrete_runtime_adapters._preflight_containment``.

Do not add a second orchestrator, lease/containment/workspace/evidence
implementation, retry loop, or status-mapping table here: every terminal
status this module returns comes from #761's single, unmodified precedence
table in ``validation_lifecycle_evidence.project_validation_lifecycle_result``.
"""

from __future__ import annotations

from pathlib import Path

from scripts.agent_os_execution_capabilities.dependencies import DependencyReadinessEvidence
from scripts.agent_os_execution_checkpoint.models import ExecutionCheckpoint
from scripts.agent_os_execution_checkpoint.resume_planner import ResumePlan
from workflow_scheduler.execution.single_issue_pilot import (
    CancellationProbe,
    SingleIssuePilotInput,
)

from scripts.agent_os_issue_acceptance.evidence_compatibility import (
    CompatibilityContext,
    CompatibilityOutcome,
    EvidenceCompatibilityDecision,
)

from .authorized_validation import (
    AuthorizedValidationAdmissionStatus,
    AuthorizedValidationLifecycleRequest,
    verify_authorized_validation_admission,
)
from .execution_composition import compose_and_run_validation
from .executor_routing import ExecutorHandoff, ExecutorRouteDecision
from .handoff_publication import publish_governed_handoff
from .validation_lifecycle_evidence import (
    ValidationLifecycleResult,
    build_validation_lifecycle_evidence_bundle,
    project_validation_lifecycle_result,
)


def _require_dispatch_compatibility(
    decision: EvidenceCompatibilityDecision | None,
) -> None:
    """Fail closed before execution when #1201 evidence is mixed-generation."""

    if decision is None:
        return
    if type(decision) is not EvidenceCompatibilityDecision:
        raise TypeError("compatibility_decision must be exact EvidenceCompatibilityDecision")
    if decision.context is not CompatibilityContext.EXECUTION_DISPATCH:
        raise ValueError("compatibility_decision must use execution-dispatch context")
    if decision.outcome is not CompatibilityOutcome.COMPATIBLE:
        reasons = ",".join(decision.reason_codes)
        owners = ",".join(decision.reacquire_owners) or "none"
        raise RuntimeError(
            "execution dispatch blocked by evidence compatibility: "
            f"outcome={decision.outcome.value}; reasons={reasons}; "
            f"reacquire={owners}; decision={decision.decision_id}"
        )


def publish_authorized_validation_handoff(
    store_root: Path | str,
    *,
    admission_request: AuthorizedValidationLifecycleRequest,
    route_decision: ExecutorRouteDecision,
    checkpoint: ExecutionCheckpoint,
    resume_plan: ResumePlan,
    dependency_readiness: DependencyReadinessEvidence,
    evaluated_at: str,
    pilot_input: SingleIssuePilotInput,
    required_return_evidence: tuple[str, ...],
    stop_conditions: tuple[str, ...],
    compatibility_decision: EvidenceCompatibilityDecision | None = None,
) -> ExecutorHandoff:
    """Publish one admitted lifecycle through the existing #1243 seam.

    The admission request already owns the current request, execution
    authorization, CandidatePacket, and concrete runtime configuration. The
    caller supplies only the canonical references not carried by #757. No
    publication object is reconstructed here and no runnable handoff is exposed
    unless ``publish_governed_handoff`` completes successfully.
    """
    if not isinstance(admission_request, AuthorizedValidationLifecycleRequest):
        raise TypeError(
            "admission_request must be exact AuthorizedValidationLifecycleRequest"
        )

    admission_result = verify_authorized_validation_admission(
        admission_request, evaluated_at=evaluated_at
    )
    if admission_result.status is not AuthorizedValidationAdmissionStatus.ACCEPTED:
        raise RuntimeError(
            "governed handoff publication requires accepted authorized-validation admission"
        )

    _require_dispatch_compatibility(compatibility_decision)
    execution_stage = admission_request.execution_packet_stage
    return publish_governed_handoff(
        store_root,
        request=execution_stage.request,
        route_decision=route_decision,
        authorization=admission_request.execution_authorization,
        checkpoint=checkpoint,
        resume_plan=resume_plan,
        candidate_packet=admission_request.candidate_packet,
        runtime_configuration=execution_stage.runtime_configuration,
        dependency_readiness=dependency_readiness,
        pilot_input=pilot_input,
        evaluated_at=evaluated_at,
        required_return_evidence=required_return_evidence,
        stop_conditions=stop_conditions,
    )


def run_authorized_validation_lifecycle(
    *,
    admission_request: AuthorizedValidationLifecycleRequest,
    evaluated_at: str,
    pilot_input: SingleIssuePilotInput,
    cancelled: CancellationProbe,
    compatibility_decision: EvidenceCompatibilityDecision | None = None,
    git_runner: object | None = None,
    process_cancelled: object | None = None,
    changed_paths_inspector: object | None = None,
) -> ValidationLifecycleResult:
    """Run the one authorized-validation lifecycle sequence and return its terminal result.

    1. Verify #757 admission. A non-accepted admission returns immediately
       with zero runtime evidence and zero side effects: no lease, no
       worktree, no #759 containment, no validation spawn.
    2. When accepted, require any caller-supplied #1201 execution-dispatch
       compatibility decision to be COMPATIBLE before delegating to runtime.
       The compatibility decision never grants admission or execution authority.
    3. Delegate exactly once to the canonical ``compose_and_run_validation``
       (which itself delegates exactly once to
       ``run_concrete_runtime_entrypoint_with_validation_evidence``): #759
       containment preflight, #758 lease acquisition, worktree creation,
       #760 initial capture, the one authorized validation run, #760 final
       capture, cleanup, and release all happen inside that one call, in
       that fixed order, through the unmodified Workflow Scheduler
       lifecycle -- never duplicated here.
    4. Assemble the #761 bundle from exactly the evidence that single call
       produced, and project the one terminal result from it. #761's
       precedence table is reused unmodified; this function adds no status
       of its own.

    The three canonical objects the accepted path needs
    (``ExecutionServiceRequest``, ``ValidationCommandPlan``,
    ``ConcreteRuntimeConfiguration``) are read from
    ``admission_request.execution_packet_stage`` -- already independently
    re-verified as present and non-drifted by #757 admission itself -- so
    this function never re-derives or duplicates that identity check.
    """
    if not isinstance(admission_request, AuthorizedValidationLifecycleRequest):
        raise TypeError(
            "admission_request must be exact AuthorizedValidationLifecycleRequest"
        )

    admission_result = verify_authorized_validation_admission(
        admission_request, evaluated_at=evaluated_at
    )

    execution_composition = None
    if admission_result.status is AuthorizedValidationAdmissionStatus.ACCEPTED:
        _require_dispatch_compatibility(compatibility_decision)
        execution_stage = admission_request.execution_packet_stage
        execution_composition = compose_and_run_validation(
            request=execution_stage.request,
            command_plan=execution_stage.command_plan,
            authorization=admission_request.execution_authorization,
            evaluated_at=evaluated_at,
            pilot_input=pilot_input,
            configuration=execution_stage.runtime_configuration,
            cancelled=cancelled,
            git_runner=git_runner,
            process_cancelled=process_cancelled,
            changed_paths_inspector=changed_paths_inspector,
        )

    bundle = build_validation_lifecycle_evidence_bundle(
        evaluated_at=evaluated_at,
        admission_request=admission_request,
        admission_result=admission_result,
        execution_composition=execution_composition,
        pilot_result=(
            execution_composition.pilot_result
            if execution_composition is not None
            else None
        ),
        workspace_lifecycle_evidence=(
            execution_composition.workspace_lifecycle_evidence
            if execution_composition is not None
            else None
        ),
        quarantine_packet=(
            execution_composition.quarantine_packet
            if execution_composition is not None
            else None
        ),
    )
    return project_validation_lifecycle_result(bundle, evaluated_at=evaluated_at)
