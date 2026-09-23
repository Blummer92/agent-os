from dataclasses import replace

import pytest

from scripts.agent_os_execution_checkpoint import (
    CheckpointStage,
    InvalidationTrigger,
    StageStatus,
    WorktreeRole,
    binding_snapshot_from_checkpoint,
    detect_triggers,
)
from scripts.agent_os_execution_checkpoint.construction import (
    ACCEPTANCE_CRITERIA_DIGEST_DOMAIN,
    DEPENDENCY_FINGERPRINT_DOMAIN,
    ENVIRONMENT_FINGERPRINT_DOMAIN,
    GOVERNANCE_CONTRACT_DIGEST_DOMAIN,
    WORKTREE_FINGERPRINT_DOMAIN,
    AcceptanceCriteriaEvidence,
    CanonicalExecutionEvidence,
    CheckpointConstructionError,
    DependencyEvidence,
    DependencyManifestEvidence,
    EnvironmentEvidence,
    GovernanceContractEvidence,
    GovernanceDocumentEvidence,
    StageObservation,
    WorktreeEvidence,
    construct_execution_checkpoint,
    derive_acceptance_criteria_digest,
    derive_dependency_fingerprint,
    derive_environment_fingerprint,
    derive_governance_contract_digest,
    derive_worktree_fingerprint,
)

SHA_A = "a" * 40
SHA_B = "b" * 40
HEX_A = "a" * 64
HEX_B = "b" * 64


def _evidence():
    execution = CanonicalExecutionEvidence(
        repository="Blummer92/agent-os",
        issue_number=1431,
        invocation_id="invocation-1431",
        execution_id="execution-1431",
        branch="agent/1431-checkpoint-construction",
        worktree_role=WorktreeRole.ISSUE_WORKTREE,
        source_sha=SHA_A,
        tested_sha=SHA_A,
        merge_base_sha=SHA_B,
        command_plan_id=f"command-plan:{HEX_A}",
        authorization_snapshot_id=f"authorization-snapshot:{HEX_B}",
    )
    worktree = WorktreeEvidence(
        branch=execution.branch,
        worktree_role=execution.worktree_role,
        source_sha=execution.source_sha,
        index_tree_sha=SHA_B,
        working_diff_digest=HEX_A,
    )
    environment = EnvironmentEvidence(
        operating_system="linux",
        architecture="x86_64",
        runtime_identities=("python:3.11.9", "git:2.45.2"),
        container_image_digest=HEX_B,
    )
    dependencies = DependencyEvidence(
        manifests=(
            DependencyManifestEvidence("pyproject.toml", HEX_A),
            DependencyManifestEvidence("requirements-dev.txt", HEX_B),
        )
    )
    acceptance = AcceptanceCriteriaEvidence(
        issue_number=1431,
        criteria=("Constructor fails closed on missing evidence.", "All authority flags remain false."),
    )
    governance = GovernanceContractEvidence(
        documents=(
            GovernanceDocumentEvidence("AGENTS.md", SHA_A),
            GovernanceDocumentEvidence("00_Governance/write-authorization-policy.md", SHA_B),
        )
    )
    preflight = StageObservation(
        stage=CheckpointStage.PREFLIGHT_COMPLETE,
        status=StageStatus.PASSED,
        tested_sha=SHA_A,
    )
    return execution, worktree, environment, dependencies, acceptance, governance, preflight


def _construct(**overrides):
    execution, worktree, environment, dependencies, acceptance, governance, preflight = _evidence()
    values = dict(
        execution=execution,
        worktree=worktree,
        environment=environment,
        dependencies=dependencies,
        acceptance=acceptance,
        governance=governance,
        stage_observations=(preflight,),
        recorded_at="2026-08-27T17:00:00Z",
        actor_id="github-service-agent",
    )
    values.update(overrides)
    return construct_execution_checkpoint(**values)


def test_identical_canonical_evidence_has_identical_semantic_identity():
    first = _construct()
    second = _construct(recorded_at="2026-08-27T18:00:00Z", actor_id="qa-test-agent")
    assert first.checkpoint_id == second.checkpoint_id
    assert first.reuse_key == second.reuse_key


def test_constructor_preserves_exact_bindings_and_creates_no_authority():
    checkpoint = _construct()
    execution, *_ = _evidence()
    assert checkpoint.source_sha == execution.source_sha
    assert checkpoint.tested_sha == execution.tested_sha
    assert checkpoint.merge_base_sha == execution.merge_base_sha
    assert checkpoint.branch == execution.branch
    assert checkpoint.authorization_snapshot_id == execution.authorization_snapshot_id
    assert checkpoint.checkpoint_stage is CheckpointStage.PREFLIGHT_COMPLETE
    assert not any(
        (
            checkpoint.repository_implementation_authorized,
            checkpoint.execution_authorized,
            checkpoint.github_writes_authorized,
            checkpoint.merge_authorized,
            checkpoint.issue_closure_authorized,
            checkpoint.external_writes_authorized,
        )
    )


def test_derived_bindings_are_deterministic_domain_separated_and_not_caller_supplied():
    _, worktree, environment, dependencies, acceptance, governance, _ = _evidence()
    digests = {
        derive_worktree_fingerprint(worktree),
        derive_environment_fingerprint(environment),
        derive_dependency_fingerprint(dependencies),
        derive_acceptance_criteria_digest(acceptance),
        derive_governance_contract_digest(governance),
    }
    assert len(digests) == 5
    assert all(len(value) == 64 for value in digests)
    assert WORKTREE_FINGERPRINT_DOMAIN != ENVIRONMENT_FINGERPRINT_DOMAIN
    assert DEPENDENCY_FINGERPRINT_DOMAIN != ACCEPTANCE_CRITERIA_DIGEST_DOMAIN
    assert GOVERNANCE_CONTRACT_DIGEST_DOMAIN != ACCEPTANCE_CRITERIA_DIGEST_DOMAIN
    checkpoint = _construct()
    assert checkpoint.worktree_fingerprint == derive_worktree_fingerprint(worktree)
    assert checkpoint.environment_fingerprint == derive_environment_fingerprint(environment)
    assert checkpoint.dependency_fingerprint == derive_dependency_fingerprint(dependencies)


def test_acceptance_and_governance_changes_drive_existing_invalidation_matrix():
    original = _construct()
    recorded = binding_snapshot_from_checkpoint(original)
    execution, worktree, environment, dependencies, acceptance, governance, preflight = _evidence()

    changed_acceptance = replace(acceptance, criteria=acceptance.criteria + ("New criterion.",))
    acceptance_checkpoint = construct_execution_checkpoint(
        execution=execution,
        worktree=worktree,
        environment=environment,
        dependencies=dependencies,
        acceptance=changed_acceptance,
        governance=governance,
        stage_observations=(preflight,),
        recorded_at="2026-08-27T17:00:00Z",
        actor_id="github-service-agent",
    )
    triggers = detect_triggers(recorded=recorded, current=binding_snapshot_from_checkpoint(acceptance_checkpoint))
    assert InvalidationTrigger.ACCEPTANCE_CRITERIA_CHANGED in triggers
    assert InvalidationTrigger.GOVERNANCE_CONTRACT_CHANGED not in triggers

    changed_governance = replace(
        governance,
        documents=governance.documents + (GovernanceDocumentEvidence("04_Registry/responsibility-matrix.md", "c" * 40),),
    )
    governance_checkpoint = construct_execution_checkpoint(
        execution=execution,
        worktree=worktree,
        environment=environment,
        dependencies=dependencies,
        acceptance=acceptance,
        governance=changed_governance,
        stage_observations=(preflight,),
        recorded_at="2026-08-27T17:00:00Z",
        actor_id="github-service-agent",
    )
    triggers = detect_triggers(recorded=recorded, current=binding_snapshot_from_checkpoint(governance_checkpoint))
    assert InvalidationTrigger.GOVERNANCE_CONTRACT_CHANGED in triggers
    assert InvalidationTrigger.ACCEPTANCE_CRITERIA_CHANGED not in triggers


def test_worktree_environment_dependency_changes_use_existing_triggers():
    original = _construct()
    recorded = binding_snapshot_from_checkpoint(original)
    execution, worktree, environment, dependencies, acceptance, governance, preflight = _evidence()
    changed = construct_execution_checkpoint(
        execution=execution,
        worktree=replace(worktree, working_diff_digest=HEX_B),
        environment=replace(environment, runtime_identities=("python:3.12.5", "git:2.45.2")),
        dependencies=replace(
            dependencies,
            manifests=(DependencyManifestEvidence("pyproject.toml", HEX_B),),
        ),
        acceptance=acceptance,
        governance=governance,
        stage_observations=(preflight,),
        recorded_at="2026-08-27T17:00:00Z",
        actor_id="github-service-agent",
    )
    triggers = detect_triggers(recorded=recorded, current=binding_snapshot_from_checkpoint(changed))
    assert InvalidationTrigger.WORKTREE_CHANGED in triggers
    assert InvalidationTrigger.ENVIRONMENT_CHANGED in triggers
    assert InvalidationTrigger.DEPENDENCY_CHANGED in triggers


def test_missing_or_ambiguous_evidence_fails_closed():
    execution, worktree, environment, dependencies, acceptance, governance, preflight = _evidence()
    with pytest.raises(CheckpointConstructionError, match="does not match canonical"):
        construct_execution_checkpoint(
            execution=execution,
            worktree=replace(worktree, source_sha=SHA_B),
            environment=environment,
            dependencies=dependencies,
            acceptance=acceptance,
            governance=governance,
            stage_observations=(preflight,),
            recorded_at="2026-08-27T17:00:00Z",
            actor_id="github-service-agent",
        )
    with pytest.raises(CheckpointConstructionError, match="duplicate stage"):
        _construct(stage_observations=(preflight, preflight))


def test_later_stage_requires_contiguous_truthful_evidence():
    *_, preflight = _evidence()
    focused = StageObservation(
        stage=CheckpointStage.FOCUSED_TESTS_PASSED,
        status=StageStatus.PASSED,
        tested_sha=SHA_A,
    )
    with pytest.raises(CheckpointConstructionError, match="missing prior evidence"):
        _construct(stage_observations=(preflight, focused))


def test_mutating_stage_requires_mutation_evidence():
    with pytest.raises(CheckpointConstructionError, match="requires mutation_intent_id"):
        StageObservation(
            stage=CheckpointStage.IMPLEMENTATION_COMPLETE,
            status=StageStatus.PASSED,
            tested_sha=SHA_A,
        )


def test_real_1210_shape_cannot_be_misrepresented_as_1239_without_1239_execution_evidence():
    """#1429 is useful shape evidence, never historical #1239 execution evidence."""
    with pytest.raises(CheckpointConstructionError):
        CanonicalExecutionEvidence(
            repository="Blummer92/agent-os",
            issue_number=1239,
            invocation_id="",
            execution_id="",
            branch="claude/cloud-build-pre-pr-admission-uk2b7n",
            worktree_role=WorktreeRole.ISSUE_WORKTREE,
            source_sha="f56a2f645592be96d78a64da56f0e2af50653379",
            tested_sha="",
            merge_base_sha="39c2ad07f46237b4385bf1c795a07de0b85c0904",
            command_plan_id=f"command-plan:{HEX_A}",
        )
