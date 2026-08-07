"""Focused tests for the pure #934 Implementation Packet projection."""

from __future__ import annotations

import ast
import copy
import hashlib
import sys
from pathlib import Path

import pytest

MEMORY_MANAGER_SRC = (
    Path(__file__).resolve().parents[2]
    / "08_Tooling"
    / "agent-memory-context-manager"
    / "src"
)
sys.path.insert(0, str(MEMORY_MANAGER_SRC))

from agent_memory_context_manager import handoff_packet_source_fingerprint  # noqa: E402
from scripts.agent_os_issue_acceptance.issue_operational_state import (  # noqa: E402
    AuthorityProjection,
    AuthorizationState,
    DependencyState,
    FreshnessState,
    IssueOperationalEvidence,
    IssueState,
    LifecycleStage,
    ReadinessState,
    SourceState,
    TerminalDisposition,
    ValidationState,
    build_issue_operational_state,
)
from scripts.agent_os_issue_acceptance.issueplan_current_state import (  # noqa: E402
    ISSUEPLAN_CURRENT_STATE_SCHEMA_VERSION,
    IssuePlanCurrentStateEvidence,
    IssuePlanSourceSnapshot,
)
from scripts.agent_os_issue_acceptance.models import (  # noqa: E402
    AcceptanceReport,
    Status,
)
from scripts.agent_os_issue_acceptance.operating_mode import (  # noqa: E402
    EnvironmentCapabilityEvidence,
    EnvironmentCapabilityState,
    evaluate_operating_mode_decision,
)
from scripts.agent_os_issue_acceptance.readiness import (  # noqa: E402
    ReadinessOutcome,
    ReadinessResult,
)
from scripts.agent_os_candidate_packet.implementation_packet_projection import (  # noqa: E402
    project_implementation_packet,
)
from scripts.agent_os_candidate_packet.stage_models import (  # noqa: E402
    DependencyIdentityEvidence,
    DependencyIdentityStatus,
    IssueReadinessStageResult,
    IssueReadinessStageStatus,
    IssueSnapshot,
)

REPOSITORY = "Blummer92/agent-os"
ISSUE_NUMBER = 934
REPOSITORY_SHA = "a" * 40
ISSUE_SOURCE_REVISION = "github-issue-v1:" + "b" * 64
APPROVAL_ID = "approval:" + "1" * 64
ENV_ID = "environment-capability:" + "2" * 64


def _authority(state: AuthorizationState) -> AuthorityProjection:
    evidence_id = APPROVAL_ID if state is AuthorizationState.AUTHORIZED else None
    return AuthorityProjection(state=state, evidence_id=evidence_id)


def _readiness_stage(*, schema_version: str = ISSUEPLAN_CURRENT_STATE_SCHEMA_VERSION):
    body = "canonical issue body"
    snapshot = IssueSnapshot(
        repository=REPOSITORY,
        issue_number=ISSUE_NUMBER,
        url="https://github.com/Blummer92/agent-os/issues/934",
        created_at="2026-08-07T03:20:37Z",
        updated_at="2026-08-07T03:20:37Z",
        body=body,
        body_sha256=hashlib.sha256(body.encode()).hexdigest(),
        source_revision=ISSUE_SOURCE_REVISION,
        retrieved_at="2026-08-07T12:00:00Z",
    )
    source_snapshot = IssuePlanSourceSnapshot(
        source_locator="github:Blummer92/agent-os#934",
        source_family="github-issue",
        source_revision=ISSUE_SOURCE_REVISION,
        retrieval_status="present",
        completeness_status="complete",
        metadata_status="present",
        governed_fields=(),
        omitted_fields=(),
        provenance_references=("issue:934",),
        candidate_set_fingerprint="candidate-set-934",
        scanner_result_fingerprint="scanner-934",
    )
    issueplan = IssuePlanCurrentStateEvidence(
        schema_version=schema_version,
        evidence_id="issueplan-evidence-934",
        observed_at="2026-08-07T12:00:00Z",
        freshness_boundary="stage-observation",
        source_snapshot=source_snapshot,
        source_snapshot_fingerprint="snapshot-934",
        scanner_result_fingerprint="scanner-934",
        entity_ids=("issue-934",),
        candidate_revisions=("candidate-934",),
        repository=REPOSITORY,
        base_branch="main",
        evaluated_repository_sha=REPOSITORY_SHA,
        implementation_contract_fingerprint="contract-934",
        allowed_files=(
            "scripts/agent_os_candidate_packet/implementation_packet_projection.py",
            "tests/agent_os_candidate_packet/test_implementation_packet_projection.py",
        ),
        forbidden_paths=(".github/workflows/**", "00_Governance/**"),
        required_tests=(
            "python -m pytest tests/agent_os_candidate_packet/test_implementation_packet_projection.py -q",
            "./scripts/validate-all.sh --focused tests/agent_os_candidate_packet",
        ),
    )
    readiness = ReadinessResult(
        outcome=ReadinessOutcome.READY,
        report=AcceptanceReport(
            linked_issue=ISSUE_NUMBER,
            overall_status=Status.PASS,
            checks=[],
        ),
    )
    return IssueReadinessStageResult(
        status=IssueReadinessStageStatus.READY,
        snapshot=snapshot,
        issueplan_current_state_evidence=issueplan,
        readiness_result=readiness,
        dependency_identity_evidence=DependencyIdentityEvidence(
            status=DependencyIdentityStatus.ABSENT,
            provenance=("issueplan:no-dependencies",),
        ),
    )


def _operational_state(
    *,
    freshness=FreshnessState.CURRENT,
    claims=(),
    implementation_authorization=AuthorizationState.AUTHORIZED,
):
    evidence = IssueOperationalEvidence(
        repository=REPOSITORY,
        issue_number=ISSUE_NUMBER,
        source_revision=REPOSITORY_SHA,
        observed_at="2026-08-07T12:00:00Z",
        evidence_ids=(APPROVAL_ID,),
        source_state=SourceState.COMPLETE,
        issue_state=IssueState.OPEN,
        lifecycle_stage=LifecycleStage.IMPLEMENTATION,
        terminal_disposition=TerminalDisposition.NONE,
        readiness=ReadinessState.READY,
        implementation_authorization=_authority(implementation_authorization),
        ready_for_review_authorization=_authority(AuthorizationState.NOT_AUTHORIZED),
        execution_authorization=_authority(AuthorizationState.NOT_AUTHORIZED),
        merge_authorization=_authority(AuthorizationState.NOT_AUTHORIZED),
        closure_authorization=_authority(AuthorizationState.NOT_AUTHORIZED),
        external_write_authorization=_authority(AuthorizationState.NOT_AUTHORIZED),
        dependency_state=DependencyState.CLEAR,
        primary_claims=claims,
        validation_state=ValidationState.NOT_RUN,
        freshness_state=freshness,
        observed_labels=("status:ready",),
    )
    return build_issue_operational_state(evidence)


def _mode(state):
    environment = EnvironmentCapabilityEvidence(
        local_execution_state=EnvironmentCapabilityState.VERIFIED,
        push_state=EnvironmentCapabilityState.NOT_VERIFIED,
        evidence_id=ENV_ID,
    )
    return evaluate_operating_mode_decision(state, "build", environment)


def _project(stage=None, state=None, **changes):
    stage = stage or _readiness_stage()
    state = state or _operational_state()
    mode = _mode(state)
    kwargs = {
        "objective": "Project current READY evidence into the existing handoff packet",
        "allowed_inspect_first": (
            "scripts/agent_os_candidate_packet/implementation_packet_projection.py",
        ),
        "known_facts": ("Memory Manager owns the handoff packet schema",),
        "prior_decisions": ("Do not create a second packet schema",),
        "acceptance_criteria": ("Projection remains deterministic", "No side effects"),
        "stop_conditions": ("A new packet schema becomes necessary",),
    }
    kwargs.update(changes)
    return project_implementation_packet(stage, state, mode, **kwargs)


def test_deterministic_projection_reuses_memory_manager_fingerprint():
    stage = _readiness_stage()
    first = _project(stage=stage)
    second = _project(stage=stage)

    assert first == second
    assert first.source_identities.packet_source_fingerprint == handoff_packet_source_fingerprint(
        first.packet
    )
    assert len(first.source_identities.source_identity_fingerprint) == 64
    assert first.packet["validation_commands"] == list(
        stage.issueplan_current_state_evidence.required_tests
    )


def test_order_insensitive_context_facts_are_canonicalized():
    first = _project(known_facts=("fact-b", "fact-a"), prior_decisions=("d2", "d1"))
    second = _project(known_facts=("fact-a", "fact-b"), prior_decisions=("d1", "d2"))

    assert first == second
    assert first.packet["known_facts"] == ["fact-a", "fact-b"]


def test_truthful_null_branch_and_pr_are_preserved():
    projection = _project()

    assert projection.packet["branch"] is None
    assert projection.packet["pr_number"] is None
    assert projection.packet["changed_files"] == []


def test_context_hint_cannot_widen_canonical_allowed_scope():
    with pytest.raises(ValueError, match="outside canonical allowed_files"):
        _project(allowed_inspect_first=("scripts/unrelated.py",))


def test_repository_issue_and_source_bindings_fail_closed():
    stage = _readiness_stage()
    state = _operational_state()
    object.__setattr__(state, "issue_number", 999)

    with pytest.raises(ValueError, match="operational-state issue"):
        _project(stage=stage, state=state)


def test_stale_operational_evidence_is_rejected():
    state = _operational_state(freshness=FreshnessState.STALE)

    with pytest.raises(ValueError, match="stale"):
        _project(state=state)


def test_bound_nonpermitting_mode_decision_is_rejected():
    state = _operational_state(
        implementation_authorization=AuthorizationState.NOT_AUTHORIZED
    )
    mode = _mode(state)

    with pytest.raises(ValueError, match="does not permit implementation"):
        project_implementation_packet(
            _readiness_stage(),
            state,
            mode,
            objective="Bounded projection",
            acceptance_criteria=("criterion",),
            stop_conditions=("stop",),
        )


def test_unknown_upstream_contract_version_fails_closed():
    stage = _readiness_stage(schema_version="99.0")

    with pytest.raises(ValueError, match="unsupported IssuePlan"):
        _project(stage=stage)


def test_inputs_are_not_mutated():
    stage = _readiness_stage()
    state = _operational_state()
    mode = _mode(state)
    stage_before = copy.deepcopy(stage)
    state_before = copy.deepcopy(state)
    mode_before = copy.deepcopy(mode)

    project_implementation_packet(
        stage,
        state,
        mode,
        objective="Bounded projection",
        acceptance_criteria=("criterion",),
        stop_conditions=("stop",),
    )

    assert stage == stage_before
    assert state == state_before
    assert mode == mode_before


def test_projection_module_has_no_execution_or_network_imports():
    module_path = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "agent_os_candidate_packet"
        / "implementation_packet_projection.py"
    )
    source = module_path.read_text()
    tree = ast.parse(source)
    forbidden_modules = {
        "subprocess",
        "requests",
        "urllib",
        "socket",
        "github",
        "scheduler",
    }
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name.split(".")[0].lower() for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module.split(".")[0].lower())

    assert imported_modules.isdisjoint(forbidden_modules)
    assert "open(" not in source
