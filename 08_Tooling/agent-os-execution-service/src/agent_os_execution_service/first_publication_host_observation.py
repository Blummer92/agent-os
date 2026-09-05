"""Trusted-host #1431 observation composition for one #1412 source capsule (#1930).

Caller input is one immutable source-capsule identity. Host paths/configuration,
GitHub reads, Git observations, environment facts, dependency readiness, and
canonical route semantics remain owned by existing components. The successful
boundary delegates exactly once to #1428 and stops before publication/Scheduler.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol

from scripts.agent_os_candidate_packet.cli import prepare_candidate_packet
from scripts.agent_os_candidate_packet.models import CandidatePacketPhase
from scripts.agent_os_candidate_packet_live_input.issue_reader import LiveIssueReader
from scripts.agent_os_candidate_packet_live_input.repository_reader import LiveRepositoryEvidenceReader
from scripts.agent_os_execution_capabilities.dependencies import (
    DependencyPreparationStatus,
    DependencyReadinessEvidence,
)
from scripts.agent_os_execution_checkpoint.construction import (
    AcceptanceCriteriaEvidence,
    CanonicalExecutionEvidence,
    DependencyEvidence,
    DependencyManifestEvidence,
    EnvironmentEvidence,
    GovernanceContractEvidence,
    GovernanceDocumentEvidence,
    StageObservation,
    WorktreeEvidence,
)
from scripts.agent_os_execution_checkpoint.dependency_readiness_store import (
    deserialize_dependency_readiness,
)
from scripts.agent_os_execution_checkpoint.models import (
    CheckpointStage,
    StageStatus,
    WorktreeRole,
)
from scripts.agent_os_execution_interface.pre_pr_runtime_compatibility import (
    project_pre_pr_runtime_capabilities,
)
from scripts.agent_os_issue_acceptance.issue_operational_state import (
    AuthorityProjection,
    AuthorizationState,
)
from scripts.agent_os_issue_acceptance.issue_operational_state_acquisition import (
    acquire_issue_operational_state,
)
from scripts.agent_os_issue_acceptance.live_compute_control_binding import (
    LiveCurrentIssueSnapshotReader,
    dependency_state_from_evidence,
    validation_state_from_evidence,
)
from scripts.agent_os_issue_acceptance.operating_mode import (
    EnvironmentCapabilityEvidence,
    EnvironmentCapabilityState,
)
from workflow_scheduler.execution.single_issue_pilot import (
    WorkspaceRequest,
    pilot_workspace_identity,
)

from .authorized_validation import AUTHORIZED_VALIDATION_PERMITTED_OPERATION
from .execution_authorization_source import (
    ExecutionAuthorizationSourceStatus,
    reacquire_execution_authorization,
)
from .executor_routing import ExecutorCapability, ExecutorRoute, select_executor_route
from .first_publication_producer import RouteSelectionEvidence
from .first_publication_source_activation import (
    FirstPublicationSourceActivationRequest,
    activate_first_publication_source,
)
from .host_github_read_transport import (
    HostGitHubReadTransport,
    build_host_github_read_transport_from_environment,
)
from .live_route_context import (
    ExactSourceLineage,
    StructuredPullRequest,
    build_live_route_context,
    verify_exact_lineage,
)
from .models import parse_canonical_utc
from .pre_publication_evidence_store import load_source_pre_publication_evidence
from .production_handoff_publication import (
    _bundle_payload,
    _rebuild_advisory,
    _rebuild_approval,
    _repository_observation,
    _runtime_inputs,
)
from .production_host_bootstrap import (
    PRODUCER_ADAPTER_VERSION,
    ProductionHostConfiguration,
    build_subprocess_verifier_runner,
    canonical_evaluated_at,
    load_production_host_configuration,
)

_CAPSULE_ID_RE = re.compile(r"^pre-publication-evidence:[0-9a-f]{64}$", re.ASCII)
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
_ACCEPTANCE_HEADING_RE = re.compile(r"^#{1,6}\s+acceptance criteria\s*$", re.I)
_HEADING_RE = re.compile(r"^#{1,6}\s+")
_BULLET_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)(.+?)\s*$")
_MAX_READINESS_RECORDS = 4096
_MAX_ACCEPTANCE_ITEMS = 64
_PRE_PR_OPERATION = "pre-pr-developer-loop"
_GOVERNANCE_PATHS = (
    "AGENTS.md",
    "00_Governance/ownership-and-source-of-truth.md",
    "00_Governance/write-authorization-policy.md",
    "04_Registry/agent-inheritance-registry.md",
    "04_Registry/responsibility-matrix.md",
    "02_Agent_Overlays/github-service-agent.md",
    "01_Shared_Standards/github/safe-implementation-lane.md",
    "01_Shared_Standards/global-engineering/testing-and-release.md",
    "01_Shared_Standards/python/INDEX.md",
)


class FirstPublicationHostObservationError(RuntimeError):
    """Current host evidence cannot safely enter #1428."""


@dataclass(frozen=True, slots=True, kw_only=True)
class FirstPublicationActivationIdentity:
    """The only caller-selected input: one exact existing source capsule."""

    source_capsule_id: str

    def __post_init__(self) -> None:
        if type(self.source_capsule_id) is not str or not _CAPSULE_ID_RE.fullmatch(
            self.source_capsule_id
        ):
            raise ValueError("source_capsule_id is malformed")


class HostCommandRunner(Protocol):
    def __call__(self, cwd: Path, argv: tuple[str, ...]) -> str: ...


class GovernanceBlobReader(Protocol):
    def __call__(self, repository: str, revision: str, path: str) -> str: ...


@dataclass(frozen=True, slots=True)
class _LineageReader:
    github: HostGitHubReadTransport

    def current_branch_head(self, repository: str, branch: str) -> str:
        payload = self.github.read_json(f"/repos/{repository}/git/ref/heads/{branch}", None)
        if not isinstance(payload, Mapping):
            raise FirstPublicationHostObservationError("branch-ref-malformed")
        object_payload = payload.get("object")
        if not isinstance(object_payload, Mapping):
            raise FirstPublicationHostObservationError("branch-ref-malformed")
        sha = object_payload.get("sha")
        if type(sha) is not str or not _SHA40_RE.fullmatch(sha):
            raise FirstPublicationHostObservationError("branch-ref-malformed")
        return sha

    def pull_requests_for_head(
        self, repository: str, branch: str
    ) -> tuple[StructuredPullRequest, ...]:
        owner = repository.split("/", 1)[0]
        payload = self.github.read_json(
            f"/repos/{repository}/pulls",
            {"state": "all", "head": f"{owner}:{branch}", "per_page": 100},
        )
        if type(payload) is not list:
            raise FirstPublicationHostObservationError("pull-request-evidence-malformed")
        values: list[StructuredPullRequest] = []
        for item in payload:
            if not isinstance(item, Mapping):
                raise FirstPublicationHostObservationError("pull-request-evidence-malformed")
            head = item.get("head")
            if not isinstance(head, Mapping):
                raise FirstPublicationHostObservationError("pull-request-evidence-malformed")
            values.append(
                StructuredPullRequest(
                    number=item.get("number"),
                    branch=head.get("ref"),
                    head_sha=head.get("sha"),
                    draft=item.get("draft"),
                    merged=item.get("merged_at") is not None,
                    state=item.get("state"),
                )
            )
        return tuple(values)


def activate_first_publication_from_host(
    identity: FirstPublicationActivationIdentity,
    *,
    configuration: ProductionHostConfiguration | None = None,
    evaluated_at: str | None = None,
    transport: HostGitHubReadTransport | None = None,
    run_verifier=None,
    run_command: HostCommandRunner | None = None,
    governance_blob_reader: GovernanceBlobReader | None = None,
):
    """Acquire all current #1431 inputs, delegate once to #1428, then stop."""
    if type(identity) is not FirstPublicationActivationIdentity:
        raise TypeError("identity must be exact FirstPublicationActivationIdentity")
    try:
        config = configuration or load_production_host_configuration()
        if type(config) is not ProductionHostConfiguration:
            raise FirstPublicationHostObservationError("host-configuration-malformed")
        now = evaluated_at or canonical_evaluated_at()
        parse_canonical_utc(now)
        github = transport or build_host_github_read_transport_from_environment()
        verifier = run_verifier or build_subprocess_verifier_runner()
        command = run_command or _subprocess_command
        blob_reader = governance_blob_reader or _github_blob_sha

        source = load_source_pre_publication_evidence(
            config.checkpoint_store_root, identity.source_capsule_id
        )
        packet = source.candidate_packet
        payload = _bundle_payload(source.validation_bundle_json)
        advisory = _rebuild_advisory(packet, source, payload)

        readiness = _select_dependency_readiness(
            config.checkpoint_store_root,
            source_sha=packet.candidate_sha,
            required_environment_id=source.required_environment_spec.required_environment_id,
            evaluated_at=now,
        )
        repository_reader = LiveRepositoryEvidenceReader(
            repository=packet.repository,
            issue_number=packet.issue_number,
            required_environment_spec=source.required_environment_spec,
            dependency_readiness=readiness,
            validation_result=advisory,
            evaluated_at=now,
            expected_validation_plan_id=source.validation_plan_id,
        )
        observation = _repository_observation(
            config=config,
            packet=packet,
            capsule=source,
            payload=payload,
            evaluated_at=now,
            run_verifier=verifier,
        )
        prepared = prepare_candidate_packet(
            repository=packet.repository,
            issue_number=packet.issue_number,
            issue_reader=LiveIssueReader(github),
            repository_reader=repository_reader,
            observed_at=now,
            base_branch=packet.base_branch,
            evaluated_repository_sha=observation.base_sha,
            invocation_id=packet.invocation_id,
            evaluator_sha=packet.evaluator_sha,
            repository_observation=observation,
            requested_phase=CandidatePacketPhase.APPROVAL_READY,
            external_build_sha=packet.external_build_sha,
            compiler_evaluated_at=now,
        )
        approval_stage, proposal, issueplan, repository_state = _rebuild_approval(
            prepared, packet, source, now
        )
        preauth = _runtime_inputs(
            packet=packet,
            capsule=source,
            repository_state=repository_state,
            projection=approval_stage.projection,
            configuration=config,
            evaluated_at=now,
            authorization_present=False,
        )
        from scripts.agent_os_candidate_packet.execution_packet_stage import prepare_execution_packet

        preauth_stage = prepare_execution_packet(approval_stage, preauth)
        if (
            not preauth_stage.packet_complete
            or preauth_stage.request_fingerprint is None
            or preauth_stage.command_plan_id is None
        ):
            raise FirstPublicationHostObservationError("execution-packet-incomplete")
        authorization = reacquire_execution_authorization(
            transport=github,
            repository=packet.repository,
            issue_number=packet.issue_number,
            expected_candidate_packet_id=packet.packet_id,
            expected_invocation_id=packet.invocation_id,
            expected_operation=AUTHORIZED_VALIDATION_PERMITTED_OPERATION,
            expected_request_fingerprint=preauth_stage.request_fingerprint,
            expected_command_plan_id=preauth_stage.command_plan_id,
            expected_sha=packet.candidate_sha,
            evaluated_at=now,
        )
        if (
            authorization.status is not ExecutionAuthorizationSourceStatus.CURRENT
            or authorization.evidence is None
        ):
            raise FirstPublicationHostObservationError("execution-authorization-not-current")

        issue_result = github.get_issue(packet.repository, packet.issue_number)
        if issue_result.item is None:
            raise FirstPublicationHostObservationError("issue-source-unavailable")
        issue_item = issue_result.item
        issue_open = issue_item.get("state") == "open"
        if issue_item.get("state") not in {"open", "closed"}:
            raise FirstPublicationHostObservationError("issue-state-malformed")
        lineage = ExactSourceLineage(
            source_capsule_id=source.capsule_id,
            repository=packet.repository,
            issue_number=packet.issue_number,
            branch=source.candidate_branch,
            source_sha=packet.candidate_sha,
            tested_sha=packet.tested_sha,
        )
        verified = verify_exact_lineage(
            lineage, reader=_LineageReader(github), issue_open=issue_open
        )
        issue_reader = LiveCurrentIssueSnapshotReader(
            transport=github,
            source_revision=packet.candidate_sha,
            observed_at=now,
            lifecycle_stage=verified.lifecycle_stage,
        )
        execution_projection = AuthorityProjection(
            state=AuthorizationState.AUTHORIZED,
            evidence_id=authorization.evidence.authorization_id,
            bound_base_sha=authorization.evidence.expected_sha,
            observed_base_sha=packet.candidate_sha,
        )
        acquired = acquire_issue_operational_state(
            repository=packet.repository,
            issue_number=packet.issue_number,
            issue_reader=issue_reader,
            approval_acquirer=lambda _snapshot: approval_stage.applicability,
            dependency_acquirer=lambda _snapshot: dependency_state_from_evidence(
                repository_reader.read_dependency_evidence(packet.repository, packet.issue_number)
            ),
            claim_acquirer=lambda _snapshot: verified.primary_claims,
            validation_acquirer=lambda _snapshot: validation_state_from_evidence(
                repository_reader.read_validation_evidence(packet.repository, packet.issue_number)
            ),
            freshness_acquirer=lambda _snapshot: verified.freshness_state,
            execution_authorization_acquirer=lambda _snapshot: execution_projection,
        )
        environment_capability = _environment_capability(
            readiness, source_sha=packet.candidate_sha
        )
        route_context = build_live_route_context(
            lineage=lineage,
            verified=verified,
            operational=acquired,
            environment=environment_capability,
            execution_authorization=execution_projection,
        )

        execution, worktree = _git_evidence(
            config=config,
            source=source,
            command=command,
            command_plan_id=preauth_stage.command_plan_id,
            authorization_id=authorization.evidence.authorization_id,
        )
        environment = _host_environment(readiness)
        dependencies = _dependency_manifests(config.repository_root, source)
        acceptance = AcceptanceCriteriaEvidence(
            issue_number=packet.issue_number,
            criteria=_acceptance_criteria(issue_item.get("body")),
        )
        governance = GovernanceContractEvidence(
            documents=tuple(
                GovernanceDocumentEvidence(
                    path=path,
                    blob_sha=blob_reader(packet.repository, packet.candidate_sha, path),
                )
                for path in _GOVERNANCE_PATHS
            )
        )
        stages = (
            StageObservation(
                stage=CheckpointStage.PREFLIGHT_COMPLETE,
                status=StageStatus.PASSED,
                tested_sha=packet.tested_sha,
                evidence_hashes=(),
            ),
        )
        runtime = project_pre_pr_runtime_capabilities(
            required_environment=source.required_environment_spec,
            dependency_readiness=readiness,
            evaluated_at=now,
        )
        route_decision = select_executor_route(
            repository=packet.repository,
            issue_or_handoff_identity=f"issue:{packet.issue_number}",
            requested_operation=_PRE_PR_OPERATION,
            required_capabilities=runtime.required_capabilities,
            governed_runner_capabilities=runtime.required_capabilities,
            governed_runner_available=True,
            external_fallback_available=False,
            external_fallback_explicitly_permitted=False,
            created_at=now,
            expires_at=source.expires_at,
            invalidation_conditions=("environment-changed", "repository-head-changed"),
            evidence_stale=runtime.evidence_stale,
            evidence_contradictory=runtime.evidence_contradictory,
            execution_service_request_fingerprint_or_none=preauth_stage.request_fingerprint,
            authorization_id_or_none=authorization.evidence.authorization_id,
            validation_command_plan_id_or_none=preauth_stage.command_plan_id,
            operating_mode_decision_id_or_none=route_context.operating_mode.decision_id,
            executable_lane_selection_id_or_none=route_context.lane_selection.selection_id,
            repository_state_evidence_id_or_none=repository_state.evidence_id,
            environment_profile_id_or_none=_environment_profile_id(readiness),
            environment_health_evidence_id_or_none=readiness.environment_health_evidence_id,
            workflow_runtime_identity_or_none="workflow-runtime:production-gce",
            execution_authorized=authorization.evidence.execution_authorized,
        )
        if route_decision.selected_route is not ExecutorRoute.CHATGPT_GOVERNED_RUNNER:
            raise FirstPublicationHostObservationError("governed-runner-route-not-current")
        route = RouteSelectionEvidence(
            repository=route_decision.repository,
            issue_or_handoff_identity=route_decision.issue_or_handoff_identity,
            requested_operation=route_decision.requested_operation,
            required_capabilities=route_decision.required_capabilities,
            governed_runner_capabilities=route_decision.governed_runner_capabilities,
            governed_runner_available=route_decision.governed_runner_available,
            external_fallback_available=False,
            external_fallback_explicitly_permitted=False,
            created_at=route_decision.created_at,
            expires_at=route_decision.expires_at,
            invalidation_conditions=route_decision.invalidation_conditions,
            operating_mode_decision_id=route_context.operating_mode.decision_id,
            executable_lane_selection_id=route_context.lane_selection.selection_id,
            execution_service_request_fingerprint=preauth_stage.request_fingerprint,
            validation_command_plan_id=preauth_stage.command_plan_id,
            repository_state_evidence_id=repository_state.evidence_id,
            environment_profile_id=route_decision.environment_profile_id_or_none,
            environment_health_evidence_id=readiness.environment_health_evidence_id,
            workflow_runtime_identity=route_decision.workflow_runtime_identity_or_none,
            evidence_stale=route_decision.evidence_stale,
            evidence_contradictory=route_decision.evidence_contradictory,
        )
        request = FirstPublicationSourceActivationRequest(
            source_capsule_id=source.capsule_id,
            execution=execution,
            worktree=worktree,
            environment=environment,
            dependencies=dependencies,
            acceptance=acceptance,
            governance=governance,
            stage_observations=stages,
            actor_id="github-service-agent",
            dependency_readiness=readiness,
            authorization=authorization.evidence,
            route=route,
            evaluated_at=now,
            expires_at=source.expires_at,
        )
        return activate_first_publication_source(config.checkpoint_store_root, request)
    except FirstPublicationHostObservationError:
        raise
    except (KeyboardInterrupt, SystemExit, GeneratorExit):
        raise
    except (TypeError, ValueError, LookupError, OSError, RuntimeError) as exc:
        raise FirstPublicationHostObservationError(
            "first-publication-host-observation-failed-closed"
        ) from exc


def _select_dependency_readiness(
    store_root: Path,
    *,
    source_sha: str,
    required_environment_id: str,
    evaluated_at: str,
) -> DependencyReadinessEvidence:
    directory = store_root / "dependency-readiness"
    try:
        paths = tuple(sorted(directory.glob("*.json")))
    except OSError as exc:
        raise FirstPublicationHostObservationError("dependency-readiness-unavailable") from exc
    if len(paths) > _MAX_READINESS_RECORDS:
        raise FirstPublicationHostObservationError("dependency-readiness-ambiguous")
    matches: list[DependencyReadinessEvidence] = []
    for path in paths:
        if path.is_symlink():
            raise FirstPublicationHostObservationError("dependency-readiness-unavailable")
        try:
            evidence = deserialize_dependency_readiness(path.read_bytes())
        except (OSError, TypeError, ValueError) as exc:
            raise FirstPublicationHostObservationError("dependency-readiness-malformed") from exc
        if (
            evidence.source_sha == source_sha
            and evidence.required_environment_id == required_environment_id
            and evidence.preparation_status is DependencyPreparationStatus.READY
            and evidence.is_current(evaluated_at)
        ):
            matches.append(evidence)
    if len(matches) != 1:
        raise FirstPublicationHostObservationError(
            "dependency-readiness-missing" if not matches else "dependency-readiness-ambiguous"
        )
    return matches[0]


def _git_evidence(*, config, source, command, command_plan_id, authorization_id):
    packet = source.candidate_packet
    request = WorkspaceRequest(
        workspace_request_id=source.workspace_request_id,
        repository=packet.repository,
        branch=source.candidate_branch,
        expected_revision=packet.candidate_sha,
    )
    workspace_identity = pilot_workspace_identity(request)
    suffix = hashlib.sha256(workspace_identity.encode("utf-8")).hexdigest()[:24]
    workspace = config.workspace_parent / f"agent-os-worktree-{suffix}"
    if not workspace.is_dir():
        raise FirstPublicationHostObservationError("candidate-worktree-missing")
    branch = command(workspace, ("git", "branch", "--show-current")).strip()
    head = command(workspace, ("git", "rev-parse", "HEAD")).strip()
    tree = command(workspace, ("git", "write-tree")).strip()
    merge_base = command(
        workspace, ("git", "merge-base", "HEAD", packet.base_branch)
    ).strip()
    diff = command(workspace, ("git", "diff", "--binary", "HEAD"))
    if branch != source.candidate_branch or head != packet.candidate_sha:
        raise FirstPublicationHostObservationError("candidate-worktree-lineage-mismatch")
    for value, name in ((tree, "index-tree"), (merge_base, "merge-base")):
        if not _SHA40_RE.fullmatch(value):
            raise FirstPublicationHostObservationError(f"{name}-malformed")
    worktree = WorktreeEvidence(
        branch=branch,
        worktree_role=WorktreeRole.ISSUE,
        source_sha=head,
        index_tree_sha=tree,
        working_diff_digest=hashlib.sha256(diff.encode("utf-8")).hexdigest(),
    )
    execution = CanonicalExecutionEvidence(
        repository=packet.repository,
        issue_number=packet.issue_number,
        invocation_id=packet.invocation_id,
        execution_id=source.execution_id,
        branch=branch,
        worktree_role=WorktreeRole.ISSUE,
        source_sha=head,
        tested_sha=packet.tested_sha,
        merge_base_sha=merge_base,
        command_plan_id=command_plan_id,
        authorization_snapshot_id=authorization_id,
    )
    return execution, worktree


def _host_environment(readiness: DependencyReadinessEvidence) -> EnvironmentEvidence:
    return EnvironmentEvidence(
        operating_system=_safe_token(platform.system().lower()),
        architecture=_safe_token(platform.machine().lower()),
        runtime_identities=tuple(
            sorted(
                {
                    f"python:{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
                    f"package-manager:{_safe_token(readiness.package_manager_version)}",
                    f"runtime:{_safe_token(readiness.runtime_version)}",
                }
            )
        ),
    )


def _dependency_manifests(repository_root: Path, source) -> DependencyEvidence:
    spec = source.required_environment_spec
    identities = [spec.dependency_manifest_identity]
    if spec.lock_or_constraints_identity is not None:
        identities.append(spec.lock_or_constraints_identity)
    identities.extend(spec.local_project_requirements)
    manifests: list[DependencyManifestEvidence] = []
    for identity in identities:
        relative = identity.relative_path
        path = repository_root / relative
        if not path.is_file() or path.is_symlink():
            raise FirstPublicationHostObservationError("dependency-manifest-missing")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != identity.sha256:
            raise FirstPublicationHostObservationError("dependency-manifest-drift")
        manifests.append(DependencyManifestEvidence(path=relative, content_digest=digest))
    return DependencyEvidence(manifests=tuple(manifests))


def _acceptance_criteria(body: object) -> tuple[str, ...]:
    if type(body) is not str:
        raise FirstPublicationHostObservationError("issue-body-malformed")
    lines = body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    start = next((index + 1 for index, line in enumerate(lines) if _ACCEPTANCE_HEADING_RE.fullmatch(line.strip())), None)
    if start is None:
        raise FirstPublicationHostObservationError("acceptance-criteria-missing")
    criteria: list[str] = []
    for line in lines[start:]:
        if _HEADING_RE.match(line.strip()):
            break
        match = _BULLET_RE.match(line)
        if match:
            value = match.group(1).strip()
            if value.startswith("[ ]") or value.lower().startswith("[x]"):
                value = value[3:].strip()
            if value:
                criteria.append(value)
    if not criteria or len(criteria) > _MAX_ACCEPTANCE_ITEMS:
        raise FirstPublicationHostObservationError("acceptance-criteria-invalid")
    if len(set(criteria)) != len(criteria):
        raise FirstPublicationHostObservationError("acceptance-criteria-duplicate")
    return tuple(criteria)


def _environment_capability(readiness, *, source_sha):
    return EnvironmentCapabilityEvidence(
        local_execution_state=EnvironmentCapabilityState.VERIFIED,
        push_state=EnvironmentCapabilityState.NOT_VERIFIED,
        evidence_id=readiness.environment_health_evidence_id,
        bound_source_revision=source_sha,
        observed_source_revision=readiness.source_sha,
    )


def _environment_profile_id(readiness: DependencyReadinessEvidence) -> str:
    material = json.dumps(
        {
            "execution_surface_id": readiness.execution_surface_id,
            "environment_health_evidence_id": readiness.environment_health_evidence_id,
            "runtime_version": readiness.runtime_version,
            "package_manager_version": readiness.package_manager_version,
            "source_sha": readiness.source_sha,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "environment-profile:" + hashlib.sha256(material).hexdigest()


def _safe_token(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._:+/@-]", "-", value.strip())
    if not normalized:
        raise FirstPublicationHostObservationError("host-environment-malformed")
    return normalized[:255]


def _subprocess_command(cwd: Path, argv: tuple[str, ...]) -> str:
    if not argv or argv[0] != "git":
        raise FirstPublicationHostObservationError("host-command-not-admitted")
    allowed = {
        ("git", "branch", "--show-current"),
        ("git", "rev-parse", "HEAD"),
        ("git", "write-tree"),
        ("git", "diff", "--binary", "HEAD"),
    }
    if argv not in allowed and not (
        len(argv) == 4 and argv[:3] == ("git", "merge-base", "HEAD")
    ):
        raise FirstPublicationHostObservationError("host-command-not-admitted")
    completed = subprocess.run(
        argv,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode != 0:
        raise FirstPublicationHostObservationError("host-git-observation-failed")
    return completed.stdout


def _github_blob_sha(repository: str, revision: str, path: str) -> str:
    transport = build_host_github_read_transport_from_environment()
    payload = transport.read_json(f"/repos/{repository}/contents/{path}", {"ref": revision})
    if not isinstance(payload, Mapping):
        raise FirstPublicationHostObservationError("governance-document-unavailable")
    sha = payload.get("sha")
    if type(sha) is not str or not _SHA40_RE.fullmatch(sha):
        raise FirstPublicationHostObservationError("governance-blob-malformed")
    return sha
