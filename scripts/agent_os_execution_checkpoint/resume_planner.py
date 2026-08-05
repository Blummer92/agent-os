"""Pure, local resume planner.

Classifies each of the 11 canonical checkpoint stages against supplied
evidence and returns one immutable, content-addressed ``ResumePlan``. A
plan is evidence, never permission: it never authorizes the next stage and
performs no I/O, subprocess, network, GitHub, Scheduler, retry, or
persistence operation of its own. All six authority fields on the plan are
always ``False``.

Authority gating is entirely delegated to the existing #863
``AgentOperatingModeDecision`` evaluator (``operating_mode.py``) -- this
module never re-derives authorization logic. The caller supplies an
already-computed decision (constructed elsewhere from live evidence); this
module only reads its ``maximum_permitted_stage`` and per-stage
``AuthorityProjection`` fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from scripts.agent_os_issue_acceptance.issue_operational_state import (
    AuthorizationState,
    LifecycleStage,
)
from scripts.agent_os_issue_acceptance.operating_mode import AgentOperatingModeDecision

from .identity import canonical_json_bytes, compute_reuse_key, compute_resume_plan_id
from .invalidation import BindingSnapshot, binding_snapshot_from_checkpoint, detect_triggers, is_stage_invalidated
from .models import (
    CANONICAL_STAGE_ORDER,
    LIFECYCLE_STAGE_ORDER,
    MAX_SERIALIZED_BYTES,
    STAGE_KIND_MAP,
    STAGE_LIFECYCLE_MAP,
    CheckpointStage,
    ExecutionCheckpoint,
    InvalidationState,
    StageKind,
    StageStatus,
    _enum,
    _exact_text,
    _positive_int,
    _repository,
    _sha256_id,
    _timestamp,
    _token,
)

RESUME_PLAN_SCHEMA_NAME = "agent-os-execution-checkpoint-resume-plan"
RESUME_PLAN_SCHEMA_VERSION = "1.0"
MAX_REASON_CHARS = 256


class StageClassification(str, Enum):
    REUSABLE = "reusable"
    RERUN_REQUIRED = "rerun-required"
    BLOCKED = "blocked"
    MANUAL_REVIEW = "manual-review"
    QUARANTINED = "quarantined"
    SUPERSEDED = "superseded"
    COMPLETE_BUT_UNAUTHORIZED_TO_CONTINUE = "complete-but-unauthorized-to-continue"


# Maps each checkpoint stage to the AgentOperatingModeDecision authority
# field that governs it. PLANNING requires no gate. DRAFT_PR-canonical
# stages (pushed, draft-pr-opened, ci-passed) share the "implementation"
# gate, matching the Safe Implementation Lane's single "explicit
# implementation instruction" authorizing tests, push, and one draft PR
# together.
CHECKPOINT_STAGE_AUTHORITY_FIELD: dict[CheckpointStage, str | None] = {
    CheckpointStage.PREFLIGHT_COMPLETE: None,
    CheckpointStage.IMPLEMENTATION_COMPLETE: "implementation_authorization",
    CheckpointStage.FOCUSED_TESTS_PASSED: "implementation_authorization",
    CheckpointStage.AGGREGATE_VALIDATION_PASSED: "implementation_authorization",
    CheckpointStage.COMMITTED: "implementation_authorization",
    CheckpointStage.PUSHED: "implementation_authorization",
    CheckpointStage.DRAFT_PR_OPENED: "implementation_authorization",
    CheckpointStage.CI_PASSED: "implementation_authorization",
    CheckpointStage.REVIEW_COMPLETE: "ready_for_review_authorization",
    CheckpointStage.MERGED: "merge_authorization",
    CheckpointStage.ISSUE_CLOSED: "closure_authorization",
}


@dataclass(frozen=True, slots=True)
class AuthorityCeiling:
    """Minimal authority summary the resume planner actually needs.

    Constructed only via ``authority_ceiling_from_decision`` from a real
    ``AgentOperatingModeDecision`` -- this type exists so the core
    classification functions stay testable without constructing a full
    decision object for every case.
    """

    maximum_permitted_stage: LifecycleStage

    def __post_init__(self) -> None:
        _enum(self.maximum_permitted_stage, LifecycleStage, "maximum_permitted_stage")


def authority_ceiling_from_decision(decision: AgentOperatingModeDecision) -> AuthorityCeiling:
    if type(decision) is not AgentOperatingModeDecision:
        raise TypeError("decision must be an exact AgentOperatingModeDecision")
    return AuthorityCeiling(maximum_permitted_stage=decision.maximum_permitted_stage)


def authority_permits_stage(stage: CheckpointStage, ceiling: AuthorityCeiling | None) -> bool:
    """Whether the supplied ceiling reaches this stage's canonical lifecycle stage.

    Fails closed: a missing ceiling (no authority evidence supplied)
    permits no stage, including planning.
    """

    if ceiling is None:
        return False
    target = STAGE_LIFECYCLE_MAP[stage]
    return LIFECYCLE_STAGE_ORDER.index(target) <= LIFECYCLE_STAGE_ORDER.index(
        ceiling.maximum_permitted_stage
    )


@dataclass(frozen=True, slots=True)
class StageDecision:
    stage: CheckpointStage
    classification: StageClassification
    evidence_checkpoint_id: str | None
    reason: str

    def __post_init__(self) -> None:
        _enum(self.stage, CheckpointStage, "stage")
        _enum(self.classification, StageClassification, "classification")
        if self.evidence_checkpoint_id is not None:
            _sha256_id(self.evidence_checkpoint_id, "evidence_checkpoint_id")
        object.__setattr__(self, "reason", _exact_text(self.reason, "reason", MAX_REASON_CHARS))

    def to_dict(self) -> dict[str, object]:
        return {
            "stage": self.stage.value,
            "classification": self.classification.value,
            "evidence_checkpoint_id": self.evidence_checkpoint_id,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class ResumePlan:
    """One immutable, content-addressed resume plan. Evidence, never permission."""

    schema_name: Literal["agent-os-execution-checkpoint-resume-plan"]
    schema_version: Literal["1.0"]
    repository: str
    issue_number: int
    execution_id: str
    stage_decisions: tuple[StageDecision, ...]
    resume_point: CheckpointStage | None
    evaluated_at: str
    plan_id: str = ""
    repository_implementation_authorized: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    github_writes_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    issue_closure_authorized: Literal[False] = field(default=False, init=False)
    external_writes_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if (
            self.schema_name != RESUME_PLAN_SCHEMA_NAME
            or self.schema_version != RESUME_PLAN_SCHEMA_VERSION
        ):
            raise ValueError("unsupported resume-plan schema")
        _repository(self.repository)
        _positive_int(self.issue_number, "issue_number")
        _token(self.execution_id, "execution_id")
        if type(self.stage_decisions) is not tuple:
            raise TypeError("stage_decisions must be an exact tuple")
        if len(self.stage_decisions) != len(CANONICAL_STAGE_ORDER):
            raise ValueError("stage_decisions must contain exactly one entry per canonical stage")
        if any(type(item) is not StageDecision for item in self.stage_decisions):
            raise TypeError("stage_decisions must contain exact StageDecision values")
        if tuple(item.stage for item in self.stage_decisions) != CANONICAL_STAGE_ORDER:
            raise ValueError("stage_decisions must be in canonical stage order, one per stage")
        if self.resume_point is not None:
            _enum(self.resume_point, CheckpointStage, "resume_point")
        _timestamp(self.evaluated_at, "evaluated_at")
        for name in (
            "repository_implementation_authorized",
            "execution_authorized",
            "github_writes_authorized",
            "merge_authorized",
            "issue_closure_authorized",
            "external_writes_authorized",
        ):
            if getattr(self, name) is not False:
                raise ValueError(f"{name} must be false: a resume plan is evidence, never permission")

        expected = compute_resume_plan_id(self._identity_payload())
        if self.plan_id and self.plan_id != expected:
            raise ValueError("plan_id does not match resume plan content")
        object.__setattr__(self, "plan_id", expected)

        if len(canonical_json_bytes(self.to_dict())) > MAX_SERIALIZED_BYTES:
            raise ValueError("resume plan exceeds its serialized bound")

    def _identity_payload(self) -> dict[str, object]:
        return {
            "schema_name": self.schema_name,
            "schema_version": self.schema_version,
            "repository": self.repository,
            "issue_number": self.issue_number,
            "execution_id": self.execution_id,
            "stage_decisions": [item.to_dict() for item in self.stage_decisions],
            "resume_point": None if self.resume_point is None else self.resume_point.value,
        }

    def to_dict(self) -> dict[str, object]:
        payload = self._identity_payload()
        payload["plan_id"] = self.plan_id
        payload["evaluated_at"] = self.evaluated_at
        payload["repository_implementation_authorized"] = False
        payload["execution_authorized"] = False
        payload["github_writes_authorized"] = False
        payload["merge_authorized"] = False
        payload["issue_closure_authorized"] = False
        payload["external_writes_authorized"] = False
        return payload


def _reuse_key_for_stage(
    current_bindings: BindingSnapshot, repository: str, issue_number: int, stage: CheckpointStage
) -> str:
    payload = {
        "repository": repository,
        "issue_number": issue_number,
        "branch": current_bindings.branch,
        "source_sha": current_bindings.source_sha,
        "tested_sha": current_bindings.tested_sha,
        "dependency_fingerprint": current_bindings.dependency_fingerprint,
        "environment_fingerprint": current_bindings.environment_fingerprint,
        "worktree_fingerprint": current_bindings.worktree_fingerprint,
        "command_plan_id": current_bindings.command_plan_id,
        "checkpoint_stage": stage.value,
    }
    return compute_reuse_key(payload)


def _classify_single_stage(
    stage: CheckpointStage,
    *,
    candidates: tuple[ExecutionCheckpoint, ...],
    current_bindings: BindingSnapshot,
    quarantined_ids: frozenset[str],
    authority_decision: AgentOperatingModeDecision | None,
) -> tuple[StageClassification, str | None, str]:
    quarantined_candidates = tuple(c for c in candidates if c.checkpoint_id in quarantined_ids)
    if quarantined_candidates:
        return (
            StageClassification.QUARANTINED,
            quarantined_candidates[0].checkpoint_id,
            "matching evidence has been quarantined",
        )

    uncertain = tuple(
        c for c in candidates if c.stage_status is StageStatus.UNCERTAIN
    )
    if uncertain:
        selected = max(
            uncertain,
            key=lambda checkpoint: (
                checkpoint.recorded_at,
                checkpoint.checkpoint_id,
            ),
        )
        return (
            StageClassification.MANUAL_REVIEW,
            selected.checkpoint_id,
            "matching outcome is uncertain; uncertain evidence is never overridden or blindly retried",
        )

    passed = tuple(c for c in candidates if c.stage_status is StageStatus.PASSED)
    # A record the store itself already marked non-current (invalidated or
    # superseded) is never reusable, regardless of whether its bindings
    # still happen to match -- a stored disposition is never silently
    # overridden by a fresh live comparison finding "no drift."
    passed_current = tuple(c for c in passed if c.invalidation_state is InvalidationState.CURRENT)
    live_valid: list[ExecutionCheckpoint] = []
    for candidate in passed_current:
        recorded = binding_snapshot_from_checkpoint(candidate)
        triggers = detect_triggers(recorded=recorded, current=current_bindings)
        if not is_stage_invalidated(stage, triggers):
            live_valid.append(candidate)

    if live_valid:
        # Equal reuse_key plus passed evidence is interchangeable across
        # invocations. Select the latest deterministically instead of
        # treating repeated successful evidence as a conflict.
        selected = max(
            live_valid,
            key=lambda checkpoint: (
                checkpoint.recorded_at,
                checkpoint.checkpoint_id,
            ),
        )
        return (
            StageClassification.REUSABLE,
            selected.checkpoint_id,
            "latest valid, non-invalidated interchangeable evidence found",
        )

    if passed and not live_valid:
        return (
            StageClassification.SUPERSEDED if any(
                c.invalidation_state.value == "superseded" for c in passed
            ) else StageClassification.RERUN_REQUIRED,
            passed[0].checkpoint_id,
            "prior evidence exists but no longer applies to current bindings",
        )

    kind = STAGE_KIND_MAP[stage]
    if kind is not StageKind.READ_ONLY and authority_decision is not None:
        field_name = CHECKPOINT_STAGE_AUTHORITY_FIELD.get(stage)
        if field_name is not None:
            projection = getattr(authority_decision, field_name).effective()
            if (
                projection.state is AuthorizationState.NOT_AUTHORIZED
                and projection.evidence_id is not None
            ):
                return (
                    StageClassification.BLOCKED,
                    None,
                    "authorization for this not-yet-performed mutation resolves to not-authorized",
                )

    return StageClassification.RERUN_REQUIRED, None, "no evidence found for this stage"


def plan_resume(
    *,
    repository: str,
    issue_number: int,
    execution_id: str,
    evaluated_at: str,
    current_bindings: BindingSnapshot,
    stored_checkpoints: tuple[ExecutionCheckpoint, ...],
    quarantined_checkpoint_ids: frozenset[str] = frozenset(),
    store_available: bool = True,
    authority_decision: AgentOperatingModeDecision | None = None,
) -> ResumePlan:
    """Build one deterministic, immutable resume plan.

    Performs no I/O of its own: ``stored_checkpoints`` and
    ``quarantined_checkpoint_ids`` must already have been loaded by
    ``store.load_checkpoints``, and ``store_available`` must reflect
    ``store.store_is_available`` (or an equivalent caller-side check).
    Never blindly retries: a stage with any matching uncertain outcome
    always resolves to ``manual-review``, never a fresh classification of
    ``reusable`` or a silent rerun.
    """

    _repository(repository)
    _positive_int(issue_number, "issue_number")
    _token(execution_id, "execution_id")
    _timestamp(evaluated_at, "evaluated_at")
    if type(current_bindings) is not BindingSnapshot:
        raise TypeError("current_bindings must be an exact BindingSnapshot")
    if type(stored_checkpoints) is not tuple or any(
        type(item) is not ExecutionCheckpoint for item in stored_checkpoints
    ):
        raise TypeError("stored_checkpoints must be an exact tuple of ExecutionCheckpoint")
    if authority_decision is not None and type(authority_decision) is not AgentOperatingModeDecision:
        raise TypeError("authority_decision must be an exact AgentOperatingModeDecision or None")

    decisions: dict[CheckpointStage, StageDecision] = {}
    resume_point: CheckpointStage | None = None

    if not store_available:
        for stage in CANONICAL_STAGE_ORDER:
            classification = (
                StageClassification.RERUN_REQUIRED
                if STAGE_KIND_MAP[stage] is StageKind.READ_ONLY
                else StageClassification.MANUAL_REVIEW
            )
            decisions[stage] = StageDecision(
                stage=stage,
                classification=classification,
                evidence_checkpoint_id=None,
                reason="checkpoint store is unavailable",
            )
        resume_point = CANONICAL_STAGE_ORDER[0]
    else:
        settled = True
        for stage in CANONICAL_STAGE_ORDER:
            if not settled:
                decisions[stage] = StageDecision(
                    stage=stage,
                    classification=StageClassification.RERUN_REQUIRED,
                    evidence_checkpoint_id=None,
                    reason="an earlier stage in this execution is not yet settled",
                )
                continue

            target_reuse_key = _reuse_key_for_stage(current_bindings, repository, issue_number, stage)
            candidates = tuple(
                cp
                for cp in stored_checkpoints
                if cp.checkpoint_stage is stage and cp.reuse_key == target_reuse_key
            )
            classification, evidence_id, reason = _classify_single_stage(
                stage,
                candidates=candidates,
                current_bindings=current_bindings,
                quarantined_ids=quarantined_checkpoint_ids,
                authority_decision=authority_decision,
            )
            decisions[stage] = StageDecision(
                stage=stage,
                classification=classification,
                evidence_checkpoint_id=evidence_id,
                reason=reason,
            )
            if classification is not StageClassification.REUSABLE:
                settled = False
                resume_point = stage

        ceiling = (
            authority_ceiling_from_decision(authority_decision)
            if authority_decision is not None
            else None
        )
        stage_list = list(CANONICAL_STAGE_ORDER)
        for index, stage in enumerate(stage_list):
            if decisions[stage].classification is not StageClassification.REUSABLE:
                continue
            if index + 1 >= len(stage_list):
                continue
            next_stage = stage_list[index + 1]
            next_decision = decisions[next_stage]
            if next_decision.classification is StageClassification.RERUN_REQUIRED and not authority_permits_stage(
                next_stage, ceiling
            ):
                decisions[next_stage] = StageDecision(
                    stage=next_stage,
                    classification=StageClassification.COMPLETE_BUT_UNAUTHORIZED_TO_CONTINUE,
                    evidence_checkpoint_id=None,
                    reason="prior stage is complete, but authority does not reach this stage",
                )
                resume_point = next_stage

    stage_decisions = tuple(decisions[stage] for stage in CANONICAL_STAGE_ORDER)
    all_reusable = all(item.classification is StageClassification.REUSABLE for item in stage_decisions)

    return ResumePlan(
        schema_name=RESUME_PLAN_SCHEMA_NAME,
        schema_version=RESUME_PLAN_SCHEMA_VERSION,
        repository=repository,
        issue_number=issue_number,
        execution_id=execution_id,
        stage_decisions=stage_decisions,
        resume_point=None if all_reusable else resume_point,
        evaluated_at=evaluated_at,
    )
