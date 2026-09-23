"""Pure-local high-reasoning proposal generation and deterministic verification."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Literal, Protocol

from .models import canonical_json, deterministic_id
from .planning import COMPUTE_ROUTES

REQUEST_SCHEMA_VERSION = "1.0"
PROPOSAL_SCHEMA_VERSION = "1.0"
MAX_ITEMS = 128
MAX_TEXT_BYTES = 4096
MAX_PATH_BYTES = 1024
MAX_RESPONSE_BYTES = 128 * 1024

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_SHELLISH_RE = re.compile(r"[`;&|><$]")

EXISTING_EXECUTOR_ROUTES = frozenset(
    {"chatgpt_connector", "governed_runner", "external_fallback", "human_decision"}
)
AUTHORITY_FIELDS = (
    "execution_authorized",
    "source_edit_authorized",
    "github_write_authorized",
    "validation_authorized",
    "ready_for_review_authorized",
    "merge_authorized",
    "issue_closure_authorized",
    "workflow_authorized",
    "credential_authorized",
    "production_authorized",
    "external_write_authorized",
    "side_effects_performed",
)

REASON_CODES = frozenset(
    {
        "route.not-high-reasoning",
        "authorization.missing-evidence",
        "authorization.not-authorized",
        "authorization.stale",
        "authorization.ambiguous",
        "source.stale",
        "human-evidence.conflicting",
        "provider.unavailable",
        "provider.failure",
        "proposal.malformed",
        "proposal.oversized",
        "proposal.unsupported-schema",
        "proposal.binding-mismatch",
        "proposal.type-mismatch",
        "proposal.scope-expansion",
        "proposal.forbidden-surface",
        "proposal.unknown-executor-route",
        "proposal.invented-authority",
        "proposal.executable-content",
        "proposal.required-validation-missing",
        "proposal.constraint-missing",
        "proposal.repair-evidence-mismatch",
        "proposal.current",
        "proposal.stale",
    }
)


class ProposalType(str, Enum):
    EXECUTION = "execution"
    REPAIR = "repair"


class ProposalOutcome(str, Enum):
    ACCEPTED = "accepted"
    MANUAL_REVIEW = "manual-review"
    NEEDS_DECISION = "needs-decision"
    REJECTED = "rejected"


class PlanAction(str, Enum):
    INSPECT = "inspect"
    EDIT = "edit"
    VALIDATE = "validate"
    DOCUMENT = "document"
    HANDOFF = "handoff"


class ProposalAdapter(Protocol):
    def propose(self, request_payload: Mapping[str, Any]) -> Mapping[str, Any]: ...


class ProposalProviderUnavailable(RuntimeError):
    pass


class _ProposalValidationError(ValueError):
    def __init__(self, reason_code: str, message: str):
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class ProposalRequest:
    schema_version: str
    repository: str
    issue_number: int | None
    pr_number: int | None
    invocation_id: str | None
    source_sha: str
    observed_source_sha: str
    base_branch: str | None
    base_sha: str | None
    objective: str
    non_goals: tuple[str, ...]
    allowed_paths: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    required_validations: tuple[str, ...]
    required_prohibited_changes: tuple[str, ...]
    blockers: tuple[str, ...]
    changed_paths: tuple[str, ...]
    compute_route: str
    authorization_state: str
    authorization_fingerprint: str | None
    proposal_type: ProposalType
    contract_versions: tuple[str, ...]
    source_fingerprints: tuple[str, ...]
    normalized_evidence_refs: tuple[str, ...]
    provider_capability_requirements: tuple[str, ...]
    human_evidence_state: str = "clear"

    def __post_init__(self) -> None:
        if self.schema_version != REQUEST_SCHEMA_VERSION:
            raise ValueError("unsupported request schema version")
        _require_text(self.repository, "repository")
        _positive_optional_int(self.issue_number, "issue_number")
        _positive_optional_int(self.pr_number, "pr_number")
        if self.invocation_id is not None:
            _require_text(self.invocation_id, "invocation_id")
        if self.issue_number is None and self.pr_number is None and self.invocation_id is None:
            raise ValueError("at least one issue, PR, or invocation identity is required")
        _require_sha40(self.source_sha, "source_sha")
        _require_sha40(self.observed_source_sha, "observed_source_sha")
        if self.base_branch is not None:
            _require_text(self.base_branch, "base_branch")
        if self.base_sha is not None:
            _require_sha40(self.base_sha, "base_sha")
        _require_text(self.objective, "objective")
        object.__setattr__(self, "non_goals", _text_tuple(self.non_goals, "non_goals"))
        object.__setattr__(self, "allowed_paths", _path_tuple(self.allowed_paths, "allowed_paths", allow_prefix=True))
        object.__setattr__(self, "forbidden_paths", _path_tuple(self.forbidden_paths, "forbidden_paths", allow_prefix=True))
        object.__setattr__(self, "required_validations", _text_tuple(self.required_validations, "required_validations"))
        object.__setattr__(self, "required_prohibited_changes", _text_tuple(self.required_prohibited_changes, "required_prohibited_changes"))
        object.__setattr__(self, "blockers", _text_tuple(self.blockers, "blockers"))
        object.__setattr__(self, "changed_paths", _path_tuple(self.changed_paths, "changed_paths"))
        if not self.allowed_paths or not self.required_validations or not self.required_prohibited_changes:
            raise ValueError("scope, validation, and prohibited-change evidence must not be empty")
        if self.compute_route not in COMPUTE_ROUTES:
            raise ValueError("compute_route is unsupported")
        if self.authorization_state not in {"authorized", "not-authorized", "stale", "ambiguous", "missing"}:
            raise ValueError("authorization_state is unsupported")
        if self.authorization_fingerprint is not None:
            _require_sha256(self.authorization_fingerprint, "authorization_fingerprint")
        if not isinstance(self.proposal_type, ProposalType):
            raise TypeError("proposal_type must be ProposalType")
        object.__setattr__(self, "contract_versions", _text_tuple(self.contract_versions, "contract_versions"))
        object.__setattr__(self, "source_fingerprints", _sha256_tuple(self.source_fingerprints, "source_fingerprints"))
        object.__setattr__(self, "normalized_evidence_refs", _text_tuple(self.normalized_evidence_refs, "normalized_evidence_refs"))
        object.__setattr__(self, "provider_capability_requirements", _text_tuple(self.provider_capability_requirements, "provider_capability_requirements"))
        if not self.contract_versions or not self.source_fingerprints:
            raise ValueError("contract_versions and source_fingerprints must not be empty")
        if self.human_evidence_state not in {"clear", "conflicting"}:
            raise ValueError("human_evidence_state is unsupported")

    @property
    def request_fingerprint(self) -> str:
        return deterministic_id(self.to_payload())

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "repository": self.repository,
            "issue_number": self.issue_number,
            "pr_number": self.pr_number,
            "invocation_id": self.invocation_id,
            "source_sha": self.source_sha,
            "observed_source_sha": self.observed_source_sha,
            "base_branch": self.base_branch,
            "base_sha": self.base_sha,
            "objective": self.objective,
            "non_goals": list(self.non_goals),
            "allowed_paths": list(self.allowed_paths),
            "forbidden_paths": list(self.forbidden_paths),
            "required_validations": list(self.required_validations),
            "required_prohibited_changes": list(self.required_prohibited_changes),
            "blockers": list(self.blockers),
            "changed_paths": list(self.changed_paths),
            "compute_route": self.compute_route,
            "authorization_state": self.authorization_state,
            "authorization_fingerprint": self.authorization_fingerprint,
            "proposal_type": self.proposal_type.value,
            "contract_versions": list(self.contract_versions),
            "source_fingerprints": list(self.source_fingerprints),
            "normalized_evidence_refs": list(self.normalized_evidence_refs),
            "provider_capability_requirements": list(self.provider_capability_requirements),
            "human_evidence_state": self.human_evidence_state,
        }


@dataclass(frozen=True, slots=True)
class PlanStep:
    action: PlanAction
    summary: str
    target_paths: tuple[str, ...]
    validation_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FrozenProposalPlan:
    schema_version: str
    plan_id: str
    plan_type: ProposalType
    request_fingerprint: str
    repository: str
    issue_number: int | None
    pr_number: int | None
    source_sha: str
    base_branch: str | None
    base_sha: str | None
    objective: str
    contract_versions: tuple[str, ...]
    source_fingerprints: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    non_goals: tuple[str, ...]
    steps: tuple[PlanStep, ...]
    proposed_files: tuple[str, ...]
    prohibited_changes: tuple[str, ...]
    validations: tuple[str, ...]
    blockers: tuple[str, ...]
    rollback_concept: str
    executor_route_requirements: tuple[str, ...]
    insufficiency_reason: str
    uncertainty: tuple[str, ...]
    expiry_condition: str
    invalidation_conditions: tuple[str, ...]
    provider_identity: str
    model_identity: str
    execution_authorized: Literal[False] = field(default=False, init=False)
    source_edit_authorized: Literal[False] = field(default=False, init=False)
    github_write_authorized: Literal[False] = field(default=False, init=False)
    validation_authorized: Literal[False] = field(default=False, init=False)
    ready_for_review_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    issue_closure_authorized: Literal[False] = field(default=False, init=False)
    workflow_authorized: Literal[False] = field(default=False, init=False)
    credential_authorized: Literal[False] = field(default=False, init=False)
    production_authorized: Literal[False] = field(default=False, init=False)
    external_write_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    @property
    def proposal_fingerprint(self) -> str:
        return self.plan_id.split(":", 1)[1]

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["plan_type"] = self.plan_type.value
        payload["steps"] = [
            {
                "action": step.action.value,
                "summary": step.summary,
                "target_paths": list(step.target_paths),
                "validation_refs": list(step.validation_refs),
            }
            for step in self.steps
        ]
        for name in (
            "contract_versions", "source_fingerprints", "evidence_refs", "non_goals",
            "proposed_files", "prohibited_changes", "validations", "blockers",
            "executor_route_requirements", "uncertainty", "invalidation_conditions",
        ):
            payload[name] = list(getattr(self, name))
        return payload


@dataclass(frozen=True, slots=True)
class ProposalResult:
    outcome: ProposalOutcome
    reason_codes: tuple[str, ...]
    plan: FrozenProposalPlan | None
    adapter_invoked: bool

    def __post_init__(self) -> None:
        if set(self.reason_codes) - REASON_CODES:
            raise ValueError("unknown reason code")
        if (self.outcome is ProposalOutcome.ACCEPTED) != (self.plan is not None):
            raise ValueError("usable plan presence does not match outcome")


@dataclass(frozen=True, slots=True)
class ProposalCurrentnessResult:
    current: bool
    reason_codes: tuple[str, ...]


def propose_high_reasoning_plan(request: ProposalRequest, adapter: ProposalAdapter) -> ProposalResult:
    if not isinstance(request, ProposalRequest):
        raise TypeError("request must be ProposalRequest")
    if request.compute_route != "high-reasoning-required":
        return ProposalResult(ProposalOutcome.NEEDS_DECISION, ("route.not-high-reasoning",), None, False)
    if request.source_sha != request.observed_source_sha:
        return ProposalResult(ProposalOutcome.MANUAL_REVIEW, ("source.stale",), None, False)
    if request.human_evidence_state == "conflicting":
        return ProposalResult(ProposalOutcome.MANUAL_REVIEW, ("human-evidence.conflicting",), None, False)
    if request.authorization_state != "authorized" or request.authorization_fingerprint is None:
        reason = {
            "missing": "authorization.missing-evidence",
            "not-authorized": "authorization.not-authorized",
            "stale": "authorization.stale",
            "ambiguous": "authorization.ambiguous",
            "authorized": "authorization.missing-evidence",
        }[request.authorization_state]
        return ProposalResult(ProposalOutcome.MANUAL_REVIEW, (reason,), None, False)

    payload = dict(request.to_payload())
    payload["request_fingerprint"] = request.request_fingerprint
    try:
        response = adapter.propose(payload)
    except ProposalProviderUnavailable:
        return ProposalResult(ProposalOutcome.NEEDS_DECISION, ("provider.unavailable",), None, True)
    except Exception:
        return ProposalResult(ProposalOutcome.NEEDS_DECISION, ("provider.failure",), None, True)

    try:
        plan = _verify_response(request, response)
    except _ProposalValidationError as exc:
        return ProposalResult(ProposalOutcome.REJECTED, (exc.reason_code,), None, True)
    return ProposalResult(ProposalOutcome.ACCEPTED, (), plan, True)


def evaluate_plan_currentness(plan: FrozenProposalPlan, current_request: ProposalRequest) -> ProposalCurrentnessResult:
    if not isinstance(plan, FrozenProposalPlan):
        raise TypeError("plan must be FrozenProposalPlan")
    if not isinstance(current_request, ProposalRequest):
        raise TypeError("current_request must be ProposalRequest")
    current = (
        plan.request_fingerprint == current_request.request_fingerprint
        and plan.source_sha == current_request.source_sha
        and current_request.source_sha == current_request.observed_source_sha
    )
    return ProposalCurrentnessResult(current, ("proposal.current",) if current else ("proposal.stale",))


def serialize_frozen_proposal(plan: FrozenProposalPlan) -> bytes:
    if not isinstance(plan, FrozenProposalPlan):
        raise TypeError("plan must be FrozenProposalPlan")
    return canonical_json(plan.to_payload()).encode("utf-8")


def _verify_response(request: ProposalRequest, response: Mapping[str, Any]) -> FrozenProposalPlan:
    if not isinstance(response, Mapping):
        raise _ProposalValidationError("proposal.malformed", "response must be a mapping")
    raw = dict(response)
    try:
        encoded = canonical_json(raw).encode("utf-8")
    except (TypeError, ValueError):
        raise _ProposalValidationError("proposal.malformed", "response is not canonical JSON") from None
    if len(encoded) > MAX_RESPONSE_BYTES:
        raise _ProposalValidationError("proposal.oversized", "response exceeds size bound")

    required = {
        "schema_version", "plan_type", "request_fingerprint", "provider_identity",
        "model_identity", "evidence_refs", "non_goals", "steps", "proposed_files",
        "prohibited_changes", "validations", "blockers", "rollback_concept",
        "executor_route_requirements", "insufficiency_reason", "uncertainty",
        "expiry_condition", "invalidation_conditions", *AUTHORITY_FIELDS,
    }
    if set(raw) != required:
        raise _ProposalValidationError("proposal.malformed", "response keys are not exact")
    if raw["schema_version"] != PROPOSAL_SCHEMA_VERSION:
        raise _ProposalValidationError("proposal.unsupported-schema", "unsupported proposal schema")
    if raw["plan_type"] != request.proposal_type.value:
        raise _ProposalValidationError("proposal.type-mismatch", "plan type mismatch")
    if raw["request_fingerprint"] != request.request_fingerprint:
        raise _ProposalValidationError("proposal.binding-mismatch", "request fingerprint mismatch")
    for name in AUTHORITY_FIELDS:
        if raw[name] is not False:
            raise _ProposalValidationError("proposal.invented-authority", f"{name} must remain false")

    provider_identity = _response_text(raw["provider_identity"], "provider_identity")
    model_identity = _response_text(raw["model_identity"], "model_identity")
    evidence_refs = _response_text_tuple(raw["evidence_refs"], "evidence_refs")
    if request.proposal_type is ProposalType.REPAIR:
        if not request.normalized_evidence_refs or evidence_refs != request.normalized_evidence_refs:
            raise _ProposalValidationError("proposal.repair-evidence-mismatch", "repair evidence mismatch")
    elif not set(evidence_refs).issubset(set(request.normalized_evidence_refs)):
        raise _ProposalValidationError("proposal.binding-mismatch", "proposal invents evidence")

    non_goals = _response_text_tuple(raw["non_goals"], "non_goals")
    if not set(request.non_goals).issubset(set(non_goals)):
        raise _ProposalValidationError("proposal.constraint-missing", "frozen non-goal omitted")
    proposed_files = _response_paths(raw["proposed_files"], "proposed_files")
    for path in proposed_files:
        if not _path_in_allowlist(path, request.allowed_paths):
            raise _ProposalValidationError("proposal.scope-expansion", f"outside allowed scope: {path}")
        if _path_forbidden(path, request.forbidden_paths):
            raise _ProposalValidationError("proposal.forbidden-surface", f"forbidden path: {path}")

    validations = _response_text_tuple(raw["validations"], "validations")
    if not set(request.required_validations).issubset(set(validations)):
        raise _ProposalValidationError("proposal.required-validation-missing", "required validation omitted")
    prohibited_changes = _response_text_tuple(raw["prohibited_changes"], "prohibited_changes")
    if not set(request.required_prohibited_changes).issubset(set(prohibited_changes)):
        raise _ProposalValidationError("proposal.constraint-missing", "required prohibited change omitted")
    blockers = _response_text_tuple(raw["blockers"], "blockers")
    if not set(request.blockers).issubset(set(blockers)):
        raise _ProposalValidationError("proposal.constraint-missing", "known blocker omitted")

    routes = _response_text_tuple(raw["executor_route_requirements"], "executor_route_requirements")
    if not routes or not set(routes).issubset(EXISTING_EXECUTOR_ROUTES):
        raise _ProposalValidationError("proposal.unknown-executor-route", "unknown executor route")
    rollback_concept = _response_text(raw["rollback_concept"], "rollback_concept")
    insufficiency_reason = _response_text(raw["insufficiency_reason"], "insufficiency_reason")
    uncertainty = _response_text_tuple(raw["uncertainty"], "uncertainty")
    expiry_condition = _response_text(raw["expiry_condition"], "expiry_condition")
    invalidation_conditions = _response_text_tuple(raw["invalidation_conditions"], "invalidation_conditions")
    if not invalidation_conditions:
        raise _ProposalValidationError("proposal.constraint-missing", "invalidation conditions required")

    steps_raw = raw["steps"]
    if type(steps_raw) is not list or not steps_raw or len(steps_raw) > MAX_ITEMS:
        raise _ProposalValidationError("proposal.malformed", "steps must be a bounded non-empty list")
    steps: list[PlanStep] = []
    for index, item in enumerate(steps_raw):
        if type(item) is not dict or set(item) != {"action", "summary", "target_paths", "validation_refs"}:
            raise _ProposalValidationError("proposal.malformed", f"step {index} keys are not exact")
        try:
            action = PlanAction(item["action"])
        except (TypeError, ValueError):
            raise _ProposalValidationError("proposal.executable-content", "unsupported step action") from None
        summary = _response_text(item["summary"], f"steps[{index}].summary")
        if _SHELLISH_RE.search(summary):
            raise _ProposalValidationError("proposal.executable-content", "shell-like step content")
        target_paths = _response_paths(item["target_paths"], f"steps[{index}].target_paths")
        if not set(target_paths).issubset(set(proposed_files)):
            raise _ProposalValidationError("proposal.scope-expansion", "step targets undeclared file")
        validation_refs = _response_text_tuple(item["validation_refs"], f"steps[{index}].validation_refs")
        if not set(validation_refs).issubset(set(validations)):
            raise _ProposalValidationError("proposal.required-validation-missing", "step references undeclared validation")
        steps.append(PlanStep(action, summary, target_paths, validation_refs))

    semantic = {
        "schema_version": PROPOSAL_SCHEMA_VERSION,
        "plan_type": request.proposal_type.value,
        "request_fingerprint": request.request_fingerprint,
        "repository": request.repository,
        "issue_number": request.issue_number,
        "pr_number": request.pr_number,
        "source_sha": request.source_sha,
        "base_branch": request.base_branch,
        "base_sha": request.base_sha,
        "objective": request.objective,
        "contract_versions": list(request.contract_versions),
        "source_fingerprints": list(request.source_fingerprints),
        "evidence_refs": list(evidence_refs),
        "non_goals": list(non_goals),
        "steps": [{"action": s.action.value, "summary": s.summary, "target_paths": list(s.target_paths), "validation_refs": list(s.validation_refs)} for s in steps],
        "proposed_files": list(proposed_files),
        "prohibited_changes": list(prohibited_changes),
        "validations": list(validations),
        "blockers": list(blockers),
        "rollback_concept": rollback_concept,
        "executor_route_requirements": list(routes),
        "insufficiency_reason": insufficiency_reason,
        "uncertainty": list(uncertainty),
        "expiry_condition": expiry_condition,
        "invalidation_conditions": list(invalidation_conditions),
        "provider_identity": provider_identity,
        "model_identity": model_identity,
        **{name: False for name in AUTHORITY_FIELDS},
    }
    return FrozenProposalPlan(
        schema_version=PROPOSAL_SCHEMA_VERSION,
        plan_id=f"high-reasoning-proposal:{deterministic_id(semantic)}",
        plan_type=request.proposal_type,
        request_fingerprint=request.request_fingerprint,
        repository=request.repository,
        issue_number=request.issue_number,
        pr_number=request.pr_number,
        source_sha=request.source_sha,
        base_branch=request.base_branch,
        base_sha=request.base_sha,
        objective=request.objective,
        contract_versions=request.contract_versions,
        source_fingerprints=request.source_fingerprints,
        evidence_refs=evidence_refs,
        non_goals=non_goals,
        steps=tuple(steps),
        proposed_files=proposed_files,
        prohibited_changes=prohibited_changes,
        validations=validations,
        blockers=blockers,
        rollback_concept=rollback_concept,
        executor_route_requirements=routes,
        insufficiency_reason=insufficiency_reason,
        uncertainty=uncertainty,
        expiry_condition=expiry_condition,
        invalidation_conditions=invalidation_conditions,
        provider_identity=provider_identity,
        model_identity=model_identity,
    )


def _positive_optional_int(value: object, name: str) -> None:
    if value is not None and (type(value) is not int or value <= 0):
        raise ValueError(f"{name} must be a positive integer when supplied")


def _require_text(value: object, name: str, maximum: int = MAX_TEXT_BYTES) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be a non-empty built-in string")
    if len(value.encode("utf-8")) > maximum or _CONTROL_RE.search(value):
        raise ValueError(f"{name} is outside bounds")
    return value


def _require_sha40(value: object, name: str) -> str:
    text = _require_text(value, name)
    if not _SHA40_RE.fullmatch(text):
        raise ValueError(f"{name} must be a lowercase 40-character SHA")
    return text


def _require_sha256(value: object, name: str) -> str:
    text = _require_text(value, name)
    if not _SHA256_RE.fullmatch(text):
        raise ValueError(f"{name} must be a lowercase SHA-256 fingerprint")
    return text


def _text_tuple(values: object, name: str) -> tuple[str, ...]:
    if type(values) is not tuple or len(values) > MAX_ITEMS:
        raise ValueError(f"{name} must be a bounded exact tuple")
    checked = tuple(_require_text(item, name) for item in values)
    if len(set(checked)) != len(checked):
        raise ValueError(f"{name} contains duplicates")
    return tuple(sorted(checked))


def _sha256_tuple(values: object, name: str) -> tuple[str, ...]:
    if type(values) is not tuple or len(values) > MAX_ITEMS:
        raise ValueError(f"{name} must be a bounded exact tuple")
    checked = tuple(_require_sha256(item, name) for item in values)
    if len(set(checked)) != len(checked):
        raise ValueError(f"{name} contains duplicates")
    return tuple(sorted(checked))


def _path_tuple(values: object, name: str, *, allow_prefix: bool = False) -> tuple[str, ...]:
    if type(values) is not tuple or len(values) > MAX_ITEMS:
        raise ValueError(f"{name} must be a bounded exact tuple")
    checked = tuple(_require_path(item, name, allow_prefix=allow_prefix) for item in values)
    if len(set(checked)) != len(checked):
        raise ValueError(f"{name} contains duplicates")
    return tuple(sorted(checked))


def _require_path(value: object, name: str, *, allow_prefix: bool = False) -> str:
    text = _require_text(value, name, MAX_PATH_BYTES)
    if text.startswith("/") or "\\" in text or ".." in text.split("/"):
        raise ValueError(f"{name} contains an unsafe path")
    if text.endswith("/") and not allow_prefix:
        raise ValueError(f"{name} must identify a file path")
    return text


def _response_text(value: object, name: str) -> str:
    try:
        return _require_text(value, name)
    except ValueError as exc:
        raise _ProposalValidationError("proposal.malformed", str(exc)) from None


def _response_text_tuple(value: object, name: str) -> tuple[str, ...]:
    if type(value) is not list or len(value) > MAX_ITEMS:
        raise _ProposalValidationError("proposal.malformed", f"{name} must be a bounded list")
    try:
        checked = tuple(_require_text(item, name) for item in value)
    except ValueError as exc:
        raise _ProposalValidationError("proposal.malformed", str(exc)) from None
    if len(set(checked)) != len(checked):
        raise _ProposalValidationError("proposal.malformed", f"{name} contains duplicates")
    return tuple(sorted(checked))


def _response_paths(value: object, name: str) -> tuple[str, ...]:
    if type(value) is not list or len(value) > MAX_ITEMS:
        raise _ProposalValidationError("proposal.malformed", f"{name} must be a bounded list")
    try:
        checked = tuple(_require_path(item, name) for item in value)
    except ValueError as exc:
        raise _ProposalValidationError("proposal.malformed", str(exc)) from None
    if len(set(checked)) != len(checked):
        raise _ProposalValidationError("proposal.malformed", f"{name} contains duplicates")
    return tuple(sorted(checked))


def _path_in_allowlist(path: str, allowed_paths: tuple[str, ...]) -> bool:
    return any(path == allowed or (allowed.endswith("/") and path.startswith(allowed)) for allowed in allowed_paths)


def _path_forbidden(path: str, forbidden_paths: tuple[str, ...]) -> bool:
    return any(path == forbidden or (forbidden.endswith("/") and path.startswith(forbidden)) for forbidden in forbidden_paths)
