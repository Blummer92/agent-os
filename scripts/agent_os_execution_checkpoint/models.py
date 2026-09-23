"""Pure-local execution-checkpoint record for one Agent OS issue lifecycle.

A checkpoint records evidence only. It never creates authorization for the
next stage, performs no I/O, and holds no secrets, mutable runtime objects,
or unbounded logs. See ``README.md`` for the full contract this implements
(#858, #895).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from scripts.agent_os_issue_acceptance.issue_operational_state import LifecycleStage

from .identity import canonical_json_bytes, compute_checkpoint_id, compute_reuse_key

CHECKPOINT_SCHEMA_NAME = "agent-os.execution-checkpoint"
CHECKPOINT_SCHEMA_VERSION = "1.0"

MAX_SERIALIZED_BYTES = 64 * 1024
MAX_EVIDENCE_HASHES = 32
MAX_DIAGNOSTIC_REFS = 8
MAX_DIAGNOSTIC_REF_CHARS = 256
MAX_TOKEN_CHARS = 128
MAX_TEXT_BYTES = 4096

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_SHA256_ID_RE = re.compile(r"^[a-z][a-z0-9.-]{1,63}:[0-9a-f]{64}$")
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_EVIDENCE_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class CheckpointStage(str, Enum):
    PREFLIGHT_COMPLETE = "preflight-complete"
    IMPLEMENTATION_COMPLETE = "implementation-complete"
    FOCUSED_TESTS_PASSED = "focused-tests-passed"
    AGGREGATE_VALIDATION_PASSED = "aggregate-validation-passed"
    COMMITTED = "committed"
    PUSHED = "pushed"
    DRAFT_PR_OPENED = "draft-pr-opened"
    CI_PASSED = "ci-passed"
    REVIEW_COMPLETE = "review-complete"
    MERGED = "merged"
    ISSUE_CLOSED = "issue-closed"


class StageStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


class StageKind(str, Enum):
    READ_ONLY = "read-only"
    MUTATING_LOCAL = "mutating-local"
    MUTATING_REMOTE = "mutating-remote"


class WorktreeRole(str, Enum):
    """Mirrors the vocabulary already defined by #891's environment-health check."""

    PRIMARY = "primary"
    ISSUE_WORKTREE = "issue-worktree"


class InvalidationState(str, Enum):
    CURRENT = "current"
    INVALIDATED = "invalidated"
    SUPERSEDED = "superseded"


class LifecycleState(str, Enum):
    ACTIVE = "active"
    INTERRUPTED = "interrupted"
    ABANDONED = "abandoned"
    MANUALLY_CANCELLED = "manually-cancelled"
    SUPERSEDED = "superseded"
    QUARANTINED = "quarantined"
    COMPLETED = "completed"
    EXTERNALLY_MODIFIED = "externally-modified"


# Fixed stage table -- the single source of truth for stage order, canonical
# lifecycle mapping, kind, idempotence, and whether the resume planner may
# ever treat the stage as an auto-resume target. Never performed by this
# system (observed only): MERGED, ISSUE_CLOSED.
CANONICAL_STAGE_ORDER: tuple[CheckpointStage, ...] = (
    CheckpointStage.PREFLIGHT_COMPLETE,
    CheckpointStage.IMPLEMENTATION_COMPLETE,
    CheckpointStage.FOCUSED_TESTS_PASSED,
    CheckpointStage.AGGREGATE_VALIDATION_PASSED,
    CheckpointStage.COMMITTED,
    CheckpointStage.PUSHED,
    CheckpointStage.DRAFT_PR_OPENED,
    CheckpointStage.CI_PASSED,
    CheckpointStage.REVIEW_COMPLETE,
    CheckpointStage.MERGED,
    CheckpointStage.ISSUE_CLOSED,
)

STAGE_LIFECYCLE_MAP: dict[CheckpointStage, LifecycleStage] = {
    CheckpointStage.PREFLIGHT_COMPLETE: LifecycleStage.PLANNING,
    CheckpointStage.IMPLEMENTATION_COMPLETE: LifecycleStage.IMPLEMENTATION,
    CheckpointStage.FOCUSED_TESTS_PASSED: LifecycleStage.IMPLEMENTATION,
    CheckpointStage.AGGREGATE_VALIDATION_PASSED: LifecycleStage.IMPLEMENTATION,
    CheckpointStage.COMMITTED: LifecycleStage.IMPLEMENTATION,
    CheckpointStage.PUSHED: LifecycleStage.DRAFT_PR,
    CheckpointStage.DRAFT_PR_OPENED: LifecycleStage.DRAFT_PR,
    CheckpointStage.CI_PASSED: LifecycleStage.DRAFT_PR,
    CheckpointStage.REVIEW_COMPLETE: LifecycleStage.REVIEW,
    CheckpointStage.MERGED: LifecycleStage.MERGED,
    CheckpointStage.ISSUE_CLOSED: LifecycleStage.CLOSED,
}

STAGE_KIND_MAP: dict[CheckpointStage, StageKind] = {
    CheckpointStage.PREFLIGHT_COMPLETE: StageKind.READ_ONLY,
    CheckpointStage.IMPLEMENTATION_COMPLETE: StageKind.MUTATING_LOCAL,
    CheckpointStage.FOCUSED_TESTS_PASSED: StageKind.READ_ONLY,
    CheckpointStage.AGGREGATE_VALIDATION_PASSED: StageKind.READ_ONLY,
    CheckpointStage.COMMITTED: StageKind.MUTATING_LOCAL,
    CheckpointStage.PUSHED: StageKind.MUTATING_REMOTE,
    CheckpointStage.DRAFT_PR_OPENED: StageKind.MUTATING_REMOTE,
    CheckpointStage.CI_PASSED: StageKind.READ_ONLY,
    CheckpointStage.REVIEW_COMPLETE: StageKind.READ_ONLY,
    CheckpointStage.MERGED: StageKind.MUTATING_REMOTE,
    CheckpointStage.ISSUE_CLOSED: StageKind.MUTATING_REMOTE,
}

STAGE_IDEMPOTENT_MAP: dict[CheckpointStage, bool] = {
    CheckpointStage.PREFLIGHT_COMPLETE: True,
    CheckpointStage.IMPLEMENTATION_COMPLETE: False,
    CheckpointStage.FOCUSED_TESTS_PASSED: True,
    CheckpointStage.AGGREGATE_VALIDATION_PASSED: True,
    CheckpointStage.COMMITTED: False,
    CheckpointStage.PUSHED: True,
    CheckpointStage.DRAFT_PR_OPENED: False,
    CheckpointStage.CI_PASSED: True,
    CheckpointStage.REVIEW_COMPLETE: True,
    CheckpointStage.MERGED: False,
    CheckpointStage.ISSUE_CLOSED: False,
}

# Never performed by this system: MERGED and ISSUE_CLOSED are observed only
# and are never valid resume targets for automatic continuation.
STAGE_AUTO_RESUME_SAFE_MAP: dict[CheckpointStage, bool] = {
    stage: stage not in (CheckpointStage.MERGED, CheckpointStage.ISSUE_CLOSED)
    for stage in CANONICAL_STAGE_ORDER
}

# Canonical six-stage order reused verbatim from operating_mode.py's private
# _STAGE_ORDER (LifecycleStage enum order); declared here as the public
# ordering needed to compare a checkpoint's canonical stage against an
# AgentOperatingModeDecision's maximum_permitted_stage. This does not
# reinterpret authorization -- it only orders the reused enum.
LIFECYCLE_STAGE_ORDER: tuple[LifecycleStage, ...] = (
    LifecycleStage.PLANNING,
    LifecycleStage.IMPLEMENTATION,
    LifecycleStage.DRAFT_PR,
    LifecycleStage.REVIEW,
    LifecycleStage.MERGED,
    LifecycleStage.CLOSED,
)


def _exact_text(value: object, name: str, maximum: int = MAX_TEXT_BYTES) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be a built-in string")
    if not value or len(value.encode("utf-8")) > maximum or _CONTROL_RE.search(value):
        raise ValueError(f"{name} is outside bounds")
    return value


def _repository(value: object) -> str:
    text = _exact_text(value, "repository", 255)
    if not _REPOSITORY_RE.fullmatch(text):
        raise ValueError("repository is malformed")
    return text


def _positive_int(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        raise TypeError(f"{name} must be a positive built-in integer")
    return value


def _sha40(value: object, name: str) -> str:
    text = _exact_text(value, name, 40)
    if not _SHA40_RE.fullmatch(text):
        raise ValueError(f"{name} must be a lowercase 40-character SHA")
    return text


def _hex64(value: object, name: str) -> str:
    text = _exact_text(value, name, 64)
    if not _HEX64_RE.fullmatch(text):
        raise ValueError(f"{name} must be a lowercase 64-character hex digest")
    return text


def _optional_hex64(value: object, name: str) -> str | None:
    return None if value is None else _hex64(value, name)


def _token(value: object, name: str) -> str:
    text = _exact_text(value, name, MAX_TOKEN_CHARS)
    if not _TOKEN_RE.fullmatch(text):
        raise ValueError(f"{name} is malformed")
    return text


def _branch(value: object, name: str = "branch") -> str:
    text = _exact_text(value, name, 255)
    if not _BRANCH_RE.fullmatch(text) or text == "main":
        raise ValueError(f"{name} is malformed or protected")
    return text


def _sha256_id(value: object, name: str) -> str:
    text = _exact_text(value, name, MAX_TOKEN_CHARS)
    if not _SHA256_ID_RE.fullmatch(text):
        raise ValueError(f"{name} is malformed")
    return text


def _optional_sha256_id(value: object, name: str) -> str | None:
    return None if value is None else _sha256_id(value, name)


def _timestamp(value: object, name: str = "recorded_at") -> str:
    text = _exact_text(value, name, 20)
    if not _TIMESTAMP_RE.fullmatch(text):
        raise ValueError(f"{name} must use YYYY-MM-DDTHH:MM:SSZ")
    return text


def _enum(value: object, enum_type: type[Enum], name: str) -> Enum:
    if not isinstance(value, enum_type):
        raise TypeError(f"{name} must be {enum_type.__name__}")
    return value


def _canonical_strings(
    values: object,
    *,
    name: str,
    maximum: int,
    max_chars: int,
) -> tuple[str, ...]:
    if type(values) is not tuple:
        raise TypeError(f"{name} must be an exact tuple")
    if len(values) > maximum:
        raise ValueError(f"{name} exceeds its bound")
    checked = tuple(_exact_text(value, name, max_chars) for value in values)
    if len(set(checked)) != len(checked):
        raise ValueError(f"{name} contains duplicates")
    return tuple(sorted(checked))


def _evidence_hashes(values: object) -> tuple[tuple[str, str], ...]:
    if type(values) is not tuple:
        raise TypeError("evidence_hashes must be an exact tuple of (name, digest) pairs")
    if len(values) > MAX_EVIDENCE_HASHES:
        raise ValueError("evidence_hashes exceeds its bound")
    checked: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in values:
        if type(item) is not tuple or len(item) != 2:
            raise TypeError("each evidence_hashes entry must be an exact (name, digest) pair")
        name, digest = item
        name_text = _exact_text(name, "evidence_hashes name", 64)
        if not _EVIDENCE_NAME_RE.fullmatch(name_text):
            raise ValueError("evidence_hashes name is malformed")
        if name_text in seen:
            raise ValueError("evidence_hashes contains a duplicate name")
        seen.add(name_text)
        checked.append((name_text, _hex64(digest, "evidence_hashes digest")))
    return tuple(sorted(checked))


def _strict_keys(payload: dict[str, object], expected: frozenset[str], name: str) -> None:
    unknown = set(payload) - expected
    missing = expected - set(payload)
    if unknown:
        raise ValueError(f"{name} contains unknown fields: {sorted(unknown)}")
    if missing:
        raise ValueError(f"{name} is missing fields: {sorted(missing)}")


@dataclass(frozen=True, slots=True)
class ExecutionCheckpoint:
    """One immutable, content-addressed execution-checkpoint record.

    Records evidence only. It never creates authorization for the next
    stage: ``repository_implementation_authorized`` and its five sibling
    authority fields are always ``False``.
    """

    schema: Literal["agent-os.execution-checkpoint"]
    schema_version: Literal["1.0"]
    repository: str
    issue_number: int
    invocation_id: str
    execution_id: str
    branch: str
    worktree_fingerprint: str
    worktree_role: WorktreeRole
    environment_fingerprint: str
    source_sha: str
    tested_sha: str
    merge_base_sha: str
    dependency_fingerprint: str
    command_plan_id: str
    acceptance_criteria_digest: str
    governance_contract_digest: str
    lifecycle_stage: LifecycleStage
    checkpoint_stage: CheckpointStage
    stage_status: StageStatus
    evidence_hashes: tuple[tuple[str, str], ...]
    invalidation_state: InvalidationState
    lifecycle_state: LifecycleState
    recorded_at: str
    actor_id: str
    parent_checkpoint_id: str | None = None
    pre_read_digest: str | None = None
    post_write_digest: str | None = None
    mutation_intent_id: str | None = None
    authorization_snapshot_id: str | None = None
    supersession_state: str | None = None
    diagnostic_refs: tuple[str, ...] = field(default_factory=tuple)
    checkpoint_id: str = ""
    reuse_key: str = ""
    repository_implementation_authorized: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    github_writes_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    issue_closure_authorized: Literal[False] = field(default=False, init=False)
    external_writes_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if (
            self.schema != CHECKPOINT_SCHEMA_NAME
            or self.schema_version != CHECKPOINT_SCHEMA_VERSION
        ):
            raise ValueError("unsupported execution-checkpoint schema")
        _repository(self.repository)
        _positive_int(self.issue_number, "issue_number")
        _token(self.invocation_id, "invocation_id")
        _token(self.execution_id, "execution_id")
        _branch(self.branch)
        _hex64(self.worktree_fingerprint, "worktree_fingerprint")
        _enum(self.worktree_role, WorktreeRole, "worktree_role")
        _hex64(self.environment_fingerprint, "environment_fingerprint")
        _sha40(self.source_sha, "source_sha")
        _sha40(self.tested_sha, "tested_sha")
        _sha40(self.merge_base_sha, "merge_base_sha")
        _hex64(self.dependency_fingerprint, "dependency_fingerprint")
        _sha256_id(self.command_plan_id, "command_plan_id")
        _hex64(self.acceptance_criteria_digest, "acceptance_criteria_digest")
        _hex64(self.governance_contract_digest, "governance_contract_digest")
        _enum(self.lifecycle_stage, LifecycleStage, "lifecycle_stage")
        _enum(self.checkpoint_stage, CheckpointStage, "checkpoint_stage")
        _enum(self.stage_status, StageStatus, "stage_status")
        if STAGE_LIFECYCLE_MAP[CheckpointStage(self.checkpoint_stage)] != self.lifecycle_stage:
            raise ValueError("lifecycle_stage does not match checkpoint_stage's canonical mapping")
        object.__setattr__(self, "evidence_hashes", _evidence_hashes(self.evidence_hashes))
        _enum(self.invalidation_state, InvalidationState, "invalidation_state")
        _enum(self.lifecycle_state, LifecycleState, "lifecycle_state")
        _timestamp(self.recorded_at)
        _token(self.actor_id, "actor_id")

        if self.parent_checkpoint_id is not None:
            _sha256_id(self.parent_checkpoint_id, "parent_checkpoint_id")
        _optional_hex64(self.pre_read_digest, "pre_read_digest")
        _optional_hex64(self.post_write_digest, "post_write_digest")

        kind = STAGE_KIND_MAP[CheckpointStage(self.checkpoint_stage)]
        if kind is StageKind.READ_ONLY and self.mutation_intent_id is not None:
            raise ValueError("mutation_intent_id must be null for a read-only stage")

        if (
            kind is not StageKind.READ_ONLY
            and self.stage_status in (StageStatus.PASSED, StageStatus.UNCERTAIN)
            and self.mutation_intent_id is None
        ):
            raise ValueError(
                "a passed or uncertain mutating stage requires mutation_intent_id"
            )

        if (
            kind is not StageKind.READ_ONLY
            and self.stage_status is StageStatus.PASSED
            and self.pre_read_digest is None
        ):
            raise ValueError("a passed mutating stage requires pre_read_digest")

        if (
            kind is not StageKind.READ_ONLY
            and self.stage_status is StageStatus.PASSED
            and self.post_write_digest is None
        ):
            raise ValueError("a passed mutating stage requires post_write_digest")

        if self.mutation_intent_id is not None:
            _sha256_id(self.mutation_intent_id, "mutation_intent_id")

        _optional_sha256_id(self.authorization_snapshot_id, "authorization_snapshot_id")

        if self.invalidation_state is InvalidationState.SUPERSEDED:
            if self.supersession_state is None:
                raise ValueError("a superseded checkpoint requires supersession_state")
            _sha256_id(self.supersession_state, "supersession_state")
        elif self.supersession_state is not None:
            raise ValueError("supersession_state must be null unless invalidation_state is superseded")

        object.__setattr__(
            self,
            "diagnostic_refs",
            _canonical_strings(
                self.diagnostic_refs,
                name="diagnostic_refs",
                maximum=MAX_DIAGNOSTIC_REFS,
                max_chars=MAX_DIAGNOSTIC_REF_CHARS,
            ),
        )

        for name in (
            "repository_implementation_authorized",
            "execution_authorized",
            "github_writes_authorized",
            "merge_authorized",
            "issue_closure_authorized",
            "external_writes_authorized",
        ):
            if getattr(self, name) is not False:
                raise ValueError(f"{name} must be false: a checkpoint records evidence only")

        expected_checkpoint_id = compute_checkpoint_id(self._identity_payload())
        if self.checkpoint_id and self.checkpoint_id != expected_checkpoint_id:
            raise ValueError("checkpoint_id does not match checkpoint content")
        object.__setattr__(self, "checkpoint_id", expected_checkpoint_id)

        if self.parent_checkpoint_id == self.checkpoint_id:
            raise ValueError("a checkpoint cannot be its own parent")
        if self.supersession_state == self.checkpoint_id:
            raise ValueError("a checkpoint cannot supersede itself")

        expected_reuse_key = compute_reuse_key(self._reuse_payload())
        if self.reuse_key and self.reuse_key != expected_reuse_key:
            raise ValueError("reuse_key does not match checkpoint content")
        object.__setattr__(self, "reuse_key", expected_reuse_key)

        if len(canonical_json_bytes(self.to_dict())) > MAX_SERIALIZED_BYTES:
            raise ValueError("execution checkpoint exceeds its serialized bound")

    def _identity_payload(self) -> dict[str, object]:
        """Semantic identity payload: excludes observational-only fields.

        ``recorded_at``, ``actor_id``, and ``diagnostic_refs`` are provenance
        metadata only, per the checkpoint identity contract (mirrors
        ADR-0002 details-02's timestamp-semantics rule). ``checkpoint_id``
        and ``reuse_key`` are themselves excluded because they are the
        outputs being computed.
        """

        return {
            "schema": self.schema,
            "schema_version": self.schema_version,
            "parent_checkpoint_id": self.parent_checkpoint_id,
            "repository": self.repository,
            "issue_number": self.issue_number,
            "invocation_id": self.invocation_id,
            "execution_id": self.execution_id,
            "branch": self.branch,
            "worktree_fingerprint": self.worktree_fingerprint,
            "worktree_role": self.worktree_role.value,
            "environment_fingerprint": self.environment_fingerprint,
            "source_sha": self.source_sha,
            "tested_sha": self.tested_sha,
            "merge_base_sha": self.merge_base_sha,
            "dependency_fingerprint": self.dependency_fingerprint,
            "command_plan_id": self.command_plan_id,
            "acceptance_criteria_digest": self.acceptance_criteria_digest,
            "governance_contract_digest": self.governance_contract_digest,
            "lifecycle_stage": self.lifecycle_stage.value,
            "checkpoint_stage": self.checkpoint_stage.value,
            "stage_status": self.stage_status.value,
            "evidence_hashes": [list(item) for item in self.evidence_hashes],
            "pre_read_digest": self.pre_read_digest,
            "post_write_digest": self.post_write_digest,
            "mutation_intent_id": self.mutation_intent_id,
            "authorization_snapshot_id": self.authorization_snapshot_id,
            "invalidation_state": self.invalidation_state.value,
            "supersession_state": self.supersession_state,
            "lifecycle_state": self.lifecycle_state.value,
        }

    def _reuse_payload(self) -> dict[str, object]:
        """The bounded field set that determines cross-invocation reuse.

        Excludes ``invocation_id`` and ``execution_id`` deliberately: two
        separate invocations that produced identical evidence for the same
        bindings and stage must be recognized as interchangeable.
        """

        return {
            "repository": self.repository,
            "issue_number": self.issue_number,
            "branch": self.branch,
            "source_sha": self.source_sha,
            "tested_sha": self.tested_sha,
            "dependency_fingerprint": self.dependency_fingerprint,
            "environment_fingerprint": self.environment_fingerprint,
            "worktree_fingerprint": self.worktree_fingerprint,
            "command_plan_id": self.command_plan_id,
            "checkpoint_stage": self.checkpoint_stage.value,
        }

    def to_dict(self) -> dict[str, object]:
        payload = self._identity_payload()
        payload["checkpoint_id"] = self.checkpoint_id
        payload["reuse_key"] = self.reuse_key
        payload["recorded_at"] = self.recorded_at
        payload["actor_id"] = self.actor_id
        payload["diagnostic_refs"] = list(self.diagnostic_refs)
        payload["repository_implementation_authorized"] = False
        payload["execution_authorized"] = False
        payload["github_writes_authorized"] = False
        payload["merge_authorized"] = False
        payload["issue_closure_authorized"] = False
        payload["external_writes_authorized"] = False
        return payload


_CHECKPOINT_DICT_KEYS = frozenset(
    {
        "schema",
        "schema_version",
        "parent_checkpoint_id",
        "repository",
        "issue_number",
        "invocation_id",
        "execution_id",
        "branch",
        "worktree_fingerprint",
        "worktree_role",
        "environment_fingerprint",
        "source_sha",
        "tested_sha",
        "merge_base_sha",
        "dependency_fingerprint",
        "command_plan_id",
        "acceptance_criteria_digest",
        "governance_contract_digest",
        "lifecycle_stage",
        "checkpoint_stage",
        "stage_status",
        "evidence_hashes",
        "pre_read_digest",
        "post_write_digest",
        "mutation_intent_id",
        "authorization_snapshot_id",
        "invalidation_state",
        "supersession_state",
        "checkpoint_id",
        "reuse_key",
        "lifecycle_state",
        "recorded_at",
        "actor_id",
        "diagnostic_refs",
        "repository_implementation_authorized",
        "execution_authorized",
        "github_writes_authorized",
        "merge_authorized",
        "issue_closure_authorized",
        "external_writes_authorized",
    }
)


def checkpoint_from_dict(payload: object) -> ExecutionCheckpoint:
    """Reconstruct one ``ExecutionCheckpoint`` from its exact dict shape.

    Unknown or missing fields fail closed; deserialization re-runs full
    ``__post_init__`` validation, including checkpoint_id/reuse_key
    recomputation, so tampered content is rejected here rather than trusted.
    """

    if type(payload) is not dict:
        raise TypeError("checkpoint payload must be an exact dict")
    _strict_keys(payload, _CHECKPOINT_DICT_KEYS, "execution checkpoint")
    for flag in (
        "repository_implementation_authorized",
        "execution_authorized",
        "github_writes_authorized",
        "merge_authorized",
        "issue_closure_authorized",
        "external_writes_authorized",
    ):
        if payload[flag] is not False:
            raise ValueError(f"serialized checkpoint cannot claim {flag}=true")
    if type(payload["evidence_hashes"]) is not list:
        raise TypeError("evidence_hashes must be an exact JSON array")
    if type(payload["diagnostic_refs"]) is not list:
        raise TypeError("diagnostic_refs must be an exact JSON array")

    def enum_value(key: str, enum_type: type[Enum]) -> Enum:
        try:
            return enum_type(payload[key])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} is unsupported") from exc

    evidence_hashes = tuple(
        tuple(item) if type(item) is list and len(item) == 2 else item
        for item in payload["evidence_hashes"]
    )

    return ExecutionCheckpoint(
        schema=payload["schema"],
        schema_version=payload["schema_version"],
        parent_checkpoint_id=payload["parent_checkpoint_id"],
        repository=payload["repository"],
        issue_number=payload["issue_number"],
        invocation_id=payload["invocation_id"],
        execution_id=payload["execution_id"],
        branch=payload["branch"],
        worktree_fingerprint=payload["worktree_fingerprint"],
        worktree_role=enum_value("worktree_role", WorktreeRole),
        environment_fingerprint=payload["environment_fingerprint"],
        source_sha=payload["source_sha"],
        tested_sha=payload["tested_sha"],
        merge_base_sha=payload["merge_base_sha"],
        dependency_fingerprint=payload["dependency_fingerprint"],
        command_plan_id=payload["command_plan_id"],
        acceptance_criteria_digest=payload["acceptance_criteria_digest"],
        governance_contract_digest=payload["governance_contract_digest"],
        lifecycle_stage=enum_value("lifecycle_stage", LifecycleStage),
        checkpoint_stage=enum_value("checkpoint_stage", CheckpointStage),
        stage_status=enum_value("stage_status", StageStatus),
        evidence_hashes=evidence_hashes,
        pre_read_digest=payload["pre_read_digest"],
        post_write_digest=payload["post_write_digest"],
        mutation_intent_id=payload["mutation_intent_id"],
        authorization_snapshot_id=payload["authorization_snapshot_id"],
        invalidation_state=enum_value("invalidation_state", InvalidationState),
        supersession_state=payload["supersession_state"],
        lifecycle_state=enum_value("lifecycle_state", LifecycleState),
        recorded_at=payload["recorded_at"],
        actor_id=payload["actor_id"],
        diagnostic_refs=tuple(payload["diagnostic_refs"]),
        checkpoint_id=payload["checkpoint_id"],
        reuse_key=payload["reuse_key"],
    )


def serialize_checkpoint(checkpoint: ExecutionCheckpoint) -> bytes:
    """Canonical byte-exact serialization (ADR-0002 details-01b)."""

    if type(checkpoint) is not ExecutionCheckpoint:
        raise TypeError("checkpoint must be an exact ExecutionCheckpoint")
    return canonical_json_bytes(checkpoint.to_dict())


def deserialize_checkpoint(serialized: object) -> ExecutionCheckpoint:
    if type(serialized) is not bytes:
        raise TypeError("serialized checkpoint must be built-in bytes")
    if len(serialized) > MAX_SERIALIZED_BYTES:
        raise ValueError("serialized checkpoint exceeds its bound")
    import json

    try:
        payload = json.loads(serialized.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("serialized checkpoint is not valid UTF-8 JSON") from exc
    except RecursionError as exc:
        raise ValueError("serialized checkpoint is nested too deeply") from exc
    return checkpoint_from_dict(payload)
