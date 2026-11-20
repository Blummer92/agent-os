"""Connected AI Navigation pathway (request -> context -> capabilities -> selection
-> routing -> governance -> execution -> evidence).

This module is a thin caller/callee seam. It owns no governance, routing,
admission, runtime, ledger, or lesson logic. Every stage delegates to the
existing owner:

- context/lessons:   ``issue_start_lesson_preflight.activate_issue_start_lesson_preflight`` (CKR6)
- capabilities:      ``reusable_capability_registry`` over ``04_Registry/reusable-capabilities.yml``
- agent selection:   ``04_Registry/agent-inheritance-registry.md`` + ``legacy-agent-alias-registry.md``
- routing:           ``executor_routing.select_executor_route``
- admission + host:  ``execution_composition.compose_and_run_validation`` (identity,
                     authorization, command-plan and runtime-binding checks, then the
                     canonical Workflow Scheduler runtime exactly once)
- evidence:          ``evidence_ledger.EvidenceLedger`` (hash-chained selection /
                     execution / completion entries)

Fail-closed: every refusal carries a ``failure_class`` that keeps policy denial,
missing/invalid evidence, unavailable infrastructure, and execution failure
distinct. The pathway never authorizes anything itself; authorization is
caller-supplied ``ExecutionAuthorizationEvidence`` that only the existing
admission re-checks. Execution receipts are untrusted evidence: they are never
written to, or promoted into, the lesson catalog (no CKR6 write, no CKR7
refinement, ``lesson_candidate_authorized`` is always ``False``).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping

from .authorization import ExecutionAuthorizationEvidence
from .command_planning import ValidationCommandPlan, validation_command_plan_id
from .execution_authorization_source import (
    ExecutionAuthorizationSourceReason,
    ExecutionAuthorizationSourceStatus,
    ExecutionAuthorizationSourceTransport,
    reacquire_execution_authorization,
)
from .evidence_ledger import EvidenceLedger, NavigationDecisionType, hash_decision_inputs
from .execution_composition import (
    ExecutionCompositionResult,
    ExecutionCompositionStatus,
    compose_and_run_validation,
)
from .executor_routing import (
    ExecutorCapability,
    ExecutorRoute,
    select_executor_route,
)
from .issue_start_lesson_preflight import activate_issue_start_lesson_preflight
from .command_planning import reconstruct_validation_command_plan
from .models import ExecutionServiceRequest, reconstruct_execution_service_request
from .request_validation import validate_execution_service_request

AI_NAVIGATION_SCHEMA_VERSION = "1.0"
ACTOR = "ai-navigation-pathway"
VALIDATION_ONLY = "validation-only"

__all__ = [
    "AI_NAVIGATION_SCHEMA_VERSION",
    "FailureClass",
    "NavigationStatus",
    "NavigationWorkRequest",
    "NavigationExecutionHost",
    "NavigationRoutingEvidence",
    "NavigationOutcome",
    "FileReceiptSink",
    "load_canonical_agents",
    "resolve_agent",
    "select_agent",
    "run_ai_navigation",
    "host_clock_evaluated_at",
    "trusted_execution_authorization_source",
    "AuthorizationSourceUnavailable",
    "run_ai_navigation_payload",
]


class NavigationStatus(str, Enum):
    COMPLETED = "completed"
    REQUEST_REJECTED = "request-rejected"
    UNAUTHORIZED_ENTRYPOINT = "unauthorized-entrypoint"
    LESSON_PREFLIGHT_BLOCKED = "lesson-preflight-blocked"
    INVALID_CAPABILITY = "invalid-capability"
    NO_ELIGIBLE_AGENT = "no-eligible-agent"
    ROUTE_NOT_DISPATCHABLE = "route-not-dispatchable"
    APPROVAL_REQUIRED = "approval-required"
    APPROVAL_DENIED = "approval-denied"
    EVIDENCE_REJECTED = "evidence-rejected"
    HOST_UNAVAILABLE = "host-unavailable"
    EXECUTION_FAILED = "execution-failed"
    RECEIPT_PERSISTENCE_FAILED = "receipt-persistence-failed"


class FailureClass(str, Enum):
    NONE = "none"
    POLICY_DENIAL = "policy-denial"
    MISSING_OR_INVALID_EVIDENCE = "missing-or-invalid-evidence"
    INFRASTRUCTURE_UNAVAILABLE = "infrastructure-unavailable"
    EXECUTION_FAILURE = "execution-failure"
    HUMAN_DECISION_REQUIRED = "human-decision-required"


@dataclass(frozen=True, slots=True, kw_only=True)
class NavigationWorkRequest:
    """Structured work request. ``service_request`` is the canonical identity root."""

    service_request: ExecutionServiceRequest
    issue_number: int
    task_reference: str
    capability_id: str | None = None
    capability_keywords: tuple[str, ...] = ()
    operation_class: str = VALIDATION_ONLY
    specialized_knowledge_required: bool | None = None
    library_hints: tuple[str, ...] = ()
    target_path_hints: tuple[str, ...] = ()
    mission_id: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class NavigationRoutingEvidence:
    """Opaque identities that the router requires, produced by their canonical owners.

    The pathway never derives or fabricates these (operating-mode decision,
    executable-lane selection, environment profile/health, runtime identity);
    a missing identity is a missing-evidence refusal, not a default.
    """

    operating_mode_decision_id: str | None = None
    executable_lane_selection_id: str | None = None
    environment_profile_id: str | None = None
    environment_health_evidence_id: str | None = None
    workflow_runtime_identity: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class NavigationExecutionHost:
    """Binding to the existing execution host (runtime configuration and probes).

    Passed through unchanged to ``compose_and_run_validation``; this module
    never constructs a runtime, lease, workspace, or git runner itself.
    """

    pilot_input: Any
    configuration: Any
    cancelled: Callable[[], bool]
    git_runner: object | None = None
    process_cancelled: object | None = None
    changed_paths_inspector: Callable[[], tuple[str, ...]] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class NavigationOutcome:
    schema_version: str
    status: NavigationStatus
    failure_class: FailureClass
    stage: str
    reason_codes: tuple[str, ...]
    lesson_retrieval_status: str | None
    context: Mapping[str, Any]
    capability_id: str | None
    selected_agent: Mapping[str, Any] | None
    route: str | None
    route_decision_id: str | None
    composition_status: str | None
    execution_attempted: bool
    receipt_persisted: bool
    receipt_digest: str | None
    ledger_jsonl: str
    lesson_candidate_authorized: bool = False
    github_writes_authorized: bool = False
    merge_authorized: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status.value,
            "failure_class": self.failure_class.value,
            "stage": self.stage,
            "reason_codes": list(self.reason_codes),
            "lesson_retrieval_status": self.lesson_retrieval_status,
            "context": dict(self.context),
            "capability_id": self.capability_id,
            "selected_agent": None if self.selected_agent is None else dict(self.selected_agent),
            "route": self.route,
            "route_decision_id": self.route_decision_id,
            "composition_status": self.composition_status,
            "execution_attempted": self.execution_attempted,
            "receipt_persisted": self.receipt_persisted,
            "receipt_digest": self.receipt_digest,
            "lesson_candidate_authorized": self.lesson_candidate_authorized,
            "github_writes_authorized": self.github_writes_authorized,
            "merge_authorized": self.merge_authorized,
        }


class FileReceiptSink:
    """Atomic, read-back-verified JSONL receipt persistence."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    def __call__(self, jsonl: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self._path.parent), prefix=".nav-receipt-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(jsonl)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self._path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        if self._path.read_text(encoding="utf-8") != jsonl:
            raise OSError("receipt read-back mismatch")


# --------------------------------------------------------------------------
# Agent registry (canonical agents + legacy aliases)
# --------------------------------------------------------------------------

_TABLE_ROW = re.compile(r"^\|(.+)\|\s*$")


def _table_rows(text: str, header_prefix: str) -> list[list[str]]:
    rows: list[list[str]] = []
    capture = False
    for line in text.splitlines():
        if not capture:
            if line.startswith(header_prefix):
                capture = True
            continue
        match = _TABLE_ROW.match(line)
        if match is None:
            if rows:
                break
            continue
        cells = [cell.strip() for cell in match.group(1).split("|")]
        if set("".join(cells)) <= set("-: "):
            continue
        rows.append(cells)
    return rows


def load_canonical_agents(registry_dir: Path) -> tuple[frozenset[str], Mapping[str, str]]:
    """Return (canonical agent names, lowercase alias -> canonical name)."""
    inheritance = (registry_dir / "agent-inheritance-registry.md").read_text(encoding="utf-8")
    canonical = frozenset(row[0] for row in _table_rows(inheritance, "| Agent | Inherits"))
    alias_text = (registry_dir / "legacy-agent-alias-registry.md").read_text(encoding="utf-8")
    aliases: dict[str, str] = {}
    for row in _table_rows(alias_text, "| Legacy Name"):
        if len(row) >= 4 and row[1] in canonical and row[3].startswith("active"):
            aliases[row[0].lower()] = row[1]
    if not canonical:
        raise ValueError("canonical agent registry is empty or unreadable")
    return canonical, aliases


def resolve_agent(name: str, canonical: frozenset[str], aliases: Mapping[str, str]) -> tuple[str, bool] | None:
    """Resolve a registry-declared agent name to a canonical agent (name, via_alias)."""
    if name in canonical:
        return name, False
    target = aliases.get(name.lower())
    return (target, True) if target is not None else None


# Operation-class eligibility. Read-only validation never needs repository write
# authority, so GitHub Service Agent (the sole write owner) is deliberately absent.
_OPERATION_AGENTS: Mapping[str, frozenset[str]] = {
    VALIDATION_ONLY: frozenset({"QA / Test Agent", "ChatGPT Orchestrator"}),
}


def select_agent(
    capability: Any,
    *,
    operation_class: str,
    canonical: frozenset[str],
    aliases: Mapping[str, str],
) -> tuple[Mapping[str, Any] | None, tuple[str, ...]]:
    """Explicit, deterministic selection criteria.

    1. the capability must be ``active`` and not deprecated (checked by the caller);
    2. each declared owner/supporting agent must resolve to a canonical agent
       (legacy aliases such as the retired ``Integration Manager`` resolve via the
       alias registry; unresolved names are skipped and reported);
    3. the canonical agent must be permitted for the operation class;
    4. the capability owner outranks supporting agents;
    5. ties break by canonical name (ascending).
    """
    permitted = _OPERATION_AGENTS.get(operation_class)
    if permitted is None:
        return None, ("operation-class-unsupported",)
    reasons: list[str] = []
    candidates: list[tuple[int, str, str, bool]] = []
    declared = [(0, capability.owner_agent), *[(1, n) for n in capability.supporting_agents]]
    for rank, declared_name in declared:
        resolved = resolve_agent(declared_name, canonical, aliases)
        if resolved is None:
            reasons.append(f"agent-unresolved:{declared_name}")
            continue
        name, via_alias = resolved
        if name not in permitted:
            reasons.append(f"agent-not-permitted-for-operation:{name}")
            continue
        candidates.append((rank, name, declared_name, via_alias))
    if not candidates:
        return None, tuple(reasons) or ("no-candidate-agent",)
    rank, name, declared_name, via_alias = sorted(candidates)[0]
    return (
        {
            "agent": name,
            "declared_as": declared_name,
            "resolved_via_alias": via_alias,
            "role": "owner" if rank == 0 else "supporting",
        },
        tuple(reasons),
    )


# --------------------------------------------------------------------------
# Pathway
# --------------------------------------------------------------------------


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _default_registry_dir() -> Path:
    return Path(__file__).resolve().parents[4] / "04_Registry"


def run_ai_navigation(
    work: NavigationWorkRequest,
    *,
    evaluated_at: str,
    command_plan: ValidationCommandPlan | None,
    authorization: ExecutionAuthorizationEvidence | None,
    host: NavigationExecutionHost | None,
    routing_evidence: NavigationRoutingEvidence | None,
    receipt_sink: Callable[[str], None],
    registry_dir: Path | None = None,
    capability_registry_path: Path | None = None,
    execute_read: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
    lesson_preflight: Callable[..., dict[str, object]] = activate_issue_start_lesson_preflight,
    before_dispatch: Callable[[], None] | None = None,
) -> NavigationOutcome:
    """Drive one structured work request through the connected pathway.

    ``execution_attempted`` is true only when the existing admission accepted
    the request and the canonical host was invoked.
    """
    registry_dir = registry_dir or _default_registry_dir()
    state: dict[str, Any] = {
        "ledger": EvidenceLedger(),
        "context": {},
        "lesson_status": None,
        "capability_id": None,
        "agent": None,
        "route": None,
        "route_id": None,
        "composition": None,
        "executed": False,
    }
    mission = work.mission_id or f"ai-navigation:{work.service_request.request_fingerprint}"

    def record(kind: NavigationDecisionType, label: str, reasons: tuple[str, ...], refs: tuple[str, ...] = ()) -> None:
        digest = hash_decision_inputs(
            {
                "request_fingerprint": work.service_request.request_fingerprint,
                "stage": label,
                "reasons": list(reasons),
                "capability_id": state["capability_id"],
                "agent": state["agent"],
                "route": state["route"],
            }
        )
        state["ledger"] = state["ledger"].append(
            mission_id=mission,
            decision_type=kind,
            inputs_digest=digest,
            reason_codes=tuple(sorted(set(reasons))) or ("none",),
            provenance_refs=refs or (f"request:{work.service_request.request_fingerprint}",),
            recorded_at=evaluated_at,
            actor=ACTOR,
            decision_label=label,
        )

    def finish(status: NavigationStatus, failure: FailureClass, stage: str, reasons: tuple[str, ...]) -> NavigationOutcome:
        terminal = NavigationDecisionType.COMPLETION if status is NavigationStatus.COMPLETED else NavigationDecisionType.EXECUTION
        persisted = False
        digest: str | None = None
        final_status, final_failure, final_reasons = status, failure, reasons
        try:
            record(terminal, f"outcome:{status.value}", reasons or ("completed",))
            jsonl = state["ledger"].to_jsonl()
            digest = state["ledger"].entries[-1].entry_digest
            receipt_sink(jsonl)
            persisted = True
        except Exception as exc:  # persistence is infrastructure; never silently dropped
            if status is NavigationStatus.COMPLETED:
                final_status = NavigationStatus.RECEIPT_PERSISTENCE_FAILED
                final_failure = FailureClass.INFRASTRUCTURE_UNAVAILABLE
                final_reasons = ("receipt-persistence-failed", type(exc).__name__)
                stage = "evidence"
            else:
                final_reasons = reasons + ("receipt-persistence-failed",)
        return NavigationOutcome(
            schema_version=AI_NAVIGATION_SCHEMA_VERSION,
            status=final_status,
            failure_class=final_failure,
            stage=stage,
            reason_codes=final_reasons,
            lesson_retrieval_status=state["lesson_status"],
            context=state["context"],
            capability_id=state["capability_id"],
            selected_agent=state["agent"],
            route=state["route"],
            route_decision_id=state["route_id"],
            composition_status=state["composition"],
            execution_attempted=state["executed"],
            receipt_persisted=persisted,
            receipt_digest=digest if persisted else None,
            ledger_jsonl=state["ledger"].to_jsonl(),
        )

    request = work.service_request
    repo = f"{request.repository_identity.owner}/{request.repository_identity.repository}"

    # 0. Entrypoint authorization + request evidence (existing validators).
    reasons = validate_execution_service_request(request, evaluated_at=evaluated_at)
    if reasons:
        return finish(
            NavigationStatus.REQUEST_REJECTED,
            FailureClass.MISSING_OR_INVALID_EVIDENCE,
            "request",
            tuple(sorted(r.value for r in reasons)),
        )
    if request.requesting_actor != request.canonical_owner:
        return finish(
            NavigationStatus.UNAUTHORIZED_ENTRYPOINT,
            FailureClass.POLICY_DENIAL,
            "request",
            ("requesting-actor-is-not-canonical-owner",),
        )

    # 1. Context + CKR6 lessons (explicit status; never fabricated).
    try:
        lessons = lesson_preflight(
            repository=repo,
            issue_number=work.issue_number,
            task_reference=work.task_reference,
            capability_keywords=work.capability_keywords,
            library_hints=work.library_hints,
            target_path_hints=work.target_path_hints,
            specialized_knowledge_required=work.specialized_knowledge_required,
            execute_read=execute_read,
        )
        state["lesson_status"] = str(lessons["lesson_retrieval_status"])
        admissible = bool(lessons["substantial_hypothesis_admissible"])
        selected = [dict(item) for item in lessons.get("selected_lessons", [])]  # type: ignore[union-attr]
        lesson_reasons = tuple(str(c) for c in lessons.get("selection_reason_codes", []))  # type: ignore[union-attr]
    except Exception as exc:
        state["lesson_status"] = "unavailable"
        admissible = False
        selected = []
        lesson_reasons = ("lesson-preflight-error", type(exc).__name__)
    state["context"] = {
        "request_fingerprint": request.request_fingerprint,
        "repository": repo,
        "issue_number": work.issue_number,
        "base_sha": request.base_sha,
        "expected_sha": request.expected_sha,
        "task_reference": work.task_reference,
        "lessons": {
            "retrieval_status": state["lesson_status"],
            "selected": selected,
            "reason_codes": list(lesson_reasons),
            "source_authority": "advisory-only",
        },
    }
    record(
        NavigationDecisionType.SELECTION,
        "context:lessons",
        (f"lesson-status:{state['lesson_status']}", *lesson_reasons),
    )
    if not admissible:
        return finish(
            NavigationStatus.LESSON_PREFLIGHT_BLOCKED,
            FailureClass.INFRASTRUCTURE_UNAVAILABLE,
            "context",
            ("lesson-retrieval-not-admissible", *lesson_reasons),
        )

    # 2. Capability discovery from the real registry. The registry distribution is
    # deliberately not a runtime dependency of the execution-service wheel
    # (test_registry_decoupled_host_runtime), so it is imported lazily here.
    try:
        from reusable_capability_registry import RegistryReader, discover_capabilities
        from reusable_capability_registry.reader import RegistryError
    except ImportError:
        return finish(
            NavigationStatus.INVALID_CAPABILITY,
            FailureClass.INFRASTRUCTURE_UNAVAILABLE,
            "capabilities",
            ("capability-registry-distribution-unavailable",),
        )
    try:
        reader = RegistryReader(capability_registry_path) if capability_registry_path else RegistryReader()
        results = discover_capabilities(
            reader,
            capability_id=work.capability_id,
            keywords=work.capability_keywords if work.capability_id is None else (),
            attach_provenance=True,
        )
    except RegistryError as exc:
        return finish(
            NavigationStatus.INVALID_CAPABILITY,
            FailureClass.MISSING_OR_INVALID_EVIDENCE,
            "capabilities",
            ("capability-discovery-failed", type(exc).__name__),
        )
    eligible = [r for r in results if r.capability.status == "active" and r.capability.deprecated_by is None]
    if not eligible:
        return finish(
            NavigationStatus.INVALID_CAPABILITY,
            FailureClass.MISSING_OR_INVALID_EVIDENCE,
            "capabilities",
            ("no-active-registered-capability", f"discovered:{len(results)}"),
        )
    if work.capability_id is None and len(eligible) != 1:
        eligible = sorted(eligible, key=lambda r: r.capability.capability_id)
    chosen = eligible[0]
    state["capability_id"] = chosen.capability.capability_id
    provenance = chosen.provenance
    state["context"]["capability"] = {
        "capability_id": chosen.capability.capability_id,
        "confidence": chosen.confidence.value,
        "evidence_basis": list(chosen.evidence_basis),
        "registry_digest": None if provenance is None else provenance.digest,
    }

    # 3. Agent selection with explicit criteria.
    try:
        canonical, aliases = load_canonical_agents(registry_dir)
    except (OSError, ValueError) as exc:
        return finish(
            NavigationStatus.NO_ELIGIBLE_AGENT,
            FailureClass.INFRASTRUCTURE_UNAVAILABLE,
            "selection",
            ("agent-registry-unavailable", type(exc).__name__),
        )
    agent, selection_reasons = select_agent(
        chosen.capability, operation_class=work.operation_class, canonical=canonical, aliases=aliases
    )
    state["context"]["agent_registry_sha256"] = {
        "inheritance": _sha(registry_dir / "agent-inheritance-registry.md"),
        "aliases": _sha(registry_dir / "legacy-agent-alias-registry.md"),
    }
    if agent is None:
        record(NavigationDecisionType.SELECTION, "agent:none", selection_reasons)
        return finish(
            NavigationStatus.NO_ELIGIBLE_AGENT,
            FailureClass.POLICY_DENIAL,
            "selection",
            ("no-eligible-agent", *selection_reasons),
        )
    state["agent"] = agent
    record(
        NavigationDecisionType.SELECTION,
        f"agent:{agent['agent']}",
        (f"capability:{state['capability_id']}", f"role:{agent['role']}", *selection_reasons),
    )

    # 4. Governance gates that precede routing: approval and command-plan evidence.
    if authorization is None:
        return finish(
            NavigationStatus.APPROVAL_REQUIRED,
            FailureClass.POLICY_DENIAL,
            "governance",
            ("execution-authorization-absent",),
        )
    if authorization.execution_authorized is not True:
        return finish(
            NavigationStatus.APPROVAL_DENIED,
            FailureClass.POLICY_DENIAL,
            "governance",
            ("execution-authorization-denied",),
        )
    if command_plan is None:
        return finish(
            NavigationStatus.EVIDENCE_REJECTED,
            FailureClass.MISSING_OR_INVALID_EVIDENCE,
            "governance",
            ("validation-command-plan-absent",),
        )
    try:
        plan_id = validation_command_plan_id(command_plan)
    except Exception as exc:
        return finish(
            NavigationStatus.EVIDENCE_REJECTED,
            FailureClass.MISSING_OR_INVALID_EVIDENCE,
            "governance",
            ("validation-command-plan-invalid", type(exc).__name__),
        )

    # 5. Routing through the existing deterministic router.
    routing_evidence = routing_evidence or NavigationRoutingEvidence()
    missing_ids = tuple(
        sorted(
            name
            for name, value in (
                ("environment_health_evidence_id", routing_evidence.environment_health_evidence_id),
                ("environment_profile_id", routing_evidence.environment_profile_id),
                ("executable_lane_selection_id", routing_evidence.executable_lane_selection_id),
                ("operating_mode_decision_id", routing_evidence.operating_mode_decision_id),
                ("workflow_runtime_identity", routing_evidence.workflow_runtime_identity),
            )
            if not value
        )
    )
    if missing_ids:
        return finish(
            NavigationStatus.EVIDENCE_REJECTED,
            FailureClass.MISSING_OR_INVALID_EVIDENCE,
            "routing",
            ("routing-evidence-incomplete", *(f"missing:{n}" for n in missing_ids)),
        )
    required = tuple(
        sorted(
            (
                ExecutorCapability.CHECKOUT,
                ExecutorCapability.ISOLATED_WORKTREE,
                ExecutorCapability.PROCESS_EXECUTION,
                ExecutorCapability.TEST_EXECUTION,
                ExecutorCapability.EXACT_HEAD_VALIDATION,
            ),
            key=lambda item: item.value,
        )
    )
    decision = select_executor_route(
        repository=repo,
        issue_or_handoff_identity=request.issue_or_handoff_identity,
        requested_operation=work.operation_class,
        required_capabilities=required,
        governed_runner_capabilities=required,
        governed_runner_available=host is not None,
        external_fallback_available=False,
        external_fallback_explicitly_permitted=False,
        created_at=request.created_at,
        expires_at=request.expires_at,
        invalidation_conditions=("expected-sha-changed",),
        execution_service_request_fingerprint_or_none=request.request_fingerprint,
        authorization_id_or_none=authorization.authorization_id,
        validation_command_plan_id_or_none=plan_id,
        execution_authorized=True,
        operating_mode_decision_id_or_none=routing_evidence.operating_mode_decision_id,
        executable_lane_selection_id_or_none=routing_evidence.executable_lane_selection_id,
        environment_profile_id_or_none=routing_evidence.environment_profile_id,
        environment_health_evidence_id_or_none=routing_evidence.environment_health_evidence_id,
        workflow_runtime_identity_or_none=routing_evidence.workflow_runtime_identity,
    )
    from .executor_routing import executor_route_decision_id

    state["route"] = decision.selected_route.value
    state["route_id"] = executor_route_decision_id(decision)
    record(
        NavigationDecisionType.EXECUTION,
        f"route:{decision.selected_route.value}",
        tuple(r.value for r in decision.route_reasons),
    )
    if decision.selected_route is not ExecutorRoute.CHATGPT_GOVERNED_RUNNER:
        human = decision.selected_route is ExecutorRoute.HUMAN_DECISION_REQUIRED
        unavailable = host is None
        return finish(
            NavigationStatus.HOST_UNAVAILABLE if unavailable else NavigationStatus.ROUTE_NOT_DISPATCHABLE,
            FailureClass.INFRASTRUCTURE_UNAVAILABLE if unavailable else (
                FailureClass.HUMAN_DECISION_REQUIRED if human else FailureClass.POLICY_DENIAL
            ),
            "routing",
            ("governed-runner-unavailable" if unavailable else "route-not-dispatchable",
             *(r.value for r in decision.route_reasons)),
        )

    # 6. Existing admission + canonical host dispatch (exactly once).
    # ``before_dispatch`` lets a trusted host durably record dispatch intent; if it
    # cannot, nothing is dispatched (never dispatch without a recoverable record).
    if before_dispatch is not None:
        try:
            before_dispatch()
        except Exception as exc:
            return finish(
                NavigationStatus.HOST_UNAVAILABLE,
                FailureClass.INFRASTRUCTURE_UNAVAILABLE,
                "dispatch",
                ("dispatch-intent-record-unavailable", type(exc).__name__),
            )
    try:
        composed: ExecutionCompositionResult = compose_and_run_validation(
            request=request,
            command_plan=command_plan,
            authorization=authorization,
            evaluated_at=evaluated_at,
            pilot_input=host.pilot_input,
            configuration=host.configuration,
            cancelled=host.cancelled,
            git_runner=host.git_runner,
            process_cancelled=host.process_cancelled,
            changed_paths_inspector=host.changed_paths_inspector,
        )
    except (OSError, ConnectionError) as exc:
        return finish(
            NavigationStatus.HOST_UNAVAILABLE,
            FailureClass.INFRASTRUCTURE_UNAVAILABLE,
            "dispatch",
            ("execution-host-unavailable", type(exc).__name__),
        )
    state["composition"] = composed.status.value
    state["executed"] = bool(composed.side_effects_performed)
    state["context"]["execution_evidence_id"] = composed.evidence_id
    codes = tuple(composed.reason_codes)
    status = composed.status
    if status is ExecutionCompositionStatus.MANUAL_REVIEW:
        return finish(NavigationStatus.EVIDENCE_REJECTED, FailureClass.MISSING_OR_INVALID_EVIDENCE, "admission", codes or ("admission-manual-review",))
    if status is ExecutionCompositionStatus.INFRASTRUCTURE_FAILURE:
        return finish(NavigationStatus.HOST_UNAVAILABLE, FailureClass.INFRASTRUCTURE_UNAVAILABLE, "dispatch", codes or ("infrastructure-failure",))
    if status is ExecutionCompositionStatus.CANCELLED:
        return finish(NavigationStatus.EXECUTION_FAILED, FailureClass.EXECUTION_FAILURE, "dispatch", codes or ("cancelled",))
    if status in (ExecutionCompositionStatus.FOCUSED_FAIL, ExecutionCompositionStatus.AGGREGATE_FAIL):
        return finish(NavigationStatus.EXECUTION_FAILED, FailureClass.EXECUTION_FAILURE, "dispatch", codes or ("validation-failed",))
    return finish(NavigationStatus.COMPLETED, FailureClass.NONE, "evidence", codes)


# --------------------------------------------------------------------------
# JSON-shaped initiating-host entrypoint
# --------------------------------------------------------------------------

_PAYLOAD_KEYS = frozenset(
    {
        "service_request",
        "command_plan",
        "issue_number",
        "task_reference",
        "capability_id",
        "capability_keywords",
        "operation_class",
        "specialized_knowledge_required",
        "library_hints",
        "target_path_hints",
        "mission_id",
        "routing_evidence",
    }
)


def host_clock_evaluated_at(clock: Callable[[], datetime] | None = None) -> str:
    """Canonical UTC ``evaluated_at`` from the trusted host clock (never request JSON)."""
    moment = (clock or (lambda: datetime.now(timezone.utc)))()
    if type(moment) is not datetime or moment.tzinfo is None:
        raise ValueError("host clock must supply a timezone-aware datetime")
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class AuthorizationSourceUnavailable(RuntimeError):
    """The trusted authorization source could not be read (infrastructure, not policy)."""


def trusted_execution_authorization_source(
    *,
    transport: ExecutionAuthorizationSourceTransport,
    candidate_packet_id: str,
    invocation_id: str,
    operation: str = VALIDATION_ONLY,
) -> Callable[[ExecutionServiceRequest, ValidationCommandPlan, str], ExecutionAuthorizationEvidence | None]:
    """Compose the existing owner-authorization reacquisition for the pathway.

    Wraps ``reacquire_execution_authorization`` unchanged. The candidate packet,
    invocation and operation bindings are trusted-composition arguments (the
    owner's record must name exactly them); nothing comes from the work payload.
    Returns evidence only for a CURRENT owner record; a missing/revoked/expired/
    mismatched record returns None (-> approval required); an unreadable source
    raises AuthorizationSourceUnavailable (-> infrastructure, not policy).
    """

    def source(request: ExecutionServiceRequest, plan: ValidationCommandPlan, evaluated_at: str):
        identity = str(request.issue_or_handoff_identity)
        if not identity.isdigit() or int(identity) <= 0:
            return None
        result = reacquire_execution_authorization(
            transport=transport,
            repository=plan.repository,
            issue_number=int(identity),
            expected_candidate_packet_id=candidate_packet_id,
            expected_invocation_id=invocation_id,
            expected_operation=operation,
            expected_request_fingerprint=request.request_fingerprint,
            expected_command_plan_id=validation_command_plan_id(plan),
            expected_sha=plan.expected_sha,
            evaluated_at=evaluated_at,
        )
        if ExecutionAuthorizationSourceReason.SOURCE_UNAVAILABLE in result.reason_codes:
            raise AuthorizationSourceUnavailable("authorization-source-unavailable")
        if result.status is not ExecutionAuthorizationSourceStatus.CURRENT:
            return None
        return result.evidence

    return source


def _payload_refusal(status: NavigationStatus, failure: FailureClass, reasons: tuple[str, ...]) -> dict[str, Any]:
    return {
        "schema_version": AI_NAVIGATION_SCHEMA_VERSION,
        "status": status.value,
        "failure_class": failure.value,
        "stage": "entrypoint",
        "reason_codes": sorted(set(reasons)),
        "execution_attempted": False,
        "receipt_persisted": False,
        "lesson_candidate_authorized": False,
        "github_writes_authorized": False,
        "merge_authorized": False,
    }


def run_ai_navigation_payload(
    payload: Mapping[str, Any],
    *,
    host: NavigationExecutionHost | None,
    authorization_source: Callable[[ExecutionServiceRequest, ValidationCommandPlan, str], ExecutionAuthorizationEvidence | None],
    receipt_sink: Callable[[str], None],
    clock: Callable[[], datetime] | None = None,
    **pathway_options: Any,
) -> dict[str, Any]:
    """Initiating-host entrypoint: JSON-shaped work request in, structured outcome out.

    Trust split: the payload carries only the work request, command plan and
    opaque routing identities. It can never carry authorization, the execution
    host, a runtime/git binding, or a receipt destination - those come from the
    trusted host composition (``authorization_source`` must reacquire owner
    authorization, e.g. through ``execution_authorization_source``). A payload
    naming any other key is refused before any stage runs.
    """
    if not isinstance(payload, Mapping):
        return _payload_refusal(NavigationStatus.REQUEST_REJECTED, FailureClass.MISSING_OR_INVALID_EVIDENCE, ("payload-not-a-mapping",))
    unknown = sorted(str(k) for k in payload if k not in _PAYLOAD_KEYS)
    if unknown:
        forged = any(k in ("authorization", "execution_authorized", "host", "git_runner", "receipt_sink", "evaluated_at") for k in unknown)
        return _payload_refusal(
            NavigationStatus.REQUEST_REJECTED,
            FailureClass.POLICY_DENIAL if forged else FailureClass.MISSING_OR_INVALID_EVIDENCE,
            ("payload-unknown-keys", *(f"key:{k}" for k in unknown)),
        )
    try:
        request = reconstruct_execution_service_request(payload["service_request"])
        plan = reconstruct_validation_command_plan(payload["command_plan"])
        issue_number = payload["issue_number"]
        task_reference = payload["task_reference"]
        routing = NavigationRoutingEvidence(**dict(payload.get("routing_evidence") or {}))
        work = NavigationWorkRequest(
            service_request=request,
            issue_number=issue_number,
            task_reference=task_reference,
            capability_id=payload.get("capability_id"),
            capability_keywords=tuple(payload.get("capability_keywords", ())),
            operation_class=payload.get("operation_class", VALIDATION_ONLY),
            specialized_knowledge_required=payload.get("specialized_knowledge_required"),
            library_hints=tuple(payload.get("library_hints", ())),
            target_path_hints=tuple(payload.get("target_path_hints", ())),
            mission_id=payload.get("mission_id", ""),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return _payload_refusal(
            NavigationStatus.REQUEST_REJECTED,
            FailureClass.MISSING_OR_INVALID_EVIDENCE,
            ("payload-invalid", type(exc).__name__),
        )
    try:
        evaluated_at = host_clock_evaluated_at(clock)
    except (TypeError, ValueError):
        return _payload_refusal(
            NavigationStatus.REQUEST_REJECTED,
            FailureClass.INFRASTRUCTURE_UNAVAILABLE,
            ("host-clock-invalid",),
        )
    try:
        authorization = authorization_source(request, plan, evaluated_at)
    except Exception as exc:
        return _payload_refusal(
            NavigationStatus.APPROVAL_REQUIRED,
            FailureClass.INFRASTRUCTURE_UNAVAILABLE,
            ("authorization-source-unavailable", type(exc).__name__),
        )
    outcome = run_ai_navigation(
        work,
        evaluated_at=evaluated_at,
        command_plan=plan,
        authorization=authorization,
        host=host,
        routing_evidence=routing,
        receipt_sink=receipt_sink,
        **pathway_options,
    )
    return outcome.to_dict()
