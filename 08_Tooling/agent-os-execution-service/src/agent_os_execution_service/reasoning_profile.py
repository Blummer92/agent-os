"""Provider-neutral task reasoning profile contract for #3336 (AN-MR1).

Semantic contract owner: ChatGPT Orchestrator.
Repository implementation: GitHub Service Agent.
Validation: QA / Test Agent.

This module is deliberately a pure contract boundary. It answers one question:

    "What reasoning capability does this task require?"

independently of:

- which model or provider should execute it (model x reasoning evaluation
  evidence is #3337 territory; provider-specific mappings remain mappings,
  never canonical semantics);
- which execution surface can satisfy it (#918 executor routing owns the four
  routes and the runtime ExecutorCapability vocabulary);
- whether compute should be spent (#1419 compute admission owns the admission
  disposition);
- whether implementation is authorized (existing authority contracts own that).

Nothing here executes a provider, chooses a model, routes execution, admits
compute, grants authority, retries work, persists state, or represents hidden
chain-of-thought. The effort vocabulary describes a requestable capability
requirement, not hidden reasoning traces.

Relationship to neighboring vocabularies (reconciled, not duplicated):

- #2318 ``CodingWorkerOperation`` (inspect/implement/repair/test/refactor/
  generate-regression-test) is a work-operation vocabulary: *what kind of work*.
  This contract's ``TaskClass`` is a task-character taxonomy: *what kind of
  reasoning the task demands*. An ``implement`` operation on a trivial rename
  and an ``implement`` operation on an architecture migration share the
  operation and differ in profile. The operation is referenced by import, never
  redefined.
- #878 PR-remediation ``COMPUTE_ROUTES`` (no-model, small-model-eligible,
  high-reasoning-required, manual-decision-required) is PR-finding routing
  policy that conflates reasoning requirement, model eligibility, and human
  authority into one field. It is not universalized here; ``project_pr_compute_route``
  is an explicit one-way consumer-side projection into provider-neutral
  vocabulary, and ``planning.py`` remains the canonical owner of that policy.
- #918 ``ExecutorCapability`` names runtime capabilities (checkout,
  process-execution, ...). This contract's context requirements name
  *information* the reasoning needs; runtime tools stay #918-owned.
- #2744 records the user-visible reasoning *setting actually used* in
  conversational tests. This contract classifies what a task *requires*;
  it never records or infers provider settings.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, fields
from enum import Enum
from typing import Literal

from .coding_worker_contract import CodingWorkerOperation

REASONING_PROFILE_SCHEMA_VERSION = "1.0"
MAX_IDENTIFIER_LENGTH = 256
MAX_TEXT_BYTES = 4096
MAX_ITEMS = 256
MAX_REASONS = 32
MAX_EVIDENCE_REFS = 64

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,255}$", re.ASCII)
_TIMESTAMP_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$",
    re.ASCII,
)

__all__ = [
    "REASONING_PROFILE_SCHEMA_VERSION",
    "TaskClass",
    "ReasoningEffort",
    "ReasoningCapability",
    "ReasoningContextRequirement",
    "RiskLevel",
    "TaskReasoningProfile",
    "task_reasoning_profile_id",
    "serialize_task_reasoning_profile",
    "validate_task_reasoning_profile",
    "project_pr_compute_route",
]


class TaskClass(str, Enum):
    """Bounded task-character taxonomy: what kind of reasoning the task demands.

    Distinct from #2318 CodingWorkerOperation (what kind of work is requested).
    """

    EXTRACT = "extract"
    CLASSIFY = "classify"
    TRIAGE = "triage"
    IMPLEMENT = "implement"
    DEBUG = "debug"
    ARCHITECTURE = "architecture"
    ADVERSARIAL_REVIEW = "adversarial-review"
    DECISION_SUPPORT = "decision-support"


class ReasoningEffort(str, Enum):
    """Bounded provider-neutral reasoning requirement.

    Each level describes a requestable capability requirement, not hidden
    reasoning traces. No level names a model, provider, or setting.
    """

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    MAXIMUM = "maximum"


class ReasoningCapability(str, Enum):
    """Finite provider-neutral reasoning capabilities a task may require."""

    SINGLE_STEP_INFERENCE = "single-step-inference"
    MULTI_STEP_INFERENCE = "multi-step-inference"
    AMBIGUITY_RESOLUTION = "ambiguity-resolution"
    TRADEOFF_SYNTHESIS = "trade-off-synthesis"
    ADVERSARIAL_ANALYSIS = "adversarial-analysis"
    CAUSAL_DIAGNOSIS = "causal-diagnosis"
    ARCHITECTURAL_DESIGN = "architectural-design"


class ReasoningContextRequirement(str, Enum):
    """Finite information inputs the reasoning needs.

    These name information, never runtime tools: test execution, checkout, and
    other runtime capabilities remain #918 ExecutorCapability territory.
    """

    TASK_EVIDENCE = "task-evidence"
    REPOSITORY_CONTEXT = "repository-context"
    HISTORICAL_PRECEDENT = "historical-precedent"
    LIVE_SYSTEM_STATE = "live-system-state"


class RiskLevel(str, Enum):
    """Consequence of wrong reasoning, on the same low/medium/high scale the
    PR-remediation planner uses for finding risk."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


def _text(name: str, value: object, maximum: int = MAX_TEXT_BYTES) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be an exact string")
    if not value or len(value.encode("utf-8")) > maximum:
        raise ValueError(f"{name} is empty or exceeds its byte bound")
    return value


def _identifier(name: str, value: object) -> str:
    text = _text(name, value, MAX_IDENTIFIER_LENGTH)
    if not _IDENTIFIER_RE.fullmatch(text):
        raise ValueError(f"{name} must use bounded ASCII identifier syntax")
    return text


def _timestamp(name: str, value: object) -> str:
    text = _text(name, value, 20)
    if not _TIMESTAMP_RE.fullmatch(text):
        raise ValueError(f"{name} must be canonical UTC seconds ending in Z")
    return text


def _enum(name: str, value: object, enum: type[Enum]) -> Enum:
    if type(value) is not enum:
        raise TypeError(f"{name} must be an exact {enum.__name__}")
    return value


def _enum_tuple(
    name: str, value: object, enum: type[Enum], *, maximum: int = MAX_ITEMS
) -> tuple[Enum, ...]:
    if type(value) not in {list, tuple}:
        raise TypeError(f"{name} must be a list or tuple")
    items = tuple(value)
    if len(items) > maximum:
        raise ValueError(f"{name} exceeds its item bound")
    for item in items:
        if type(item) is not enum:
            raise TypeError(f"{name} items must be exact {enum.__name__} values")
    if len(set(items)) != len(items):
        raise ValueError(f"{name} contains duplicates")
    return items


def _text_tuple(
    name: str, value: object, *, maximum: int = MAX_ITEMS, required: bool = False
) -> tuple[str, ...]:
    if type(value) not in {list, tuple}:
        raise TypeError(f"{name} must be a list or tuple")
    items = tuple(_text(f"{name}[{index}]", item) for index, item in enumerate(value))
    if len(items) > maximum:
        raise ValueError(f"{name} exceeds its item bound")
    if required and not items:
        raise ValueError(f"{name} must not be empty")
    if len(set(items)) != len(items):
        raise ValueError(f"{name} contains duplicates")
    return items


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(domain: str, payload: object) -> str:
    material = f"{domain}:v1\0".encode("ascii") + _canonical_json(payload).encode("utf-8")
    return f"{domain}:{hashlib.sha256(material).hexdigest()}"


@dataclass(frozen=True, slots=True, kw_only=True)
class TaskReasoningProfile:
    """Bounded provider-neutral classification of one task instance.

    The profile asserts what reasoning capability the task requires. It grants
    no authority, chooses no model, routes no execution, and admits no compute:
    all authority fields are fixed false and reconstruction rejects any attempt
    to set them true.
    """

    schema_version: str
    profile_id: str = ""
    task_identity: str
    task_class: TaskClass
    work_operation_or_none: CodingWorkerOperation | None
    reasoning_effort: ReasoningEffort
    semantic_ambiguity: bool
    risk: RiskLevel
    capability_requirements: tuple[ReasoningCapability, ...]
    context_requirements: tuple[ReasoningContextRequirement, ...]
    manual_review_required: bool
    manual_review_reason_or_none: str | None
    reasons: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    profiled_at: str
    execution_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    closure_authorized: Literal[False] = field(default=False, init=False)
    external_writes_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_version != REASONING_PROFILE_SCHEMA_VERSION:
            raise ValueError("schema_version is unsupported")
        _identifier("task_identity", self.task_identity)
        _enum("task_class", self.task_class, TaskClass)
        if self.work_operation_or_none is not None:
            _enum("work_operation_or_none", self.work_operation_or_none, CodingWorkerOperation)
        _enum("reasoning_effort", self.reasoning_effort, ReasoningEffort)
        if type(self.semantic_ambiguity) is not bool:
            raise TypeError("semantic_ambiguity must be an exact boolean")
        _enum("risk", self.risk, RiskLevel)
        _enum_tuple("capability_requirements", self.capability_requirements, ReasoningCapability)
        _enum_tuple(
            "context_requirements", self.context_requirements, ReasoningContextRequirement
        )
        if type(self.manual_review_required) is not bool:
            raise TypeError("manual_review_required must be an exact boolean")
        reason = self.manual_review_reason_or_none
        if self.manual_review_required:
            if reason is None:
                raise ValueError("manual_review_required needs manual_review_reason_or_none")
            _text("manual_review_reason_or_none", reason)
        elif reason is not None:
            raise ValueError(
                "manual_review_reason_or_none must be absent without manual_review_required"
            )
        _text_tuple("reasons", self.reasons, maximum=MAX_REASONS, required=True)
        _text_tuple("evidence_refs", self.evidence_refs, maximum=MAX_EVIDENCE_REFS)
        _timestamp("profiled_at", self.profiled_at)
        if self.semantic_ambiguity and self.reasoning_effort is ReasoningEffort.NONE:
            raise ValueError(
                "semantic_ambiguity requires reasoning_effort above none: ambiguous "
                "evidence cannot be resolved with no reasoning"
            )
        computed = task_reasoning_profile_id(self)
        if self.profile_id and self.profile_id != computed:
            raise ValueError("profile_id does not match profile content")
        object.__setattr__(self, "profile_id", computed)

    def to_dict(self) -> dict[str, object]:
        return _profile_payload(self, include_id=True)

    @classmethod
    def from_dict(cls, payload: object) -> "TaskReasoningProfile":
        if type(payload) is not dict or set(payload) != {item.name for item in fields(cls)}:
            raise ValueError("reasoning profile contains unknown or missing fields")
        for name in (
            "execution_authorized",
            "merge_authorized",
            "closure_authorized",
            "external_writes_authorized",
        ):
            if payload[name] is not False:
                raise ValueError(f"{name} must be false")
        values = dict(payload)
        for name in (
            "execution_authorized",
            "merge_authorized",
            "closure_authorized",
            "external_writes_authorized",
        ):
            values.pop(name)
        values["task_class"] = TaskClass(values["task_class"])
        operation = values["work_operation_or_none"]
        values["work_operation_or_none"] = (
            CodingWorkerOperation(operation) if operation is not None else None
        )
        values["reasoning_effort"] = ReasoningEffort(values["reasoning_effort"])
        values["risk"] = RiskLevel(values["risk"])
        values["capability_requirements"] = tuple(
            ReasoningCapability(item) for item in values["capability_requirements"]
        )
        values["context_requirements"] = tuple(
            ReasoningContextRequirement(item) for item in values["context_requirements"]
        )
        values["reasons"] = tuple(values["reasons"])
        values["evidence_refs"] = tuple(values["evidence_refs"])
        return cls(**values)


def _profile_payload(profile: TaskReasoningProfile, *, include_id: bool) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": profile.schema_version,
        "task_identity": profile.task_identity,
        "task_class": profile.task_class.value,
        "work_operation_or_none": (
            profile.work_operation_or_none.value
            if profile.work_operation_or_none is not None
            else None
        ),
        "reasoning_effort": profile.reasoning_effort.value,
        "semantic_ambiguity": profile.semantic_ambiguity,
        "risk": profile.risk.value,
        "capability_requirements": tuple(
            item.value for item in profile.capability_requirements
        ),
        "context_requirements": tuple(item.value for item in profile.context_requirements),
        "manual_review_required": profile.manual_review_required,
        "manual_review_reason_or_none": profile.manual_review_reason_or_none,
        "reasons": profile.reasons,
        "evidence_refs": profile.evidence_refs,
        "profiled_at": profile.profiled_at,
        "execution_authorized": False,
        "merge_authorized": False,
        "closure_authorized": False,
        "external_writes_authorized": False,
    }
    if include_id:
        payload["profile_id"] = profile.profile_id
    return payload


def task_reasoning_profile_id(profile: TaskReasoningProfile) -> str:
    """Deterministic content digest binding the profile to its evidence basis.

    Any change to the classified content — including the evidence references —
    produces a different identity, so a stale or tampered evidence basis cannot
    silently reuse a profile identity.
    """
    return _digest("reasoning-profile", _profile_payload(profile, include_id=False))


def serialize_task_reasoning_profile(profile: TaskReasoningProfile) -> dict[str, object]:
    """Canonical wire form of a validated profile."""
    if type(profile) is not TaskReasoningProfile:
        raise TypeError("profile must be a TaskReasoningProfile")
    return _profile_payload(profile, include_id=True)


def validate_task_reasoning_profile(payload: object) -> TaskReasoningProfile:
    """Strictly validate an untrusted payload into a TaskReasoningProfile.

    Unknown fields — including any model, provider, or route names — are
    rejected. Provider dependence cannot enter through the wire format.
    """
    return TaskReasoningProfile.from_dict(payload)


_PR_COMPUTE_ROUTE_PROJECTION: dict[str, tuple[ReasoningEffort | None, bool]] = {
    # PR-remediation compute route -> (provider-neutral effort, manual review required).
    # "small-model-eligible" is a provider-selection statement; it projects to
    # LOW as a requirement statement, which is deliberately lossy: the mapping
    # never claims which model satisfies the requirement.
    # "manual-decision-required" specifies no machine-side effort: the PR policy
    # only requires a human decision, so effort is left unspecified (None) and
    # the manual-review flag carries the invariant.
    "no-model": (ReasoningEffort.NONE, False),
    "small-model-eligible": (ReasoningEffort.LOW, False),
    "high-reasoning-required": (ReasoningEffort.HIGH, False),
    "manual-decision-required": (None, True),
}


def project_pr_compute_route(compute_route: str) -> tuple[ReasoningEffort | None, bool]:
    """Project one #878 PR-remediation compute route into profile vocabulary.

    This is an explicit one-way consumer-side mapping, not a second definition
    of the PR policy: ``scripts/agent_os_pr_remediation/planning.py`` remains
    the canonical owner of the compute-route vocabulary and its derivation.
    Unknown routes fail closed.
    """
    if type(compute_route) is not str:
        raise TypeError("compute_route must be an exact string")
    try:
        return _PR_COMPUTE_ROUTE_PROJECTION[compute_route]
    except KeyError:
        raise ValueError(f"unknown PR compute route: {compute_route}") from None
