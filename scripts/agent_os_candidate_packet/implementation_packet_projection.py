"""Pure-local projection into the existing Agent Memory handoff packet (#934).

`Implementation Packet` is a usage profile only. This module deliberately
creates no packet schema, readiness model, authority record, executor, or
persistence surface. It verifies supplied canonical Agent OS evidence, calls
the existing ``agent_memory_context_manager`` public packet builder/validator,
and returns that packet together with bounded source identities.

The Memory Manager is an existing separately packaged dependency. This module
uses only its declared public API; it defines no path-loader, runtime repository
discovery, or private-import compatibility mechanism.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from agent_memory_context_manager import (
    assert_valid_handoff_packet,
    build_handoff_packet,
    handoff_packet_source_fingerprint,
)
from scripts.agent_os_issue_acceptance.issue_operational_state import (
    FreshnessState,
    IssueState,
    IssueOperationalState,
    ReadinessState,
)
from scripts.agent_os_issue_acceptance.issueplan_current_state import (
    ISSUEPLAN_CURRENT_STATE_SCHEMA_VERSION,
)
from scripts.agent_os_issue_acceptance.operating_mode import (
    AgentOperatingModeDecision,
    OPERATING_MODE_DECISION_SCHEMA_NAME,
    OPERATING_MODE_DECISION_SCHEMA_VERSION,
)

from .stage_models import (
    IssueReadinessStageResult,
    IssueReadinessStageStatus,
)

MAX_CONTEXT_ITEMS = 64
MAX_TEXT_BYTES = 4096
MAX_ITEM_BYTES = 1024
MAX_PATH_BYTES = 512
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True, slots=True)
class ImplementationPacketSourceIdentities:
    """Bounded provenance for one projected existing handoff packet.

    This is evidence about the projection boundary, not a packet schema and not
    an authority record. ``packet`` remains the canonical Memory Manager
    handoff packet.
    """

    repository: str
    issue_number: int
    issue_source_revision: str
    issue_body_sha256: str
    issueplan_evidence_id: str
    evaluated_repository_sha: str
    operational_state_id: str
    operating_mode_decision_id: str
    packet_source_fingerprint: str
    source_identity_fingerprint: str


@dataclass(frozen=True, slots=True)
class ImplementationPacketProjection:
    """Existing Memory Manager packet plus bounded source identity evidence."""

    packet: Mapping[str, Any]
    source_identities: ImplementationPacketSourceIdentities


def project_implementation_packet(
    readiness_stage_result: IssueReadinessStageResult,
    operational_state: IssueOperationalState,
    operating_mode_decision: AgentOperatingModeDecision,
    *,
    objective: str,
    allowed_inspect_first: tuple[str, ...] = (),
    known_facts: tuple[str, ...] = (),
    prior_decisions: tuple[str, ...] = (),
    acceptance_criteria: tuple[str, ...],
    stop_conditions: tuple[str, ...],
    compute_limits: Mapping[str, Any] | None = None,
) -> ImplementationPacketProjection:
    """Project current supplied evidence into the existing handoff packet.

    The function performs pure in-memory validation/projection only. It never
    reads issue prose, calls GitHub, invokes Scheduler/provider code, launches a
    subprocess, writes the filesystem, or creates authorization.

    ``allowed_inspect_first`` is context guidance only and must be a strict
    subset of the canonical upstream ``allowed_files``. Required validation
    commands are copied exactly from canonical ``required_tests``; callers
    cannot substitute or weaken them here.
    """

    _validate_canonical_inputs(
        readiness_stage_result, operational_state, operating_mode_decision
    )

    snapshot = readiness_stage_result.snapshot
    issueplan = readiness_stage_result.issueplan_current_state_evidence
    assert snapshot is not None
    assert issueplan is not None

    objective_value = _text(objective, "objective", MAX_TEXT_BYTES)
    facts = _text_tuple(known_facts, "known_facts")
    decisions = _text_tuple(prior_decisions, "prior_decisions")
    criteria = _text_tuple(
        acceptance_criteria, "acceptance_criteria", preserve_order=True
    )
    stops = _text_tuple(stop_conditions, "stop_conditions", preserve_order=True)

    canonical_allowed = tuple(issueplan.allowed_files)
    inspect_first = _path_tuple(
        allowed_inspect_first, "allowed_inspect_first", preserve_order=True
    )
    if not inspect_first:
        inspect_first = canonical_allowed[:8]
    unauthorized_hints = tuple(
        path for path in inspect_first if path not in canonical_allowed
    )
    if unauthorized_hints:
        raise ValueError(
            "allowed_inspect_first contains paths outside canonical allowed_files: "
            + ", ".join(unauthorized_hints)
        )

    forbidden = _path_tuple(tuple(issueplan.forbidden_paths), "forbidden_paths")
    required_tests = _text_tuple(
        tuple(issueplan.required_tests), "required_tests", preserve_order=True
    )
    if not required_tests:
        raise ValueError("current IssuePlan evidence must supply required_tests")

    branch, pr_number = _branch_and_pr(operational_state)
    current_phase = (
        f"{operational_state.lifecycle_stage.value}/"
        f"{operating_mode_decision.effective_mode.value}"
    )

    packet = build_handoff_packet(
        objective=objective_value,
        current_phase=current_phase,
        branch=branch,
        pr_number=pr_number,
        changed_files=[],
        allowed_inspect_first=list(inspect_first),
        forbidden_unless_needed=list(forbidden),
        known_facts=list(facts),
        prior_decisions=list(decisions),
        acceptance_criteria=list(criteria),
        validation_commands=list(required_tests),
        stop_conditions=list(stops),
        compute_limits=None if compute_limits is None else dict(compute_limits),
    )
    assert_valid_handoff_packet(packet)
    packet_fingerprint = handoff_packet_source_fingerprint(packet)
    if not _SHA256_RE.fullmatch(packet_fingerprint):
        raise ValueError("Memory Manager returned an invalid packet source fingerprint")

    source_payload = {
        "repository": snapshot.repository,
        "issue_number": snapshot.issue_number,
        "issue_source_revision": snapshot.source_revision,
        "issue_body_sha256": snapshot.body_sha256,
        "issueplan_evidence_id": issueplan.evidence_id,
        "evaluated_repository_sha": issueplan.evaluated_repository_sha,
        "operational_state_id": operational_state.state_id,
        "operating_mode_decision_id": operating_mode_decision.decision_id,
        "packet_source_fingerprint": packet_fingerprint,
    }
    source_fingerprint = hashlib.sha256(
        b"agent-os-implementation-packet-source:v1\0"
        + json.dumps(
            source_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()

    identities = ImplementationPacketSourceIdentities(
        **source_payload,
        source_identity_fingerprint=source_fingerprint,
    )
    return ImplementationPacketProjection(packet=packet, source_identities=identities)


def _validate_canonical_inputs(
    readiness_stage_result: IssueReadinessStageResult,
    operational_state: IssueOperationalState,
    operating_mode_decision: AgentOperatingModeDecision,
) -> None:
    if type(readiness_stage_result) is not IssueReadinessStageResult:
        raise TypeError("readiness_stage_result must be an exact IssueReadinessStageResult")
    if type(operational_state) is not IssueOperationalState:
        raise TypeError("operational_state must be an exact IssueOperationalState")
    if type(operating_mode_decision) is not AgentOperatingModeDecision:
        raise TypeError(
            "operating_mode_decision must be an exact AgentOperatingModeDecision"
        )

    if readiness_stage_result.status is not IssueReadinessStageStatus.READY:
        raise ValueError("readiness_stage_result must be current READY evidence")
    snapshot = readiness_stage_result.snapshot
    issueplan = readiness_stage_result.issueplan_current_state_evidence
    readiness = readiness_stage_result.readiness_result
    if snapshot is None or issueplan is None or readiness is None:
        raise ValueError("READY evidence is incomplete")
    if issueplan.schema_version != ISSUEPLAN_CURRENT_STATE_SCHEMA_VERSION:
        raise ValueError("unsupported IssuePlan current-state schema version")
    if issueplan.repository != snapshot.repository:
        raise ValueError("IssuePlan repository does not match issue snapshot")
    if issueplan.source_snapshot.source_revision != snapshot.source_revision:
        raise ValueError("IssuePlan source revision does not match issue snapshot")
    if (
        issueplan.source_snapshot.scanner_result_fingerprint
        != issueplan.scanner_result_fingerprint
    ):
        raise ValueError("IssuePlan scanner fingerprint binding is contradictory")

    if operational_state.repository != snapshot.repository:
        raise ValueError("operational-state repository does not match issue snapshot")
    if operational_state.issue_number != snapshot.issue_number:
        raise ValueError("operational-state issue does not match issue snapshot")
    if not issueplan.evaluated_repository_sha:
        raise ValueError("IssuePlan evidence is missing evaluated_repository_sha")
    if operational_state.source_revision != issueplan.evaluated_repository_sha:
        raise ValueError(
            "operational-state source revision does not match evaluated repository"
        )
    if operational_state.issue_state is not IssueState.OPEN:
        raise ValueError("implementation packet requires an open issue")
    if operational_state.readiness is not ReadinessState.READY:
        raise ValueError("operational-state readiness must remain READY")
    if operational_state.freshness_state is not FreshnessState.CURRENT:
        raise ValueError("operational-state evidence is stale")
    if operational_state.reconciliation_required:
        raise ValueError("operational-state evidence requires reconciliation")

    if (
        operating_mode_decision.schema_name != OPERATING_MODE_DECISION_SCHEMA_NAME
        or operating_mode_decision.schema_version
        != OPERATING_MODE_DECISION_SCHEMA_VERSION
    ):
        raise ValueError("unsupported operating-mode decision schema version")
    if operating_mode_decision.source_operational_state_id != operational_state.state_id:
        raise ValueError("operating-mode decision is not bound to operational state")
    if operating_mode_decision.side_effects_performed is not False:
        raise ValueError("operating-mode decision must be side-effect free")


def _branch_and_pr(state: IssueOperationalState) -> tuple[str | None, int | None]:
    if len(state.primary_pr_numbers) > 1:
        raise ValueError("multiple primary PR identities cannot be projected")
    pr_number = state.primary_pr_numbers[0] if state.primary_pr_numbers else None
    if pr_number is not None and state.active_branch is None:
        raise ValueError("primary PR identity is missing its active branch")
    return state.active_branch, pr_number


def _text(value: object, name: str, maximum_bytes: int) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be a built-in string")
    if not value.strip() or len(value.encode("utf-8")) > maximum_bytes:
        raise ValueError(f"{name} is outside bounds")
    if _CONTROL_RE.search(value):
        raise ValueError(f"{name} contains control characters")
    return value


def _text_tuple(
    values: object,
    name: str,
    *,
    preserve_order: bool = False,
) -> tuple[str, ...]:
    if type(values) is not tuple:
        raise TypeError(f"{name} must be an exact tuple")
    if len(values) > MAX_CONTEXT_ITEMS:
        raise ValueError(f"{name} exceeds its item bound")
    checked = tuple(_text(value, name, MAX_ITEM_BYTES) for value in values)
    if len(set(checked)) != len(checked):
        raise ValueError(f"{name} contains duplicates")
    return checked if preserve_order else tuple(sorted(checked))


def _path_tuple(
    values: object,
    name: str,
    *,
    preserve_order: bool = False,
) -> tuple[str, ...]:
    if type(values) is not tuple:
        raise TypeError(f"{name} must be an exact tuple")
    if len(values) > MAX_CONTEXT_ITEMS:
        raise ValueError(f"{name} exceeds its item bound")
    checked = tuple(_text(value, name, MAX_PATH_BYTES) for value in values)
    if len(set(checked)) != len(checked):
        raise ValueError(f"{name} contains duplicates")
    return checked if preserve_order else tuple(sorted(checked))
