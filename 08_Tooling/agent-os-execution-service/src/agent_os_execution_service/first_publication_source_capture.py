"""Persist #1412 source evidence after one successful authorized validation.

This is the narrow upstream capture seam required by #1830.  It reuses the
existing #762 validation lifecycle, #1412 source-capsule builder/store, the
Scheduler's deterministic pilot-holder identity, and trusted production-host
configuration.  It creates no checkpoint, ResumePlan, route, handoff,
publication, retry, dependency installation, or Scheduler dispatch of its own.
"""
from __future__ import annotations

from typing import Callable

from workflow_scheduler.execution.single_issue_pilot import (
    CancellationProbe,
    PilotLeaseRequest,
    SingleIssuePilotInput,
    pilot_holder_identity,
)

from .authorized_validation import AuthorizedValidationLifecycleRequest
from .authorized_validation_entrypoint import run_authorized_validation_lifecycle
from .pre_publication_evidence_capsule import build_source_pre_publication_evidence
from .pre_publication_evidence_store import append_pre_publication_evidence
from .production_host_bootstrap import load_production_host_configuration
from .validation_lifecycle_evidence import (
    ValidationLifecycleResult,
    ValidationLifecycleTerminalStatus,
)


class FirstPublicationSourceCaptureError(RuntimeError):
    """Successful validation could not be captured as exact #1412 source evidence."""


def _execution_identity(pilot_input: SingleIssuePilotInput) -> str:
    """Reuse the Scheduler-owned deterministic holder for this exact invocation."""
    if not isinstance(pilot_input, SingleIssuePilotInput):
        raise TypeError("pilot_input must be SingleIssuePilotInput")
    if len(pilot_input.issue_numbers) != 1:
        raise FirstPublicationSourceCaptureError("source capture requires exactly one issue")
    request = PilotLeaseRequest(
        repository=pilot_input.repository,
        issue_number=pilot_input.issue_numbers[0],
        invocation_id=pilot_input.invocation_id,
        branch=pilot_input.branch,
        workspace_request_id=pilot_input.workspace_request_id,
        projection_id=pilot_input.expected_projection_id,
        approval_id=pilot_input.expected_approval_id,
        source_head_sha=pilot_input.source_head_sha,
    )
    return pilot_holder_identity(request)


def run_production_authorized_validation_with_source_capture(
    *,
    admission_request: AuthorizedValidationLifecycleRequest,
    evaluated_at: str,
    pilot_input: SingleIssuePilotInput,
    cancelled: CancellationProbe,
    compatibility_decision: object | None = None,
    git_runner: object | None = None,
    process_cancelled: object | None = None,
    changed_paths_inspector: object | None = None,
) -> tuple[ValidationLifecycleResult, str | None]:
    """Run #762 once and persist one source capsule only for a successful lifecycle.

    The caller supplies no store/repository/workspace path.  The checkpoint-store
    root is loaded from the existing trusted ``ProductionHostConfiguration``.
    Non-success terminal results are returned unchanged with ``None`` and perform
    zero #1412 writes.  A successful lifecycle that cannot be captured fails
    closed rather than being reported as publication-ready.
    """
    result = run_authorized_validation_lifecycle(
        admission_request=admission_request,
        evaluated_at=evaluated_at,
        pilot_input=pilot_input,
        cancelled=cancelled,
        compatibility_decision=compatibility_decision,
        git_runner=git_runner,
        process_cancelled=process_cancelled,
        changed_paths_inspector=changed_paths_inspector,
    )
    if result.status is not ValidationLifecycleTerminalStatus.SUCCEEDED:
        return result, None

    configuration = load_production_host_configuration()
    runtime_configuration = admission_request.execution_packet_stage.runtime_configuration
    required_environment_spec = runtime_configuration.required_environment_spec
    if required_environment_spec is None:
        raise FirstPublicationSourceCaptureError(
            "successful validation lacks the required environment specification"
        )

    capsule = build_source_pre_publication_evidence(
        candidate_packet=admission_request.candidate_packet,
        pilot_input=pilot_input,
        required_environment_spec=required_environment_spec,
        execution_id=_execution_identity(pilot_input),
        created_at=evaluated_at,
        expires_at=admission_request.execution_authorization.expires_at,
    )
    outcome = append_pre_publication_evidence(
        configuration.checkpoint_store_root,
        capsule,
    )
    if outcome.capsule_id != capsule.capsule_id:
        raise FirstPublicationSourceCaptureError(
            "persisted source-capsule identity does not match constructed evidence"
        )
    return result, outcome.capsule_id
