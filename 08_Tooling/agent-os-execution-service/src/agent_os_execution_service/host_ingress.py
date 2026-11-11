"""#3333 (D61) trusted-host ingress operations.

Four narrowly typed host-local operations connect existing canonical owners
without adding an internet-facing listener, a generic command runner, a
request-lookup database, or any new persistence/authority seam:

* ``freeze-pre-validation-evidence``: consume one exact existing
  candidate-provenance identity plus one genuine Codespaces dev-validation
  runner receipt (bounded stdin), bind both to the fresh canonical
  pre-validation plan through the existing fail-closed projection and
  adapter owners, build the existing typed evidence bundle, and emit its
  canonical serialized bytes on stdout. Nothing is executed and nothing is
  persisted: the receipt must already exist from the admitted
  dev-validation lane.
* ``capture-approved-candidate-custody``: consume one exact existing
  candidate-provenance identity, reacquire the genuine owner's approval
  through the existing GitHub read transport, rebuild current canonical
  candidate evidence, and append custody through the existing evidence
  owner. With no bundle bytes on stdin it still fails closed at the
  missing-producer boundary; with the frozen bundle bytes on bounded stdin
  it canonically reconstructs and identity-verifies them, derives the
  advisory identities through the existing advisory owners, builds the
  repository observation through the existing verify-repo-state runner,
  and completes the existing custody composition.
* ``originate-authorized-validation-request``: consume one exact existing
  candidate-provenance identity, one exact existing approval-custody
  capsule identity, and the frozen bundle bytes on bounded stdin; verify
  the bytes against the custody-bound content identity, reacquire the
  live structured execution authorization through the existing source
  owner, and emit one canonical serialized v1.1 lifecycle request on
  stdout. No dispatch, no execution, no persistence.
* ``run-authorized-validation``: consume one exact canonical v1.1 lifecycle
  request from bounded stdin, verify its content identity against the
  expected identity, and delegate once through the existing production
  caller, which alone reacquires CURRENT execution authorization.

No operation grants approval, execution, publication, merge, lease,
worktree, Scheduler dispatch, GitHub write, retry, or Gate 2 authority.
Unknown arguments, malformed identities, wrong schemas, stale or missing
evidence, and unavailable canonical producers all fail closed with finite
blocked results: owner (candidate-provenance-unavailable/-malformed),
bootstrap (host-configuration-unavailable/-malformed), transport
(host-transport-unavailable, approval-reacquisition-unavailable), and
fresh-pre-validation (fresh-pre-validation-unavailable,
approval-projection-not-complete) failures are each reported distinctly.
Test-only seams (injected configuration/transport/verifier) stay out of the
installed CLI entrypoints, which bind only the static host configuration
and environment.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Sequence

from scripts.agent_os_candidate_packet.execution_packet_stage import (
    ExecutionPacketDisposition,
    prepare_execution_packet,
)
from scripts.agent_os_candidate_packet.pre_validation_stage import (
    PreValidationCandidateInputs,
)
from scripts.agent_os_candidate_packet.validation_stage import CandidateRuntimeInputs
from scripts.agent_os_candidate_packet_live_input.issue_reader import LiveIssueReader
from scripts.agent_os_candidate_packet_live_input.repository_observation import (
    build_repository_observation_from_verifier_stdout,
)
from scripts.agent_os_candidate_packet_live_input.repository_reader import (
    LiveRepositoryEvidenceReader,
)
from scripts.agent_os_execution_capabilities.approved_projection import (
    GOVERNED_PROJECTION_EVIDENCE_SCHEMA_VERSION,
    GovernedProjectionEvidenceResult,
)
from scripts.agent_os_execution_capabilities.dependencies import (
    DependencyCacheState,
    DependencyPreparationStatus,
)
from scripts.agent_os_execution_checkpoint.dependency_readiness_store import (
    DependencyReadinessIntegrityError,
    DependencyReadinessNotFound,
    append_dependency_readiness,
    load_dependency_readiness,
)
from scripts.agent_os_execution_checkpoint.store import (
    CheckpointStoreCapacityExceeded,
    CheckpointStoreIntegrityConflict,
    CheckpointStoreUnavailable,
)
from scripts.agent_os_remote_validation import (
    MAX_BUNDLE_SERIALIZED_BYTES,
    evaluate_pr_less_advisory_evidence,
    render_advisory_evidence,
)
from scripts.agent_os_remote_validation.pre_pr_evidence_bundle import (
    build_pre_pr_validation_evidence_bundle,
    pre_pr_validation_evidence_bundle_id,
    reconstruct_pre_pr_validation_evidence_bundle,
    serialize_pre_pr_validation_evidence_bundle,
)
from scripts.agent_os_remote_validation.selector import (
    deserialize_pre_pr_validation_plan,
    pre_pr_validation_plan_id,
)
from workflow_scheduler.execution.dependency_preparation import (
    DependencyCommandObservation,
    DependencyPreparationObservation,
    execute_dependency_preparation,
)
from workflow_scheduler.governance.dev_validation import build_dev_validation_request
from workflow_scheduler.governance.first_run_validation_observation import (
    CODESPACES_RUNNER_ID,
    FirstRunValidationObservationError,
    observed_command_from_codespaces_evidence,
    resolve_fixed_first_run_validation_id,
)
from workflow_scheduler.governance.pre_pr_dev_validation_evidence import (
    supplied_command_results_from_dev_validation,
)

from .authorized_validation import (
    _MAX_VNEXT_SERIALIZED_BYTES,
    AUTHORIZED_VALIDATION_VNEXT_SCHEMA_VERSION,
    AuthorizedValidationLifecyclePolicy,
    build_authorized_validation_lifecycle_request,
    reconstruct_authorized_validation_lifecycle_request,
    serialize_authorized_validation_lifecycle_request,
)
from .candidate_environment_provenance import (
    derive_initial_required_environment_spec,
)
from workflow_scheduler.governance.dev_validation_profiles import (
    canonical_profile_id,
)
from .candidate_approval_provenance import (
    CandidateApprovalProvenanceEvidence,
    load_candidate_approval_provenance,
)
from .execution_authorization_source import (
    ExecutionAuthorizationSourceStatus,
    reacquire_execution_authorization,
)
from .fresh_pre_validation import FreshPreValidationError, prepare_fresh_pre_validation
from .host_github_read_transport import (
    HostGitHubTransportUnavailable,
    build_host_github_read_transport_from_environment,
)
from .human_approval_custody import (
    HumanApprovalCustodyError,
    produce_human_approval_custody,
    reacquire_human_approval_decision,
)
from .models import parse_canonical_utc
from .pre_publication_evidence_store import (
    load_approval_custody_pre_publication_evidence,
)
from .production_authorized_validation_caller import (
    ProductionAuthorizedValidationCallerError,
    run_production_authorized_validation,
)
from .production_host_bootstrap import (
    ProductionHostBootstrapError,
    ProductionHostConfiguration,
    VerifierInvocation,
    build_subprocess_verifier_runner,
    canonical_evaluated_at,
    load_production_host_configuration,
)

_PROVENANCE_ID_RE = re.compile(r"pre-publication-evidence:[0-9a-f]{64}")
_REQUEST_ID_RE = re.compile(r"authorized-validation-request:[0-9a-f]{64}")

PRODUCER_OPERATION_CAPTURE_CUSTODY = "capture-approved-candidate-custody-v1"
PRODUCER_OPERATION_RUN_VALIDATION = "run-authorized-validation-v1"
PRODUCER_OPERATION_FREEZE_PRE_VALIDATION = "freeze-pre-validation-evidence-v1"
PRODUCER_OPERATION_ORIGINATE_REQUEST = "originate-authorized-validation-request-v1"

PRE_PR_DEVELOPER_LOOP_OPERATION = "pre-pr-developer-loop"


class HostIngressError(RuntimeError):
    """Finite blocked result for one D61 host-ingress operation."""


def _load_provenance(
    config: ProductionHostConfiguration, candidate_provenance_id: str
) -> CandidateApprovalProvenanceEvidence:
    try:
        provenance = load_candidate_approval_provenance(
            config.checkpoint_store_root, candidate_provenance_id
        )
    except LookupError as exc:
        raise HostIngressError("candidate-provenance-unavailable") from exc
    except CheckpointStoreUnavailable as exc:
        raise HostIngressError("candidate-provenance-unavailable") from exc
    except (CheckpointStoreIntegrityConflict, TypeError, ValueError) as exc:
        raise HostIngressError("candidate-provenance-malformed") from exc
    if type(provenance) is not CandidateApprovalProvenanceEvidence:
        raise HostIngressError("candidate-provenance-malformed")
    return provenance


def _host_context(
    candidate_provenance_id: str,
    configuration: ProductionHostConfiguration | None,
    transport: object | None,
    evaluated_at: str | None,
):
    """Resolve the exact host context shared by every ingress operation."""
    if type(candidate_provenance_id) is not str or _PROVENANCE_ID_RE.fullmatch(
        candidate_provenance_id
    ) is None:
        raise HostIngressError("candidate-provenance-id-malformed")
    if configuration is None:
        try:
            config = load_production_host_configuration()
        except ProductionHostBootstrapError as exc:
            raise HostIngressError("host-configuration-unavailable") from exc
    else:
        config = configuration
    if type(config) is not ProductionHostConfiguration:
        raise HostIngressError("host-configuration-malformed")
    now = evaluated_at or canonical_evaluated_at()
    parse_canonical_utc(now)
    provenance = _load_provenance(config, candidate_provenance_id)
    if transport is None:
        try:
            github = build_host_github_read_transport_from_environment()
        except HostGitHubTransportUnavailable as exc:
            raise HostIngressError("host-transport-unavailable") from exc
    else:
        github = transport
    return config, now, provenance, github


def _fresh_stage_material(config, provenance, github, now):
    """Reacquire the owner decision and rebuild the current plan, fail-closed."""
    packet = provenance.approval_ready_packet
    try:
        decision = reacquire_human_approval_decision(
            transport=github,
            repository=packet.repository,
            issue_number=packet.issue_number,
            candidate_provenance_id=provenance.evidence_id,
        )
    except HumanApprovalCustodyError as exc:
        raise HostIngressError("approval-reacquisition-unavailable") from exc
    proposal_stage = provenance.repository_proposal_stage_result
    if proposal_stage is None or proposal_stage.repository_state_evidence is None:
        raise HostIngressError("candidate-provenance-vnext-required")
    repository_state = proposal_stage.repository_state_evidence
    candidate_inputs = PreValidationCandidateInputs(
        repository_identity=repository_state.repository_identity,
        repository_state_evidence=repository_state,
        issue_number=packet.issue_number,
        invocation_id=packet.invocation_id,
        candidate_branch=packet.candidate_ref,
        candidate_sha=packet.candidate_sha,
        tested_sha=packet.tested_sha,
        evaluator_sha=packet.evaluator_sha,
        expected_changed_paths=tuple(packet.expected_changed_paths),
        required_tests=tuple(packet.required_tests),
    )
    try:
        fresh = prepare_fresh_pre_validation(
            provenance=provenance,
            approval_decision=decision.approval_decision,
            candidate_inputs=candidate_inputs,
            evaluated_at=now,
            projected_at=now,
        )
    except FreshPreValidationError as exc:
        raise HostIngressError("fresh-pre-validation-unavailable") from exc
    if fresh.approval_stage_result.projection is None:
        raise HostIngressError("approval-projection-not-complete")
    return decision, fresh


def _fresh_plan(provenance, fresh):
    """Return the fresh canonical pre-validation plan or fail closed."""
    validation = fresh.validation_stage_result
    if validation.validation_plan is None or validation.validation_plan_id is None:
        raise HostIngressError("pre-validation-plan-unavailable")
    return validation.validation_plan, validation.validation_plan_id


def _governed_projection(provenance, fresh) -> GovernedProjectionEvidenceResult:
    """Project the fresh verified stage material into the governed record.

    Every value comes from material already verified by the fresh
    pre-validation owner (proposal-stage identity bindings and the exact
    approval projection); the subject's embedded projection, approval, and
    contract identities must be exactly the fresh projection's own. The
    bundle builder and the advisory evaluator each re-verify this record
    against independently derived expectations, so a drifted field fails
    closed at the next owner boundary.
    """
    proposal_stage = provenance.repository_proposal_stage_result
    repository_state = proposal_stage.repository_state_evidence
    proposal = proposal_stage.proposal
    subject = fresh.validation_stage_result.subject
    projection = fresh.approval_stage_result.projection
    if proposal is None or subject is None or projection is None:
        raise HostIngressError("pre-validation-plan-unavailable")
    if (
        subject.projection_id != projection.projection_id
        or subject.approval_id != projection.approval_id
        or subject.implementation_contract_fingerprint
        != getattr(projection, "implementation_contract_fingerprint", None)
    ):
        raise HostIngressError("governed-projection-not-accepted")
    return GovernedProjectionEvidenceResult(
        status="accepted",
        schema_version=GOVERNED_PROJECTION_EVIDENCE_SCHEMA_VERSION,
        projection_id=subject.projection_id,
        proposal_id=proposal.proposal_id,
        approval_id=subject.approval_id,
        repository_identity=repository_state.repository_identity,
        base_branch=subject.base_branch,
        base_sha=subject.base_sha,
        head_sha=subject.expected_source_sha,
        evaluated_sha=subject.base_sha,
        tested_sha=subject.tested_sha,
        repository_evidence_type=repository_state.evidence_type,
        repository_state_evidence_id=repository_state.evidence_id,
        implementation_contract_fingerprint=subject.implementation_contract_fingerprint,
        reason_codes=(),
        details=(),
    )


def _derive_frozen_pre_validation_advisory(provenance, fresh, payload):
    """Reconstruct frozen bundle bytes and derive advisory ids, fail-closed.

    The bytes are never trusted: canonical reconstruction verifies the typed
    bundle and its content identity, the embedded plan must be exactly the
    fresh canonical plan, and every subject identity must match the exact
    candidate. Advisory identities are then derived through the existing
    advisory owners; nothing is executed and nothing is synthesized.
    """
    packet = provenance.approval_ready_packet
    try:
        bundle = reconstruct_pre_pr_validation_evidence_bundle(payload)
    except (TypeError, ValueError) as exc:
        raise HostIngressError("pre-validation-bundle-malformed") from exc
    try:
        plan = deserialize_pre_pr_validation_plan(
            payload.get("validation_plan") if type(payload) is dict else None
        )
    except (TypeError, ValueError) as exc:
        raise HostIngressError("pre-validation-bundle-malformed") from exc
    fresh_plan, fresh_plan_id = _fresh_plan(provenance, fresh)
    if pre_pr_validation_plan_id(plan) != fresh_plan_id or plan != fresh_plan:
        raise HostIngressError("validation-plan-identity-mismatch")
    governed = _governed_projection(provenance, fresh)
    identity = governed.repository_identity
    if (
        f"{identity.owner}/{identity.repository}".casefold()
        != packet.repository.casefold()
        or payload.get("source_head_sha") != packet.candidate_sha
        or payload.get("tested_sha") != packet.tested_sha
        or payload.get("invocation_id") != packet.invocation_id
        or payload.get("base_branch") != packet.base_branch
        or payload.get("base_sha") != packet.base_sha
        or payload.get("projection_id") != governed.projection_id
        or payload.get("runner_id") != CODESPACES_RUNNER_ID
    ):
        raise HostIngressError("validation-bundle-subject-mismatch")
    try:
        advisory = evaluate_pr_less_advisory_evidence(
            payload,
            expected_bundle_id=bundle.bundle_id,
            current_base_sha=packet.base_sha,
            current_source_head_sha=packet.candidate_sha,
            invocation_id=packet.invocation_id,
        )
        render = render_advisory_evidence(advisory)
    except (TypeError, ValueError) as exc:
        raise HostIngressError("advisory-evidence-unavailable") from exc
    if advisory.status != "passed":
        raise HostIngressError("advisory-evidence-not-passed")
    return bundle, plan, advisory, render


def _tested_content_spec(config, tested_sha, required_tests, content_root=None):
    """Derive the canonical environment spec from the tested SHA's own content.

    Production reads the tested commit through an ephemeral detached worktree
    of the configured clone; the host checkout's incidental state is never
    the source of dependency policy. Fails closed when the tested content is
    unavailable. ``content_root`` is the test seam (the same pattern as the
    module's injected transport and verifier): tests derive from a genuine
    on-disk tree instead of materializing a worktree.
    """
    if content_root is not None:
        try:
            return derive_initial_required_environment_spec(
                content_root, required_tests=required_tests
            )
        except (TypeError, ValueError) as exc:
            raise HostIngressError(
                "required-environment-spec-unavailable"
            ) from exc
    root = Path(config.repository_root)
    temporary = Path(tempfile.mkdtemp(prefix="agent-os-tested-content-"))
    worktree = temporary / "repo"
    added = None
    try:
        try:
            added = subprocess.run(
                (
                    "git",
                    "-C",
                    str(root),
                    "worktree",
                    "add",
                    "--detach",
                    str(worktree),
                    tested_sha,
                ),
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            head = (
                subprocess.run(
                    ("git", "-C", str(worktree), "rev-parse", "HEAD"),
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if added.returncode == 0
                else None
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise HostIngressError("tested-content-unavailable") from exc
        if (
            head is None
            or head.returncode != 0
            or head.stdout.strip() != tested_sha
        ):
            raise HostIngressError("tested-content-unavailable")
        try:
            return derive_initial_required_environment_spec(
                worktree, required_tests=required_tests
            )
        except (TypeError, ValueError) as exc:
            raise HostIngressError(
                "required-environment-spec-unavailable"
            ) from exc
    finally:
        cleanup_failed = False
        if added is not None and added.returncode == 0:
            try:
                removed = subprocess.run(
                    (
                        "git",
                        "-C",
                        str(root),
                        "worktree",
                        "remove",
                        "--force",
                        str(worktree),
                    ),
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                cleanup_failed = removed.returncode != 0
            except (OSError, subprocess.TimeoutExpired):
                cleanup_failed = True
        shutil.rmtree(temporary, ignore_errors=True)
        if cleanup_failed or temporary.exists():
            raise HostIngressError("tested-content-cleanup-failed")


def _custody_required_environment_spec(config, provenance, fresh, *, content_root=None):
    """Derive the one canonical required-environment spec for this candidate.

    The fixed validation command identity is catalog-owned: the fresh plan's
    exact argv resolves to the existing dev-validation profile id through the
    same owner the freeze step uses, so the spec carries the catalog id while
    the packet retains the exact argv anchor. The spec derives from the
    tested SHA's own content, never the incidental host checkout state.
    Fails closed when the plan is not a fixed profile or the tested content
    is unavailable.
    """
    plan, _plan_id = _fresh_plan(provenance, fresh)
    try:
        validation_id = canonical_profile_id(
            resolve_fixed_first_run_validation_id(plan)
        )
    except (FirstRunValidationObservationError, ValueError) as exc:
        raise HostIngressError("fixed-validation-profile-unavailable") from exc
    return _tested_content_spec(
        config,
        provenance.approval_ready_packet.tested_sha,
        (validation_id,),
        content_root,
    )


def _custody_runtime_inputs(
    config, provenance, decision, now, bundle, advisory, render, *,
    required_environment_spec=None,
):
    """Assemble runtime inputs from genuine durable identities only.

    ``created_at`` binds the owner approval's durable decision timestamp and
    ``expires_at`` binds the candidate packet's own freshness boundary, so
    the execution request fingerprint is reproducible when the canonical
    request originator later recomposes the same stage. Execution
    authorization is genuinely absent at custody time: the structured owner
    authorization comment binds this composition's fingerprint and therefore
    can only follow it.
    """
    packet = provenance.approval_ready_packet
    proposal_stage = provenance.repository_proposal_stage_result
    repository_state = proposal_stage.repository_state_evidence
    return CandidateRuntimeInputs(
        repository_identity=repository_state.repository_identity,
        repository_state_evidence=repository_state,
        issue_number=packet.issue_number,
        invocation_id=packet.invocation_id,
        candidate_branch=packet.candidate_ref,
        candidate_sha=packet.candidate_sha,
        tested_sha=packet.tested_sha,
        evaluator_sha=packet.evaluator_sha,
        expected_changed_paths=tuple(packet.expected_changed_paths),
        required_tests=tuple(packet.required_tests),
        created_at=decision.decision_at,
        expires_at=packet.freshness_boundary,
        evaluated_at=now,
        repository_root=str(config.repository_root),
        workspace_parent=str(config.workspace_parent),
        validation_bundle_id=bundle.bundle_id,
        advisory_result_id=advisory.result_id,
        advisory_render_id=render.render_id,
        required_environment_spec=required_environment_spec,
        execution_authorization_present=False,
    )


def _candidate_repository_observation(config, provenance, fresh, run_verifier):
    """Reconstruct the approval-time observation after fresh full-subject verification.

    The strict post-approval identity owner compares the repository-evidence
    identity carried by the approved packet, and that identity covers every
    field of the approval-time observation, including its producer and
    ``observed_at``. A fresh observation stamped at custody time can therefore
    never match it. Custody's duty is instead twofold: reconstruct the
    approval-time observation field-for-field from durable provenance (whose
    evidence id is self-verifying over exactly these fields), and re-run the
    canonical verifier now to prove the full subject it observes - base and
    head refs and SHAs, the observed SHA, requested candidate and tested SHA,
    contract fingerprint, and worktree state - still equals the durable
    approval evidence exactly. Any drift fails closed; staleness is governed
    separately by the compiler's freshness checks against the durable
    freshness boundary.
    """
    packet = provenance.approval_ready_packet
    verifier = run_verifier or build_subprocess_verifier_runner()
    try:
        stdout = verifier(
            VerifierInvocation(
                repository_root=config.repository_root,
                branch=packet.candidate_ref,
                base_branch=packet.base_branch,
            )
        )
    except (ProductionHostBootstrapError, TypeError, ValueError, RuntimeError, OSError) as exc:
        raise HostIngressError("repository-verification-unavailable") from exc
    if type(stdout) is not str:
        raise HostIngressError("repository-verifier-malformed")
    proposal_stage = provenance.repository_proposal_stage_result
    durable = proposal_stage.repository_state_evidence
    identity = durable.repository_identity
    if identity.host != config.repository_host:
        raise HostIngressError("repository-host-mismatch")
    subject = fresh.validation_stage_result.subject
    if subject is None:
        raise HostIngressError("pre-validation-plan-unavailable")
    try:
        observation = build_repository_observation_from_verifier_stdout(
            stdout,
            producer_adapter=durable.producer_adapter,
            producer_adapter_version=durable.producer_adapter_version,
            correlation_id=durable.correlation_id,
            repository_identity=identity,
            contract_fingerprint=durable.contract_fingerprint,
            observed_at=durable.observed_at,
            freshness_boundary=durable.freshness_boundary,
            evidence_type=durable.evidence_type,
            requested_ref=durable.requested_ref,
            requested_sha=durable.requested_sha,
            tested_sha=durable.tested_sha,
            pushed_sha=durable.pushed_sha,
            proposed_pr_sha=durable.proposed_pr_sha,
            synthetic_merge_sha=durable.synthetic_merge_sha,
            external_build_sha=durable.external_build_sha,
            worktree_reason_codes=durable.worktree_reason_codes,
        )
    except (TypeError, ValueError) as exc:
        raise HostIngressError("repository-observation-malformed") from exc
    if (
        observation.base_ref != durable.base_ref
        or observation.base_sha != durable.base_sha
        or observation.head_ref != durable.head_ref
        or observation.head_sha != durable.head_sha
        or observation.observed_sha != durable.observed_sha
        or observation.worktree_state != durable.worktree_state
        or durable.requested_ref != packet.candidate_ref
        or durable.requested_sha != packet.candidate_sha
        or durable.tested_sha != packet.tested_sha
        or durable.contract_fingerprint
        != subject.implementation_contract_fingerprint
    ):
        raise HostIngressError("candidate-repository-subject-drift")
    return observation


def capture_approved_candidate_custody(
    candidate_provenance_id: str,
    *,
    pre_validation_bundle_payload: object | None = None,
    dependency_readiness_evidence_id: str | None = None,
    configuration: ProductionHostConfiguration | None = None,
    transport: object | None = None,
    run_verifier=None,
    evaluated_at: str | None = None,
    content_root: object | None = None,
) -> str:
    """Compose existing owners for one approved-candidate custody append.

    Every input is reacquired from its existing canonical owner; nothing is
    accepted from the caller beyond the exact provenance identity and the
    frozen pre-validation bundle bytes, which are canonically reconstructed
    and identity-verified before use. Without those bytes this still fails
    closed at the exact missing-producer boundary; it never synthesizes
    validation evidence, authorizes execution, or runs a hidden
    pre-validation.
    """
    config, now, provenance, github = _host_context(
        candidate_provenance_id, configuration, transport, evaluated_at
    )
    decision, fresh = _fresh_stage_material(config, provenance, github, now)
    if pre_validation_bundle_payload is None:
        # #3333 Contract A boundary: CandidateRuntimeInputs.validation_bundle_id,
        # advisory_result_id and advisory_render_id are prior immutable evidence
        # references whose only genuine source is frozen post-run pre-validation
        # evidence. Without the frozen bundle bytes (see
        # freeze_pre_validation_evidence), custody cannot truthfully complete.
        raise HostIngressError(
            "pre-validation-evidence-references-unavailable:"
            "no admitted producer of frozen pre-validation evidence"
        )
    bundle, _plan, advisory, render = _derive_frozen_pre_validation_advisory(
        provenance, fresh, pre_validation_bundle_payload
    )
    packet = provenance.approval_ready_packet
    if dependency_readiness_evidence_id is None:
        # #3333 Contract A boundary: RESOLVED_CLEAR dependency evidence
        # requires genuine DependencyReadinessEvidence produced by an
        # admitted canonical preparation run and persisted through the
        # existing store owner. Without its identity this fails closed; it
        # never synthesizes readiness.
        raise HostIngressError("dependency-readiness-evidence-unavailable")
    spec = _custody_required_environment_spec(
        config, provenance, fresh, content_root=content_root
    )
    try:
        readiness = load_dependency_readiness(
            config.checkpoint_store_root, dependency_readiness_evidence_id
        )
    except (DependencyReadinessNotFound, CheckpointStoreUnavailable) as exc:
        raise HostIngressError("dependency-readiness-unavailable") from exc
    except (
        DependencyReadinessIntegrityError,
        CheckpointStoreIntegrityConflict,
        TypeError,
        ValueError,
    ) as exc:
        raise HostIngressError("dependency-readiness-malformed") from exc
    if readiness.source_sha != packet.tested_sha:
        raise HostIngressError("dependency-readiness-subject-mismatch")
    if readiness.required_environment_id != spec.required_environment_id:
        raise HostIngressError("dependency-readiness-environment-mismatch")
    if not readiness.is_current(now):
        raise HostIngressError("dependency-readiness-not-current")
    observation = _candidate_repository_observation(
        config, provenance, fresh, run_verifier
    )
    runtime_inputs = _custody_runtime_inputs(
        config,
        provenance,
        decision,
        now,
        bundle,
        advisory,
        render,
        required_environment_spec=spec,
    )
    try:
        return produce_human_approval_custody(
            candidate_provenance_id=provenance.evidence_id,
            transport=github,
            issue_reader=LiveIssueReader(github),
            repository_reader=LiveRepositoryEvidenceReader(
                repository=packet.repository,
                issue_number=packet.issue_number,
                validation_result=advisory,
                dependency_readiness=readiness,
                required_environment_spec=spec,
                evaluated_at=now,
                expected_validation_plan_id=fresh.validation_stage_result.validation_plan_id,
            ),
            repository_observation=observation,
            candidate_runtime_inputs=runtime_inputs,
            observed_at=now,
            configuration=config,
        )
    except HumanApprovalCustodyError as exc:
        raise HostIngressError("approval-custody-unavailable") from exc


def freeze_pre_validation_evidence(
    candidate_provenance_id: str,
    observed_evidence: object,
    *,
    configuration: ProductionHostConfiguration | None = None,
    transport: object | None = None,
    evaluated_at: str | None = None,
) -> str:
    """Freeze one genuine dev-validation receipt into bundle bytes on stdout.

    ``observed_evidence`` must be the already-admitted Codespaces
    dev-validation lane's recorded runner evidence for this exact candidate;
    this operation executes nothing. The receipt is bound fail-closed to the
    fresh canonical plan (repository, issue, tested SHA, fixed profile, and
    the canonically derived lane request identity), converted through the
    existing supplied-results adapter, and frozen through the existing typed
    bundle owner. The serialized bytes are returned for the host operator;
    nothing is persisted and no authority is granted or implied.
    """
    config, now, provenance, github = _host_context(
        candidate_provenance_id, configuration, transport, evaluated_at
    )
    _decision, fresh = _fresh_stage_material(config, provenance, github, now)
    plan, _plan_id = _fresh_plan(provenance, fresh)
    subject = plan.subject
    try:
        validation_id = resolve_fixed_first_run_validation_id(plan)
    except FirstRunValidationObservationError as exc:
        raise HostIngressError("fixed-validation-profile-unavailable") from exc
    try:
        lane_request = build_dev_validation_request(
            repository=subject.repository,
            issue_number=subject.issue_number,
            branch=subject.branch,
            source_sha=subject.tested_sha,
            validation_id=validation_id,
        )
    except (TypeError, ValueError) as exc:
        raise HostIngressError("dev-validation-request-rejected") from exc
    try:
        observed = observed_command_from_codespaces_evidence(
            observed_evidence,
            expected_repository=subject.repository,
            expected_issue_number=subject.issue_number,
            expected_sha=subject.tested_sha,
            expected_profile_id=lane_request.profile_id,
            expected_request_id=lane_request.request_id,
        )
    except (FirstRunValidationObservationError, ValueError) as exc:
        raise HostIngressError("dev-validation-observation-rejected") from exc
    try:
        results = supplied_command_results_from_dev_validation(plan, (observed,))
    except (TypeError, ValueError) as exc:
        raise HostIngressError("dev-validation-receipt-rejected") from exc
    governed = _governed_projection(provenance, fresh)
    proposal_stage = provenance.repository_proposal_stage_result
    repository_state = proposal_stage.repository_state_evidence
    try:
        bundle = build_pre_pr_validation_evidence_bundle(
            governed,
            plan,
            results,
            expected_repository=repository_state.repository_identity,
            expected_repository_evidence_type=repository_state.evidence_type,
            expected_proposal_id=proposal_stage.proposal.proposal_id,
            expected_repository_state_evidence_id=repository_state.evidence_id,
            runner_id=CODESPACES_RUNNER_ID,
            started_at=observed.started_at,
            completed_at=observed.completed_at,
        )
        serialized = serialize_pre_pr_validation_evidence_bundle(bundle, plan)
        reconstructed = reconstruct_pre_pr_validation_evidence_bundle(serialized)
        if pre_pr_validation_evidence_bundle_id(reconstructed, plan) != bundle.bundle_id:
            raise HostIngressError("evidence-bundle-identity-mismatch")
    except HostIngressError:
        raise
    except (TypeError, ValueError) as exc:
        raise HostIngressError("evidence-bundle-construction-failed") from exc
    return json.dumps(serialized, sort_keys=True, separators=(",", ":"))


_RUNTIME_REQUIREMENT_RE = re.compile(r"^>=(\d+)\.(\d+)$", re.ASCII)


def _runtime_version_compatible(runtime_version: str, requirement: str) -> bool:
    """Recompute runtime compatibility from the measured version text.

    The lane's spec declares exactly one lower-bound form (``>=3.11``); any
    other expression or unparseable measurement fails closed.
    """
    requirement_match = _RUNTIME_REQUIREMENT_RE.fullmatch(requirement)
    version_match = re.fullmatch(r"(\d+)\.(\d+)(?:\.\d+)?", runtime_version)
    if requirement_match is None or version_match is None:
        return False
    required = (int(requirement_match.group(1)), int(requirement_match.group(2)))
    actual = (int(version_match.group(1)), int(version_match.group(2)))
    return actual >= required


def _measurement_text(preparation: dict, name: str) -> str:
    value = preparation.get(name)
    if type(value) is not str or not value:
        raise HostIngressError("dependency-readiness-malformed")
    return value


class _RemoteAttemptReplay:
    """Replay one remotely measured preparation attempt; executes nothing.

    The fixed remote script reports the exact argv it executed; the canonical
    plan argv is recomputed here from the host-derived spec, and any
    divergence beyond the interpreter placeholder (argv[0]) fails closed.
    """

    def __init__(self, preparation: dict) -> None:
        self._preparation = preparation
        self._calls = 0

    def run(
        self, argv: tuple[str, ...], *, workspace_identity: str
    ) -> DependencyCommandObservation:
        self._calls += 1
        remote_argv = self._preparation.get("argv")
        if self._calls > 1 or (
            type(remote_argv) is not list
            or not remote_argv
            or any(type(part) is not str for part in remote_argv)
            or tuple(remote_argv[1:]) != tuple(argv[1:])
        ):
            raise HostIngressError("dependency-preparation-argv-mismatch")
        if self._preparation.get("install_attempted") is not True:
            return DependencyCommandObservation(attempted=False, succeeded=False)
        if self._preparation.get("install_succeeded") is not True:
            reason = self._preparation.get("failure_reason_code")
            return DependencyCommandObservation(
                attempted=True,
                succeeded=False,
                failure_reason_code=(
                    reason
                    if type(reason) is str and reason
                    else "dependency.preparation-failed"
                ),
            )
        resolved = self._preparation.get("resolved_dependency_identity")
        return DependencyCommandObservation(
            attempted=True,
            succeeded=True,
            resolved_dependency_identity=(
                resolved if type(resolved) is str and resolved else None
            ),
        )


def _replay_remote_dependency_preparation(spec, preparation):
    """Reconstruct readiness from fixed-script measurements via canonical owners.

    Every measurement is type-checked; missing or partial measurements fail
    closed, never default to pass. The manifest and local-project digests are
    compared against the host-derived spec (itself derived from the tested
    SHA's own content), runtime compatibility is recomputed from the measured
    version, and planning/execution/evidence semantics come only from the
    canonical workflow-scheduler owners with a replay runner that executes
    nothing. READY can only result from a genuinely reported successful
    pinned-argv install with a resolved environment identity.
    """
    if type(preparation) is not dict:
        raise HostIngressError("dependency-readiness-record-unavailable")
    runtime_version = _measurement_text(preparation, "runtime_version")
    package_manager_version = _measurement_text(
        preparation, "package_manager_version"
    )
    projects = preparation.get("local_project_sha256")
    if type(projects) is not dict:
        raise HostIngressError("dependency-readiness-malformed")
    manifest_sha = preparation.get("manifest_sha256")
    manifest_matches = (
        type(manifest_sha) is str
        and manifest_sha == spec.dependency_manifest_identity.sha256
    )
    local_projects_match = all(
        type(projects.get(requirement.relative_path)) is str
        and projects[requirement.relative_path] == requirement.sha256
        for requirement in spec.local_project_requirements
    )
    source_identity = preparation.get("source_identity")
    observed_at = _measurement_text(preparation, "observed_at")
    expires_at = _measurement_text(preparation, "expires_at")
    try:
        observation = DependencyPreparationObservation(
            execution_surface_id=_measurement_text(
                preparation, "execution_surface_id"
            ),
            workspace_identity=_measurement_text(preparation, "workspace_identity"),
            source_sha=_measurement_text(preparation, "source_sha"),
            environment_health_evidence_id=_measurement_text(
                preparation, "environment_health_evidence_id"
            ),
            environment_health_current=True,
            runtime_version=runtime_version,
            runtime_compatible=_runtime_version_compatible(
                runtime_version, spec.runtime_requirement
            ),
            package_manager_version=package_manager_version,
            manifest_matches=manifest_matches,
            lock_matches=None,
            source_identity_matches=(
                type(source_identity) is str
                and source_identity == spec.approved_source_identity
            ),
            source_reachable=preparation.get("source_reachable") is True,
            # No prior contrary evidence; the measured bounded attempt is the
            # availability check and its failure is classified canonically.
            package_available=True,
            cache_state=DependencyCacheState.UNKNOWN,
            local_projects_match=local_projects_match,
            source_form_reason_codes=(),
            existing_ready_evidence=None,
        )
        evidence = execute_dependency_preparation(
            spec,
            observation,
            _RemoteAttemptReplay(preparation),
            evaluated_at=observed_at,
            expires_at=expires_at,
        )
    except HostIngressError:
        raise
    except (TypeError, ValueError) as exc:
        raise HostIngressError("dependency-readiness-malformed") from exc
    return evidence


def record_codespaces_dependency_readiness(
    candidate_provenance_id: str,
    observed_evidence: object,
    *,
    configuration: ProductionHostConfiguration | None = None,
    transport: object | None = None,
    evaluated_at: str | None = None,
    content_root: object | None = None,
) -> str:
    """Verify and persist readiness from one lane receipt's measurements.

    ``observed_evidence`` must be the same already-admitted Codespaces
    dev-validation lane receipt accepted by freeze_pre_validation_evidence for
    this exact candidate, carrying the raw preparation measurements the fixed
    remote script produced before the fixed validation command ran. The
    receipt is bound fail-closed to the fresh canonical plan through the same
    projector the freeze step uses; the measurements are replayed through the
    canonical planner/executor/evidence owners against the spec derived from
    the tested SHA's own content; the resulting readiness is re-bound to this
    candidate's tested subject, derived required environment, execution
    surface, and environment-health evidence, required READY and current at
    this evaluation, then appended through the existing store owner. Returns
    the readiness evidence identity for the custody capture operation. This
    operation executes no candidate code and grants no execution, merge, or
    publication authority. Its only side effect beyond the store append is
    the bounded ephemeral worktree used to read the tested content (added and
    removed with ``git worktree``; cleanup failure fails closed).
    """
    config, now, provenance, github = _host_context(
        candidate_provenance_id, configuration, transport, evaluated_at
    )
    _decision, fresh = _fresh_stage_material(config, provenance, github, now)
    plan, _plan_id = _fresh_plan(provenance, fresh)
    subject = plan.subject
    try:
        validation_id = resolve_fixed_first_run_validation_id(plan)
    except FirstRunValidationObservationError as exc:
        raise HostIngressError("fixed-validation-profile-unavailable") from exc
    try:
        lane_request = build_dev_validation_request(
            repository=subject.repository,
            issue_number=subject.issue_number,
            branch=subject.branch,
            source_sha=subject.tested_sha,
            validation_id=validation_id,
        )
    except (TypeError, ValueError) as exc:
        raise HostIngressError("dev-validation-request-rejected") from exc
    try:
        observed_command_from_codespaces_evidence(
            observed_evidence,
            expected_repository=subject.repository,
            expected_issue_number=subject.issue_number,
            expected_sha=subject.tested_sha,
            expected_profile_id=lane_request.profile_id,
            expected_request_id=lane_request.request_id,
        )
    except (FirstRunValidationObservationError, ValueError) as exc:
        raise HostIngressError("dev-validation-observation-rejected") from exc
    spec = _custody_required_environment_spec(
        config, provenance, fresh, content_root=content_root
    )
    preparation = (
        observed_evidence.get("dependency_preparation")
        if type(observed_evidence) is dict
        else None
    )
    readiness = _replay_remote_dependency_preparation(spec, preparation)
    if readiness.preparation_status is not DependencyPreparationStatus.READY:
        raise HostIngressError("dependency-readiness-not-ready")
    if readiness.source_sha != subject.tested_sha:
        raise HostIngressError("dependency-readiness-subject-mismatch")
    if readiness.required_environment_id != spec.required_environment_id:
        raise HostIngressError("dependency-readiness-environment-mismatch")
    if readiness.execution_surface_id != observed_evidence.get("execution_surface_id"):
        raise HostIngressError("dependency-readiness-surface-mismatch")
    if readiness.environment_health_evidence_id != observed_evidence.get(
        "environment_health_evidence_id"
    ):
        raise HostIngressError("dependency-readiness-health-mismatch")
    if not readiness.is_current(now):
        raise HostIngressError("dependency-readiness-not-current")
    try:
        outcome = append_dependency_readiness(
            config.checkpoint_store_root, readiness
        )
    except (
        CheckpointStoreCapacityExceeded,
        CheckpointStoreIntegrityConflict,
        CheckpointStoreUnavailable,
        OSError,
    ) as exc:
        raise HostIngressError("dependency-readiness-store-unavailable") from exc
    return outcome.evidence_id


def originate_authorized_validation_request(
    candidate_provenance_id: str,
    approval_custody_capsule_id: str,
    pre_validation_bundle_payload: object,
    *,
    configuration: ProductionHostConfiguration | None = None,
    transport: object | None = None,
    evaluated_at: str | None = None,
    content_root: object | None = None,
) -> str:
    """Originate one canonical serialized v1.1 lifecycle request on stdout.

    The frozen bundle bytes are verified against the custody-bound content
    identity recorded in the exact approval-custody capsule; the stage
    inputs are rederived through the existing fresh pre-validation owner;
    the structured execution authorization is reacquired live through the
    existing source owner and must be CURRENT for this exact candidate,
    request fingerprint, and command plan. This originator grants and
    implies no authority: no dispatch, no execution, no persistence.
    """
    if type(approval_custody_capsule_id) is not str or _PROVENANCE_ID_RE.fullmatch(
        approval_custody_capsule_id
    ) is None:
        raise HostIngressError("approval-custody-id-malformed")
    config, now, provenance, github = _host_context(
        candidate_provenance_id, configuration, transport, evaluated_at
    )
    try:
        capsule = load_approval_custody_pre_publication_evidence(
            config.checkpoint_store_root, approval_custody_capsule_id
        )
    except LookupError as exc:
        raise HostIngressError("approval-custody-unavailable") from exc
    except CheckpointStoreUnavailable as exc:
        raise HostIngressError("approval-custody-unavailable") from exc
    except (CheckpointStoreIntegrityConflict, TypeError, ValueError) as exc:
        raise HostIngressError("approval-custody-malformed") from exc
    custody_packet = capsule.candidate_packet
    packet = provenance.approval_ready_packet
    if (
        custody_packet.repository.casefold() != packet.repository.casefold()
        or custody_packet.issue_number != packet.issue_number
        or custody_packet.invocation_id != packet.invocation_id
        or custody_packet.base_sha != packet.base_sha
        or custody_packet.candidate_sha != packet.candidate_sha
        or custody_packet.tested_sha != packet.tested_sha
        or custody_packet.candidate_ref != packet.candidate_ref
    ):
        raise HostIngressError("approval-custody-lineage-mismatch")
    # The capsule durably carries the compiled candidate packet; its stage
    # identities record the custody-time execution-request, command-plan,
    # and runtime-configuration content identities. The runtime stage itself
    # is re-derived below from genuine inputs, and fingerprint equality with
    # these recorded identities binds the two by content address.
    custody_identities = dict(custody_packet.stage_identities)
    custody_request_fingerprint = custody_identities.get("execution-request")
    custody_command_plan_id = custody_identities.get("command-plan")
    custody_runtime_fingerprint = custody_identities.get("runtime-configuration")
    if (
        not custody_request_fingerprint
        or not custody_command_plan_id
        or not custody_runtime_fingerprint
    ):
        raise HostIngressError("custody-execution-packet-incomplete")
    decision, fresh = _fresh_stage_material(config, provenance, github, now)
    bundle, _plan, advisory, render = _derive_frozen_pre_validation_advisory(
        provenance, fresh, pre_validation_bundle_payload
    )
    _fresh_plan_value, fresh_plan_id = _fresh_plan(provenance, fresh)
    spec = _custody_required_environment_spec(
        config, provenance, fresh, content_root=content_root
    )
    runtime_inputs = _custody_runtime_inputs(
        config,
        provenance,
        decision,
        now,
        bundle,
        advisory,
        render,
        required_environment_spec=spec,
    )
    preauth_stage = prepare_execution_packet(fresh.approval_stage_result, runtime_inputs)
    if (
        not preauth_stage.packet_complete
        or preauth_stage.request_fingerprint is None
        or preauth_stage.command_plan_id is None
        or preauth_stage.runtime_configuration is None
    ):
        raise HostIngressError("execution-packet-incomplete")
    if (
        preauth_stage.request_fingerprint != custody_request_fingerprint
        or preauth_stage.command_plan_id != custody_command_plan_id
        or preauth_stage.runtime_configuration_fingerprint
        != custody_runtime_fingerprint
    ):
        raise HostIngressError("custody-content-identity-mismatch")
    if (
        preauth_stage.runtime_configuration.validation_plan_id != fresh_plan_id
        or preauth_stage.runtime_configuration.validation_bundle_id != bundle.bundle_id
        or preauth_stage.runtime_configuration.advisory_result_id != advisory.result_id
        or preauth_stage.runtime_configuration.advisory_render_id != render.render_id
    ):
        raise HostIngressError("custody-content-identity-mismatch")
    authorization = reacquire_execution_authorization(
        transport=github,
        repository=custody_packet.repository,
        issue_number=custody_packet.issue_number,
        expected_candidate_packet_id=custody_packet.packet_id,
        expected_invocation_id=custody_packet.invocation_id,
        expected_operation=PRE_PR_DEVELOPER_LOOP_OPERATION,
        expected_request_fingerprint=preauth_stage.request_fingerprint,
        expected_command_plan_id=preauth_stage.command_plan_id,
        expected_sha=custody_packet.candidate_sha,
        evaluated_at=now,
    )
    if (
        authorization.status is not ExecutionAuthorizationSourceStatus.CURRENT
        or authorization.evidence is None
        or authorization.authorizer_id is None
    ):
        raise HostIngressError("execution-authorization-not-current")
    execution_stage = prepare_execution_packet(
        fresh.approval_stage_result,
        replace(runtime_inputs, execution_authorization_present=True),
    )
    if (
        execution_stage.disposition is not ExecutionPacketDisposition.GO
        or not execution_stage.packet_complete
        or execution_stage.request is None
        or execution_stage.runtime_configuration is None
        or execution_stage.request_fingerprint != preauth_stage.request_fingerprint
        or execution_stage.command_plan_id != preauth_stage.command_plan_id
    ):
        raise HostIngressError("execution-packet-incomplete")
    try:
        lifecycle = build_authorized_validation_lifecycle_request(
            candidate_packet=custody_packet,
            approval_stage=fresh.approval_stage_result,
            execution_packet_stage=execution_stage,
            execution_authorization=authorization.evidence,
            authorizer_id=authorization.authorizer_id,
            authorized_candidate_packet_id=custody_packet.packet_id,
            authorized_invocation_id=custody_packet.invocation_id,
            lifecycle_policy=AuthorizedValidationLifecyclePolicy(
                expected_changed_paths=tuple(custody_packet.expected_changed_paths)
            ),
            schema_version=AUTHORIZED_VALIDATION_VNEXT_SCHEMA_VERSION,
            validation_evidence_bundle=bundle,
        )
        payload = serialize_authorized_validation_lifecycle_request(lifecycle)
        reconstructed = reconstruct_authorized_validation_lifecycle_request(payload)
        if reconstructed.request_id != lifecycle.request_id:
            raise HostIngressError("authorized-request-identity-mismatch")
    except HostIngressError:
        raise
    except (TypeError, ValueError) as exc:
        raise HostIngressError("authorized-request-construction-failed") from exc
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def run_authorized_validation(
    expected_request_id: str,
    payload: object,
    *,
    configuration: ProductionHostConfiguration | None = None,
    transport: object | None = None,
    run_verifier=None,
    evaluated_at: str | None = None,
):
    """Verify one canonical v1.1 request identity and delegate once.

    The payload is typed canonical request transport, not arbitrary JSON
    approval: none of its asserted authority is trusted without canonical
    reconstruction, content-identity verification, and the production
    caller's own CURRENT authority reacquisition.
    """
    if type(expected_request_id) is not str or _REQUEST_ID_RE.fullmatch(
        expected_request_id
    ) is None:
        raise HostIngressError("expected-request-id-malformed")
    try:
        request = reconstruct_authorized_validation_lifecycle_request(payload)
    except (TypeError, ValueError) as exc:
        raise HostIngressError("authorized-validation-request-malformed") from exc
    if request.schema_version != AUTHORIZED_VALIDATION_VNEXT_SCHEMA_VERSION:
        raise HostIngressError("authorized-validation-v1.1-required")
    if request.request_id != expected_request_id:
        raise HostIngressError("authorized-validation-request-identity-mismatch")
    return run_production_authorized_validation(
        payload,
        cancelled=lambda checkpoint: False,
        configuration=configuration,
        evaluated_at=evaluated_at,
        transport=transport,
        run_verifier=run_verifier,
    )


def _read_bounded_stdin(oversize_reason: str, malformed_reason: str):
    """Read one bounded JSON payload from stdin; None when stdin is empty."""
    data = sys.stdin.buffer.read(MAX_BUNDLE_SERIALIZED_BYTES + 1)
    if len(data) > MAX_BUNDLE_SERIALIZED_BYTES:
        print(f"blocked:{oversize_reason}", file=sys.stderr)
        return None, 1
    if not data.strip():
        return None, 0
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        print(f"blocked:{malformed_reason}", file=sys.stderr)
        return None, 1
    return payload, 0


def _capture_custody_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-os-host-capture-custody")
    parser.add_argument("--candidate-provenance-id", required=True)
    parser.add_argument("--dependency-readiness-evidence-id", required=True)
    return parser


def main_capture_custody(argv: Sequence[str] | None = None) -> int:
    args = _capture_custody_parser().parse_args(argv)
    if type(args.candidate_provenance_id) is not str or _PROVENANCE_ID_RE.fullmatch(
        args.candidate_provenance_id
    ) is None:
        print("blocked:candidate-provenance-id-malformed", file=sys.stderr)
        return 1
    payload, status = _read_bounded_stdin(
        "pre-validation-bundle-oversize", "pre-validation-bundle-malformed"
    )
    if status != 0:
        return status
    try:
        capsule_id = capture_approved_candidate_custody(
            args.candidate_provenance_id,
            pre_validation_bundle_payload=payload,
            dependency_readiness_evidence_id=args.dependency_readiness_evidence_id,
        )
    except HostIngressError as exc:
        print(f"blocked:{exc}", file=sys.stderr)
        return 1
    print(capsule_id)
    return 0


def _record_dependency_readiness_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-os-host-record-dependency-readiness"
    )
    parser.add_argument("--candidate-provenance-id", required=True)
    return parser


def main_record_dependency_readiness(argv: Sequence[str] | None = None) -> int:
    args = _record_dependency_readiness_parser().parse_args(argv)
    if type(args.candidate_provenance_id) is not str or _PROVENANCE_ID_RE.fullmatch(
        args.candidate_provenance_id
    ) is None:
        print("blocked:candidate-provenance-id-malformed", file=sys.stderr)
        return 1
    payload, status = _read_bounded_stdin(
        "dev-validation-evidence-oversize", "dev-validation-evidence-malformed"
    )
    if status != 0:
        return status
    if payload is None:
        print("blocked:dev-validation-evidence-malformed", file=sys.stderr)
        return 1
    try:
        evidence_id = record_codespaces_dependency_readiness(
            args.candidate_provenance_id, payload
        )
    except HostIngressError as exc:
        print(f"blocked:{exc}", file=sys.stderr)
        return 1
    print(evidence_id)
    return 0


def _freeze_pre_validation_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-os-host-freeze-pre-validation-evidence")
    parser.add_argument("--candidate-provenance-id", required=True)
    return parser


def main_freeze_pre_validation(argv: Sequence[str] | None = None) -> int:
    args = _freeze_pre_validation_parser().parse_args(argv)
    if type(args.candidate_provenance_id) is not str or _PROVENANCE_ID_RE.fullmatch(
        args.candidate_provenance_id
    ) is None:
        print("blocked:candidate-provenance-id-malformed", file=sys.stderr)
        return 1
    payload, status = _read_bounded_stdin(
        "dev-validation-evidence-oversize", "dev-validation-evidence-malformed"
    )
    if status != 0:
        return status
    if payload is None:
        print("blocked:dev-validation-evidence-malformed", file=sys.stderr)
        return 1
    try:
        serialized = freeze_pre_validation_evidence(args.candidate_provenance_id, payload)
    except HostIngressError as exc:
        print(f"blocked:{exc}", file=sys.stderr)
        return 1
    print(serialized)
    return 0


def _originate_request_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-os-host-originate-authorized-validation-request"
    )
    parser.add_argument("--candidate-provenance-id", required=True)
    parser.add_argument("--approval-custody-capsule-id", required=True)
    return parser


def main_originate_authorized_validation_request(argv: Sequence[str] | None = None) -> int:
    args = _originate_request_parser().parse_args(argv)
    payload, status = _read_bounded_stdin(
        "pre-validation-bundle-oversize", "pre-validation-bundle-malformed"
    )
    if status != 0:
        return status
    if payload is None:
        print("blocked:pre-validation-bundle-malformed", file=sys.stderr)
        return 1
    try:
        serialized = originate_authorized_validation_request(
            args.candidate_provenance_id,
            args.approval_custody_capsule_id,
            payload,
        )
    except HostIngressError as exc:
        print(f"blocked:{exc}", file=sys.stderr)
        return 1
    print(serialized)
    return 0


def _run_validation_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-os-host-run-authorized-validation")
    parser.add_argument("--expected-request-id", required=True)
    return parser


def main_run_authorized_validation(argv: Sequence[str] | None = None) -> int:
    args = _run_validation_parser().parse_args(argv)
    data = sys.stdin.buffer.read(_MAX_VNEXT_SERIALIZED_BYTES + 1)
    if len(data) > _MAX_VNEXT_SERIALIZED_BYTES:
        print("blocked:authorized-validation-request-oversize", file=sys.stderr)
        return 1
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        print("blocked:authorized-validation-request-malformed", file=sys.stderr)
        return 1
    try:
        result, source_capsule_id = run_authorized_validation(
            args.expected_request_id, payload
        )
    except (HostIngressError, ProductionAuthorizedValidationCallerError) as exc:
        print(f"blocked:{exc}", file=sys.stderr)
        return 1
    terminal_status = getattr(result, "terminal_status", None)
    print(
        json.dumps(
            {
                "terminal_status": terminal_status,
                "source_capsule_id": source_capsule_id,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via module entrypoint
    raise SystemExit(main_capture_custody())
