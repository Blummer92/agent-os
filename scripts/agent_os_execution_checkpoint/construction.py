"""Canonical, pure construction boundary for :class:`ExecutionCheckpoint`.

This module owns only the deterministic derivation of #895 checkpoint bindings
that cannot be accepted safely as caller-selected hashes.  It performs no I/O,
persistence, network, GitHub, Scheduler, authorization, or lifecycle mutation.
Callers must supply already-observed canonical evidence from the owning systems;
this module validates those observations, derives bounded fingerprints/digests,
selects the highest truthfully evidenced checkpoint stage, and returns the
existing ``ExecutionCheckpoint`` model.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .identity import canonical_json_bytes
from .models import (
    CANONICAL_STAGE_ORDER,
    CHECKPOINT_SCHEMA_NAME,
    CHECKPOINT_SCHEMA_VERSION,
    STAGE_KIND_MAP,
    STAGE_LIFECYCLE_MAP,
    CheckpointStage,
    ExecutionCheckpoint,
    InvalidationState,
    LifecycleState,
    StageKind,
    StageStatus,
    WorktreeRole,
    _branch,
    _evidence_hashes,
    _hex64,
    _positive_int,
    _repository,
    _sha256_id,
    _sha40,
    _token,
)

WORKTREE_FINGERPRINT_DOMAIN = "agent-os.execution-checkpoint.worktree"
ENVIRONMENT_FINGERPRINT_DOMAIN = "agent-os.execution-checkpoint.environment"
DEPENDENCY_FINGERPRINT_DOMAIN = "agent-os.execution-checkpoint.dependencies"
ACCEPTANCE_CRITERIA_DIGEST_DOMAIN = "agent-os.execution-checkpoint.acceptance-criteria"
GOVERNANCE_CONTRACT_DIGEST_DOMAIN = "agent-os.execution-checkpoint.governance-contract"

_MAX_ITEMS = 64
_MAX_TEXT_BYTES = 4096
_RELATIVE_PATH_RE = re.compile(r"^[A-Za-z0-9_.-][A-Za-z0-9_./-]{0,511}$")
_SAFE_IDENTITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/@-]{0,255}$")


class CheckpointConstructionError(ValueError):
    """Construction evidence is incomplete, contradictory, or non-canonical."""


def _domain_hex_digest(domain: str, payload: object) -> str:
    material = domain.encode("utf-8") + b":v1\0" + canonical_json_bytes(payload)
    return hashlib.sha256(material).hexdigest()


def _safe_identity(value: object, name: str) -> str:
    if type(value) is not str or not _SAFE_IDENTITY_RE.fullmatch(value):
        raise CheckpointConstructionError(f"{name} is malformed")
    return value


def _relative_path(value: object, name: str) -> str:
    if type(value) is not str or not _RELATIVE_PATH_RE.fullmatch(value):
        raise CheckpointConstructionError(f"{name} is malformed")
    if value.startswith("/") or ".." in value.split("/"):
        raise CheckpointConstructionError(f"{name} must be repository-relative")
    return value


def _normalized_contract_text(value: object, name: str) -> str:
    if type(value) is not str:
        raise CheckpointConstructionError(f"{name} must be a built-in string")
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.strip().split("\n"))
    if not text or len(text.encode("utf-8")) > _MAX_TEXT_BYTES:
        raise CheckpointConstructionError(f"{name} is outside bounds")
    return text


def _bounded_tuple(values: object, name: str) -> tuple[object, ...]:
    if type(values) is not tuple:
        raise CheckpointConstructionError(f"{name} must be an exact tuple")
    if not values or len(values) > _MAX_ITEMS:
        raise CheckpointConstructionError(f"{name} is outside bounds")
    return values


@dataclass(frozen=True, slots=True)
class CanonicalExecutionEvidence:
    """Direct identities observed by their existing canonical owners."""

    repository: str
    issue_number: int
    invocation_id: str
    execution_id: str
    branch: str
    worktree_role: WorktreeRole
    source_sha: str
    tested_sha: str
    merge_base_sha: str
    command_plan_id: str
    authorization_snapshot_id: str | None = None

    def __post_init__(self) -> None:
        try:
            _repository(self.repository)
            _positive_int(self.issue_number, "issue_number")
            _token(self.invocation_id, "invocation_id")
            _token(self.execution_id, "execution_id")
            _branch(self.branch)
            if not isinstance(self.worktree_role, WorktreeRole):
                raise TypeError("worktree_role must be WorktreeRole")
            _sha40(self.source_sha, "source_sha")
            _sha40(self.tested_sha, "tested_sha")
            _sha40(self.merge_base_sha, "merge_base_sha")
            _sha256_id(self.command_plan_id, "command_plan_id")
            if self.authorization_snapshot_id is not None:
                _sha256_id(self.authorization_snapshot_id, "authorization_snapshot_id")
        except (TypeError, ValueError) as exc:
            raise CheckpointConstructionError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class WorktreeEvidence:
    """Canonical git/worktree facts; never an absolute path or directory hash."""

    branch: str
    worktree_role: WorktreeRole
    source_sha: str
    index_tree_sha: str
    working_diff_digest: str

    def __post_init__(self) -> None:
        try:
            _branch(self.branch)
            if not isinstance(self.worktree_role, WorktreeRole):
                raise TypeError("worktree_role must be WorktreeRole")
            _sha40(self.source_sha, "source_sha")
            _sha40(self.index_tree_sha, "index_tree_sha")
            _hex64(self.working_diff_digest, "working_diff_digest")
        except (TypeError, ValueError) as exc:
            raise CheckpointConstructionError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class EnvironmentEvidence:
    """Bounded execution/test environment identities with no paths or secrets."""

    operating_system: str
    architecture: str
    runtime_identities: tuple[str, ...]
    container_image_digest: str | None = None

    def __post_init__(self) -> None:
        _safe_identity(self.operating_system, "operating_system")
        _safe_identity(self.architecture, "architecture")
        values = _bounded_tuple(self.runtime_identities, "runtime_identities")
        checked = tuple(_safe_identity(value, "runtime_identity") for value in values)
        if len(set(checked)) != len(checked):
            raise CheckpointConstructionError("runtime_identities contains duplicates")
        if self.container_image_digest is not None:
            try:
                _hex64(self.container_image_digest, "container_image_digest")
            except (TypeError, ValueError) as exc:
                raise CheckpointConstructionError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class DependencyManifestEvidence:
    path: str
    content_digest: str

    def __post_init__(self) -> None:
        _relative_path(self.path, "dependency path")
        try:
            _hex64(self.content_digest, "dependency content_digest")
        except (TypeError, ValueError) as exc:
            raise CheckpointConstructionError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class DependencyEvidence:
    manifests: tuple[DependencyManifestEvidence, ...]

    def __post_init__(self) -> None:
        values = _bounded_tuple(self.manifests, "manifests")
        if not all(type(item) is DependencyManifestEvidence for item in values):
            raise CheckpointConstructionError(
                "manifests must contain exact DependencyManifestEvidence values"
            )
        paths = [item.path for item in values]
        if len(set(paths)) != len(paths):
            raise CheckpointConstructionError("manifests contains duplicate paths")


@dataclass(frozen=True, slots=True)
class AcceptanceCriteriaEvidence:
    issue_number: int
    criteria: tuple[str, ...]

    def __post_init__(self) -> None:
        try:
            _positive_int(self.issue_number, "issue_number")
        except (TypeError, ValueError) as exc:
            raise CheckpointConstructionError(str(exc)) from exc
        values = _bounded_tuple(self.criteria, "criteria")
        normalized = tuple(
            _normalized_contract_text(value, "acceptance criterion") for value in values
        )
        if len(set(normalized)) != len(normalized):
            raise CheckpointConstructionError("criteria contains duplicates after normalization")


@dataclass(frozen=True, slots=True)
class GovernanceDocumentEvidence:
    path: str
    blob_sha: str

    def __post_init__(self) -> None:
        _relative_path(self.path, "governance path")
        try:
            _sha40(self.blob_sha, "governance blob_sha")
        except (TypeError, ValueError) as exc:
            raise CheckpointConstructionError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class GovernanceContractEvidence:
    documents: tuple[GovernanceDocumentEvidence, ...]

    def __post_init__(self) -> None:
        values = _bounded_tuple(self.documents, "documents")
        if not all(type(item) is GovernanceDocumentEvidence for item in values):
            raise CheckpointConstructionError(
                "documents must contain exact GovernanceDocumentEvidence values"
            )
        paths = [item.path for item in values]
        if len(set(paths)) != len(paths):
            raise CheckpointConstructionError("documents contains duplicate paths")


@dataclass(frozen=True, slots=True)
class StageObservation:
    """Observed evidence for one exact stage and exact tested specimen head."""

    stage: CheckpointStage
    status: StageStatus
    tested_sha: str
    evidence_hashes: tuple[tuple[str, str], ...] = ()
    mutation_intent_id: str | None = None
    pre_read_digest: str | None = None
    post_write_digest: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.stage, CheckpointStage):
            raise CheckpointConstructionError("stage must be CheckpointStage")
        if not isinstance(self.status, StageStatus):
            raise CheckpointConstructionError("status must be StageStatus")
        try:
            _sha40(self.tested_sha, "tested_sha")
            object.__setattr__(self, "evidence_hashes", _evidence_hashes(self.evidence_hashes))
            if self.mutation_intent_id is not None:
                _sha256_id(self.mutation_intent_id, "mutation_intent_id")
            if self.pre_read_digest is not None:
                _hex64(self.pre_read_digest, "pre_read_digest")
            if self.post_write_digest is not None:
                _hex64(self.post_write_digest, "post_write_digest")
        except (TypeError, ValueError) as exc:
            raise CheckpointConstructionError(str(exc)) from exc

        kind = STAGE_KIND_MAP[self.stage]
        if kind is StageKind.READ_ONLY and self.mutation_intent_id is not None:
            raise CheckpointConstructionError(
                "read-only stage observation cannot carry mutation_intent_id"
            )
        if kind is not StageKind.READ_ONLY and self.status in (
            StageStatus.PASSED,
            StageStatus.UNCERTAIN,
        ) and self.mutation_intent_id is None:
            raise CheckpointConstructionError(
                "passed or uncertain mutating stage observation requires mutation_intent_id"
            )
        if kind is not StageKind.READ_ONLY and self.status is StageStatus.PASSED:
            if self.pre_read_digest is None or self.post_write_digest is None:
                raise CheckpointConstructionError(
                    "passed mutating stage observation requires pre/post read digests"
                )


def derive_worktree_fingerprint(evidence: WorktreeEvidence) -> str:
    if type(evidence) is not WorktreeEvidence:
        raise TypeError("evidence must be exact WorktreeEvidence")
    return _domain_hex_digest(
        WORKTREE_FINGERPRINT_DOMAIN,
        {
            "branch": evidence.branch,
            "worktree_role": evidence.worktree_role.value,
            "source_sha": evidence.source_sha,
            "index_tree_sha": evidence.index_tree_sha,
            "working_diff_digest": evidence.working_diff_digest,
        },
    )


def derive_environment_fingerprint(evidence: EnvironmentEvidence) -> str:
    if type(evidence) is not EnvironmentEvidence:
        raise TypeError("evidence must be exact EnvironmentEvidence")
    return _domain_hex_digest(
        ENVIRONMENT_FINGERPRINT_DOMAIN,
        {
            "operating_system": evidence.operating_system,
            "architecture": evidence.architecture,
            "runtime_identities": sorted(evidence.runtime_identities),
            "container_image_digest": evidence.container_image_digest,
        },
    )


def derive_dependency_fingerprint(evidence: DependencyEvidence) -> str:
    if type(evidence) is not DependencyEvidence:
        raise TypeError("evidence must be exact DependencyEvidence")
    return _domain_hex_digest(
        DEPENDENCY_FINGERPRINT_DOMAIN,
        [
            {"path": item.path, "content_digest": item.content_digest}
            for item in sorted(evidence.manifests, key=lambda item: item.path)
        ],
    )


def derive_acceptance_criteria_digest(evidence: AcceptanceCriteriaEvidence) -> str:
    if type(evidence) is not AcceptanceCriteriaEvidence:
        raise TypeError("evidence must be exact AcceptanceCriteriaEvidence")
    return _domain_hex_digest(
        ACCEPTANCE_CRITERIA_DIGEST_DOMAIN,
        {
            "issue_number": evidence.issue_number,
            "criteria": [
                _normalized_contract_text(value, "acceptance criterion")
                for value in evidence.criteria
            ],
        },
    )


def derive_governance_contract_digest(evidence: GovernanceContractEvidence) -> str:
    if type(evidence) is not GovernanceContractEvidence:
        raise TypeError("evidence must be exact GovernanceContractEvidence")
    return _domain_hex_digest(
        GOVERNANCE_CONTRACT_DIGEST_DOMAIN,
        [
            {"path": item.path, "blob_sha": item.blob_sha}
            for item in sorted(evidence.documents, key=lambda item: item.path)
        ],
    )


def select_highest_truthful_stage(
    observations: tuple[StageObservation, ...], *, tested_sha: str
) -> StageObservation:
    """Select the highest evidenced stage, requiring a contiguous stage prefix."""

    values = _bounded_tuple(observations, "stage observations")
    if not all(type(item) is StageObservation for item in values):
        raise CheckpointConstructionError(
            "stage observations must contain exact StageObservation values"
        )
    try:
        _sha40(tested_sha, "tested_sha")
    except (TypeError, ValueError) as exc:
        raise CheckpointConstructionError(str(exc)) from exc

    by_stage: dict[CheckpointStage, StageObservation] = {}
    for observation in values:
        if observation.stage in by_stage:
            raise CheckpointConstructionError("duplicate stage observation")
        if observation.tested_sha != tested_sha:
            raise CheckpointConstructionError(
                "stage observation tested_sha differs from canonical tested_sha"
            )
        by_stage[observation.stage] = observation

    highest_index = max(CANONICAL_STAGE_ORDER.index(stage) for stage in by_stage)
    required_prefix = CANONICAL_STAGE_ORDER[: highest_index + 1]
    missing = [stage.value for stage in required_prefix if stage not in by_stage]
    if missing:
        raise CheckpointConstructionError(
            f"cannot select later checkpoint stage with missing prior evidence: {missing}"
        )
    return by_stage[CANONICAL_STAGE_ORDER[highest_index]]


def construct_execution_checkpoint(
    *,
    execution: CanonicalExecutionEvidence,
    worktree: WorktreeEvidence,
    environment: EnvironmentEvidence,
    dependencies: DependencyEvidence,
    acceptance: AcceptanceCriteriaEvidence,
    governance: GovernanceContractEvidence,
    stage_observations: tuple[StageObservation, ...],
    recorded_at: str,
    actor_id: str,
    parent_checkpoint_id: str | None = None,
    diagnostic_refs: tuple[str, ...] = (),
) -> ExecutionCheckpoint:
    """Build one existing checkpoint from canonical observations or fail closed."""

    if type(execution) is not CanonicalExecutionEvidence:
        raise TypeError("execution must be exact CanonicalExecutionEvidence")
    if type(worktree) is not WorktreeEvidence:
        raise TypeError("worktree must be exact WorktreeEvidence")
    if type(environment) is not EnvironmentEvidence:
        raise TypeError("environment must be exact EnvironmentEvidence")
    if type(dependencies) is not DependencyEvidence:
        raise TypeError("dependencies must be exact DependencyEvidence")
    if type(acceptance) is not AcceptanceCriteriaEvidence:
        raise TypeError("acceptance must be exact AcceptanceCriteriaEvidence")
    if type(governance) is not GovernanceContractEvidence:
        raise TypeError("governance must be exact GovernanceContractEvidence")

    if (
        worktree.branch != execution.branch
        or worktree.worktree_role is not execution.worktree_role
        or worktree.source_sha != execution.source_sha
    ):
        raise CheckpointConstructionError(
            "worktree evidence does not match canonical branch/role/source bindings"
        )
    if acceptance.issue_number != execution.issue_number:
        raise CheckpointConstructionError(
            "acceptance evidence does not match canonical issue binding"
        )

    selected = select_highest_truthful_stage(
        stage_observations, tested_sha=execution.tested_sha
    )

    return ExecutionCheckpoint(
        schema=CHECKPOINT_SCHEMA_NAME,
        schema_version=CHECKPOINT_SCHEMA_VERSION,
        repository=execution.repository,
        issue_number=execution.issue_number,
        invocation_id=execution.invocation_id,
        execution_id=execution.execution_id,
        branch=execution.branch,
        worktree_fingerprint=derive_worktree_fingerprint(worktree),
        worktree_role=execution.worktree_role,
        environment_fingerprint=derive_environment_fingerprint(environment),
        source_sha=execution.source_sha,
        tested_sha=execution.tested_sha,
        merge_base_sha=execution.merge_base_sha,
        dependency_fingerprint=derive_dependency_fingerprint(dependencies),
        command_plan_id=execution.command_plan_id,
        acceptance_criteria_digest=derive_acceptance_criteria_digest(acceptance),
        governance_contract_digest=derive_governance_contract_digest(governance),
        lifecycle_stage=STAGE_LIFECYCLE_MAP[selected.stage],
        checkpoint_stage=selected.stage,
        stage_status=selected.status,
        evidence_hashes=selected.evidence_hashes,
        invalidation_state=InvalidationState.CURRENT,
        lifecycle_state=LifecycleState.ACTIVE,
        recorded_at=recorded_at,
        actor_id=actor_id,
        parent_checkpoint_id=parent_checkpoint_id,
        pre_read_digest=selected.pre_read_digest,
        post_write_digest=selected.post_write_digest,
        mutation_intent_id=selected.mutation_intent_id,
        authorization_snapshot_id=execution.authorization_snapshot_id,
        diagnostic_refs=diagnostic_refs,
    )
