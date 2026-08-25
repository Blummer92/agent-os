"""Production factory for the installed governed-resume module path (#1217).

This is the smallest bridge from the fixed #1238 argv contract to the already
canonical #1319 host bootstrap. It does not own currentness, authorization,
dependency readiness, validation semantics, Scheduler admission, leases,
retries, or execution. AOS-EXECSIMPL1 (#1338) now consumes the canonical
RuntimeExecutionRequest first, with bounded legacy reconstruction only when that
request is genuinely absent, then delegates to #1319.

The restart capsule already persists the canonical validation bundle and the
expected advisory identity. Rebuilding that advisory uses the existing
``evaluate_advisory_pre_pr_evidence`` function and requires the recomputed
identity to equal the capsule; no second validation store or status mapping is
introduced here.
"""

from __future__ import annotations

from collections.abc import Mapping

from scripts.agent_os_candidate_packet_live_input.repository_reader import (
    LiveRepositoryEvidenceReader,
)
from scripts.agent_os_execution_capabilities.approved_projection import (
    GOVERNED_PROJECTION_EVIDENCE_SCHEMA_VERSION,
    GovernedProjectionEvidenceResult,
)
from scripts.agent_os_execution_capabilities.models import (
    RepositoryEvidenceType,
    RepositoryIdentity,
)
from scripts.agent_os_execution_checkpoint.dependency_readiness_store import (
    load_dependency_readiness,
)
from scripts.agent_os_execution_checkpoint.invocation_descriptor import (
    GovernedInvocationDescriptor,
)
from scripts.agent_os_remote_validation.advisory_gate import (
    advisory_evidence_result_id,
    evaluate_advisory_pre_pr_evidence,
)
from scripts.agent_os_remote_validation.evidence_bundle import SuppliedCommandResult
from scripts.agent_os_remote_validation.models import ValidationPlan
from scripts.agent_os_remote_validation.selector import validation_plan_id

from .governed_resume_entrypoint import GovernedResumeBindings
from .governed_resume_restart_capsule import GovernedResumeRestartCapsule
from .host_github_read_transport import build_host_github_read_transport_from_environment
from .production_host_bootstrap import (
    ProductionHostBootstrapError,
    build_production_host_bootstrap,
    build_subprocess_verifier_runner,
    canonical_evaluated_at,
    load_production_host_configuration,
)
from .runtime_execution_request import load_runtime_execution_request_or_legacy


class ProductionGovernedResumeFactoryError(RuntimeError):
    """Production entrypoint evidence could not be composed safely."""


def build_production_governed_resume_bindings_for_handoff(
    handoff_id: str,
) -> GovernedResumeBindings:
    """Build the canonical #1319 bindings for one immutable handoff identity."""
    try:
        configuration = load_production_host_configuration()
        evaluated_at = canonical_evaluated_at()
        loaded = load_runtime_execution_request_or_legacy(
            configuration.checkpoint_store_root, handoff_id
        )
        descriptor = loaded.request.invocation_descriptor
        capsule = loaded.request.restart_capsule
        _bind_descriptor_and_capsule(descriptor, capsule, handoff_id)

        readiness = load_dependency_readiness(
            configuration.checkpoint_store_root,
            descriptor.dependency_readiness_evidence_id,
        )
        advisory = _rebuild_advisory_result(descriptor, capsule)
        repository_reader = LiveRepositoryEvidenceReader(
            repository=descriptor.repository,
            issue_number=descriptor.issue_number,
            required_environment_spec=capsule.required_environment_spec,
            dependency_readiness=readiness,
            validation_result=advisory,
            evaluated_at=evaluated_at,
            expected_validation_plan_id=capsule.validation_plan_id,
        )

        transport = build_host_github_read_transport_from_environment()
        bootstrap = build_production_host_bootstrap(
            issue_transport=transport,
            authorization_transport=transport,
            repository_evidence_reader=repository_reader,
            run_verifier=build_subprocess_verifier_runner(),
            configuration=configuration,
            evaluated_at=evaluated_at,
        )
        return bootstrap.governed_resume_bindings(cancelled=_no_cancellation_requested)
    except ProductionGovernedResumeFactoryError:
        raise
    except (TypeError, ValueError, LookupError, OSError, RuntimeError) as exc:
        raise ProductionGovernedResumeFactoryError(
            "production governed-resume composition failed closed"
        ) from exc


def _bind_descriptor_and_capsule(
    descriptor: GovernedInvocationDescriptor,
    capsule: GovernedResumeRestartCapsule,
    handoff_id: str,
) -> None:
    if type(descriptor) is not GovernedInvocationDescriptor:
        raise ProductionGovernedResumeFactoryError("invocation descriptor is malformed")
    if type(capsule) is not GovernedResumeRestartCapsule:
        raise ProductionGovernedResumeFactoryError("restart capsule is malformed")
    packet = capsule.candidate_packet
    if (
        descriptor.handoff_id != handoff_id
        or capsule.handoff_id != handoff_id
        or packet.packet_id != descriptor.candidate_packet_id
        or packet.repository.casefold() != descriptor.repository.casefold()
        or packet.issue_number != descriptor.issue_number
        or packet.invocation_id != descriptor.invocation_id
        or packet.candidate_sha != descriptor.source_sha
        or capsule.required_environment_spec.required_environment_id
        != descriptor.required_environment_id
    ):
        raise ProductionGovernedResumeFactoryError(
            "invocation descriptor and restart capsule do not bind the same subject"
        )


def _rebuild_advisory_result(
    descriptor: GovernedInvocationDescriptor,
    capsule: GovernedResumeRestartCapsule,
):
    payload = capsule.validation_bundle_payload()
    plan = _validation_plan(payload)
    if validation_plan_id(plan) != capsule.validation_plan_id:
        raise ProductionGovernedResumeFactoryError(
            "validation plan identity does not match restart capsule"
        )
    if payload.get("plan_id") != capsule.validation_plan_id:
        raise ProductionGovernedResumeFactoryError(
            "validation bundle plan identity does not match restart capsule"
        )
    if payload.get("invocation_id") != descriptor.invocation_id:
        raise ProductionGovernedResumeFactoryError(
            "validation bundle invocation does not match descriptor"
        )

    identity = _repository_identity(payload.get("repository_identity"))
    expected_repository = f"{identity.owner}/{identity.repository}"
    if expected_repository.casefold() != descriptor.repository.casefold():
        raise ProductionGovernedResumeFactoryError(
            "validation bundle repository does not match descriptor"
        )
    if payload.get("source_head_sha") != descriptor.source_sha:
        raise ProductionGovernedResumeFactoryError(
            "validation bundle source SHA does not match descriptor"
        )

    evidence_type = _repository_evidence_type(payload.get("repository_evidence_type"))
    governed_projection = GovernedProjectionEvidenceResult(
        status="accepted",
        schema_version=GOVERNED_PROJECTION_EVIDENCE_SCHEMA_VERSION,
        projection_id=_required_text(payload, "projection_id"),
        proposal_id=_required_text(payload, "proposal_id"),
        approval_id=_required_text(payload, "approval_id"),
        repository_identity=identity,
        base_branch=_required_text(payload, "base_branch"),
        base_sha=_required_text(payload, "base_sha"),
        head_sha=_required_text(payload, "source_head_sha"),
        evaluated_sha=_required_text(payload, "base_sha"),
        tested_sha=_required_text(payload, "tested_sha"),
        repository_evidence_type=evidence_type,
        repository_state_evidence_id=_required_text(
            payload, "repository_state_evidence_id"
        ),
        implementation_contract_fingerprint=_required_text(
            payload, "implementation_contract_fingerprint"
        ),
        reason_codes=(),
        details=(),
    )
    command_results = _supplied_command_results(payload)
    expectations = dict(
        expected_repository=identity,
        expected_pull_request=payload.get("pull_request"),
        expected_base_branch=payload.get("base_branch"),
        expected_base_sha=payload.get("base_sha"),
        expected_source_head_sha=payload.get("source_head_sha"),
        expected_tested_sha=payload.get("tested_sha"),
        expected_repository_evidence_type=evidence_type,
        expected_projection_id=payload.get("projection_id"),
        expected_proposal_id=payload.get("proposal_id"),
        expected_approval_id=payload.get("approval_id"),
        expected_repository_state_evidence_id=payload.get(
            "repository_state_evidence_id"
        ),
        expected_implementation_contract_fingerprint=payload.get(
            "implementation_contract_fingerprint"
        ),
        expected_selector_version=plan.selector_version,
        expected_profile=plan.profile,
        expected_command_set_digest=plan.command_set_digest,
        expected_plan_id=capsule.validation_plan_id,
        runner_id=payload.get("runner_id"),
        invocation_id=descriptor.invocation_id,
        started_at=payload.get("started_at"),
        completed_at=payload.get("completed_at"),
    )
    advisory = evaluate_advisory_pre_pr_evidence(
        governed_projection,
        plan,
        command_results,
        current_base_sha=payload.get("base_sha"),
        current_source_head_sha=descriptor.source_sha,
        expected_bundle_id=capsule.validation_bundle_id,
        **expectations,
    )
    if advisory_evidence_result_id(advisory) != capsule.advisory_result_id:
        raise ProductionGovernedResumeFactoryError(
            "rebuilt advisory identity does not match restart capsule"
        )
    return advisory


def _validation_plan(payload: Mapping[str, object]) -> ValidationPlan:
    raw = payload.get("validation_plan")
    if type(raw) is not dict:
        raise ProductionGovernedResumeFactoryError(
            "restart capsule validation plan is malformed"
        )
    expected = {
        "schema_name",
        "schema_version",
        "selector_version",
        "repository",
        "pull_request",
        "base_sha",
        "head_sha",
        "profile",
        "commands",
        "command_set_digest",
        "reason_codes",
        "remote_build_required",
        "execution_authorized",
        "side_effects_performed",
    }
    if set(raw) != expected:
        raise ProductionGovernedResumeFactoryError(
            "restart capsule validation plan fields drifted"
        )
    if raw["execution_authorized"] is not False or raw["side_effects_performed"] is not False:
        raise ProductionGovernedResumeFactoryError(
            "restart capsule validation plan cannot grant authority"
        )
    commands = raw["commands"]
    reasons = raw["reason_codes"]
    if type(commands) is not list or type(reasons) is not list:
        raise ProductionGovernedResumeFactoryError(
            "restart capsule validation plan collections are malformed"
        )
    try:
        return ValidationPlan(
            selector_version=raw["selector_version"],
            repository=raw["repository"],
            pull_request=raw["pull_request"],
            base_sha=raw["base_sha"],
            head_sha=raw["head_sha"],
            profile=raw["profile"],
            commands=tuple(commands),
            command_set_digest=raw["command_set_digest"],
            reason_codes=tuple(reasons),
            remote_build_required=raw["remote_build_required"],
            execution_authorized=False,
            side_effects_performed=False,
        )
    except (TypeError, ValueError) as exc:
        raise ProductionGovernedResumeFactoryError(
            "restart capsule validation plan could not be reconstructed"
        ) from exc


def _supplied_command_results(
    payload: Mapping[str, object],
) -> tuple[SuppliedCommandResult, ...]:
    raw = payload.get("command_results")
    if type(raw) is not list:
        raise ProductionGovernedResumeFactoryError(
            "restart capsule validation command results are malformed"
        )
    results: list[SuppliedCommandResult] = []
    for item in raw:
        if type(item) is not dict:
            raise ProductionGovernedResumeFactoryError(
                "restart capsule validation command result is malformed"
            )
        try:
            results.append(
                SuppliedCommandResult(
                    plan_id=item["plan_id"],
                    invocation_id=item["invocation_id"],
                    runner_id=item["runner_id"],
                    command_ordinal=item["command_ordinal"],
                    command=item["command"],
                    source_head_sha=item["source_head_sha"],
                    tested_sha=item["tested_sha"],
                    started_at=item["started_at"],
                    completed_at=item["completed_at"],
                    status=item["status"],
                    exit_code=item["exit_code"],
                    diagnostic_summary=item["diagnostic_summary"],
                    diagnostic_truncated=item["diagnostic_truncated"],
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProductionGovernedResumeFactoryError(
                "restart capsule validation command result could not be reconstructed"
            ) from exc
    return tuple(results)


def _repository_identity(value: object) -> RepositoryIdentity:
    if type(value) is not dict:
        raise ProductionGovernedResumeFactoryError(
            "validation bundle repository identity is malformed"
        )
    expected = {
        "host",
        "owner",
        "repository",
        "repository_id",
        "is_fork",
        "upstream_owner",
        "upstream_repository",
        "upstream_repository_id",
        "default_branch",
    }
    if set(value) != expected:
        raise ProductionGovernedResumeFactoryError(
            "validation bundle repository identity fields drifted"
        )
    try:
        return RepositoryIdentity(**value)
    except (TypeError, ValueError) as exc:
        raise ProductionGovernedResumeFactoryError(
            "validation bundle repository identity could not be reconstructed"
        ) from exc


def _repository_evidence_type(value: object) -> RepositoryEvidenceType:
    try:
        return RepositoryEvidenceType(value)
    except (TypeError, ValueError) as exc:
        raise ProductionGovernedResumeFactoryError(
            "validation bundle repository evidence type is malformed"
        ) from exc


def _required_text(payload: Mapping[str, object], name: str) -> str:
    value = payload.get(name)
    if type(value) is not str or not value:
        raise ProductionGovernedResumeFactoryError(
            f"validation bundle {name} is malformed"
        )
    return value


def _no_cancellation_requested() -> bool:
    """The fixed host argv carries no cancellation datum; report none requested."""
    return False
