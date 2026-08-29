from __future__ import annotations

import ast
import inspect

import pytest

from scripts.agent_os_issue_acceptance.authorization_drift_review import (
    AuthorizationDriftReviewRequest,
    AuthorizationState,
    AuthorizationStateEvidence,
    CompatibilityState,
    DependencyEvidence,
    DriftOutcome,
    GovernanceContractEvidence,
    RangeEvidence,
    ValidationContractEvidence,
    build_authorization_refresh_handoff,
    evaluate_authorization_drift,
)

A = "a" * 40
B = "b" * 40
EVIDENCE = "range-evidence:" + "1" * 64
REVALIDATION = "validation-evidence:" + "2" * 64


def _validation(**overrides):
    values = dict(
        original_required_tests=("python -m pytest tests/focused.py -q",),
        current_required_tests=("python -m pytest tests/focused.py -q",),
        original_command_or_profile="profile:focused-v1",
        current_command_or_profile="profile:focused-v1",
        original_policy_revision="testing-and-release:1",
        current_policy_revision="testing-and-release:1",
    )
    values.update(overrides)
    return ValidationContractEvidence(**values)


def _request(**overrides):
    values = dict(
        schema_name="agent-os-authorization-drift-review",
        schema_version="1.0",
        repository="Blummer92/agent-os",
        issue_number=1157,
        authorization_repository="Blummer92/agent-os",
        authorization_issue_number=1157,
        authorization_id="approval:" + "3" * 64,
        authorization_revision="approval-revision:" + "4" * 64,
        base_branch="main",
        authorization_base_sha=A,
        current_main_sha=B,
        authorization_state=AuthorizationStateEvidence(AuthorizationState.ACTIVE),
        range_evidence=RangeEvidence(
            base_sha=A,
            head_sha=B,
            changed_paths=("docs/unrelated.md",),
            provenance_ids=(EVIDENCE,),
        ),
        allowed_paths=("scripts/agent_os_issue_acceptance/authorization_drift_review.py",),
        forbidden_paths=(".github/workflows",),
        expected_paths=("tests/agent_os_issue_acceptance/test_authorization_drift_review.py",),
        original_contract_fingerprint="contract:" + "5" * 64,
        current_contract_fingerprint="contract:" + "5" * 64,
        contract_compatibility=CompatibilityState.COMPATIBLE,
        forbidden_surface_implicated=False,
        dependencies=(
            DependencyEvidence("dep:issue-operational-state", "r1", "r1", False),
        ),
        governance_contracts=(
            GovernanceContractEvidence("ownership", "r1", "r1", CompatibilityState.COMPATIBLE),
            GovernanceContractEvidence("source-of-truth", "r1", "r1", CompatibilityState.COMPATIBLE),
            GovernanceContractEvidence("write-authorization", "r1", "r1", CompatibilityState.COMPATIBLE),
            GovernanceContractEvidence("safe-lane", "r1", "r1", CompatibilityState.COMPATIBLE),
            GovernanceContractEvidence("lifecycle", "r1", "r1", CompatibilityState.COMPATIBLE),
            GovernanceContractEvidence("approval", "r1", "r1", CompatibilityState.COMPATIBLE),
        ),
        validation=_validation(),
        relevance_resolved=True,
    )
    values.update(overrides)
    return AuthorizationDriftReviewRequest(**values)


def test_unrelated_documentation_only_movement_is_no_relevant_drift():
    result = evaluate_authorization_drift(_request())
    assert result.outcome is DriftOutcome.NO_RELEVANT_DRIFT
    assert result.reason_codes == ("relevance.no-relevant-change",)
    assert not result.authorization_granted
    assert not result.side_effects_performed


def test_unrelated_source_movement_with_complete_dependency_proof_is_irrelevant():
    request = _request(
        range_evidence=RangeEvidence(A, B, ("src/unrelated.py",), provenance_ids=(EVIDENCE,)),
        dependencies=(DependencyEvidence("dep:x", "v1", "v1", False),),
    )
    assert evaluate_authorization_drift(request).outcome is DriftOutcome.NO_RELEVANT_DRIFT


@pytest.mark.parametrize(
    ("changed_path", "reason"),
    [
        ("scripts/agent_os_issue_acceptance/authorization_drift_review.py", "scope.allowlisted-path-changed"),
        ("tests/agent_os_issue_acceptance/test_authorization_drift_review.py", "scope.expected-path-changed"),
    ],
)
def test_authorized_or_expected_path_change_requires_revalidation(changed_path, reason):
    request = _request(range_evidence=RangeEvidence(A, B, (changed_path,), provenance_ids=(EVIDENCE,)))
    result = evaluate_authorization_drift(request)
    assert result.outcome is DriftOutcome.REVALIDATION_REQUIRED
    assert reason in result.reason_codes


def test_dependency_identity_change_requires_revalidation():
    result = evaluate_authorization_drift(
        _request(dependencies=(DependencyEvidence("dep:x", "v1", "v2", False),))
    )
    assert result.outcome is DriftOutcome.REVALIDATION_REQUIRED
    assert result.reason_codes == ("dependency.identity-changed",)


def test_public_interface_change_requires_revalidation():
    result = evaluate_authorization_drift(
        _request(dependencies=(DependencyEvidence("dep:x", "v1", "v1", True),))
    )
    assert result.outcome is DriftOutcome.REVALIDATION_REQUIRED
    assert result.reason_codes == ("dependency.public-interface-changed",)


@pytest.mark.parametrize(
    "validation",
    [
        _validation(current_required_tests=("python -m pytest tests/new.py -q",)),
        _validation(current_command_or_profile="profile:aggregate-v2"),
        _validation(current_policy_revision="testing-and-release:2"),
    ],
)
def test_validation_contract_drift_requires_revalidation(validation):
    result = evaluate_authorization_drift(_request(validation=validation))
    assert result.outcome is DriftOutcome.REVALIDATION_REQUIRED


def test_compatible_governance_movement_requires_revalidation():
    contracts = tuple(
        GovernanceContractEvidence(item.kind, item.original_revision, "r2", CompatibilityState.COMPATIBLE)
        if item.kind == "ownership" else item
        for item in _request().governance_contracts
    )
    result = evaluate_authorization_drift(_request(governance_contracts=contracts))
    assert result.outcome is DriftOutcome.REVALIDATION_REQUIRED
    assert result.reason_codes == ("governance.ownership-changed",)


def test_incompatible_governance_movement_is_contract_conflict():
    contracts = tuple(
        GovernanceContractEvidence(item.kind, item.original_revision, "r2", CompatibilityState.INCOMPATIBLE)
        if item.kind == "write-authorization" else item
        for item in _request().governance_contracts
    )
    result = evaluate_authorization_drift(_request(governance_contracts=contracts))
    assert result.outcome is DriftOutcome.CONTRACT_CONFLICT
    assert "contract.incompatible-current-main" in result.reason_codes
    assert "governance.write-authorization-changed" in result.reason_codes


def test_forbidden_surface_implication_is_contract_conflict():
    result = evaluate_authorization_drift(_request(forbidden_surface_implicated=True))
    assert result.outcome is DriftOutcome.CONTRACT_CONFLICT
    assert result.reason_codes == ("scope.forbidden-surface-implicated",)


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        (AuthorizationState.EXPIRED, "authorization.expired"),
        (AuthorizationState.REVOKED, "authorization.revoked"),
        (AuthorizationState.SUPERSEDED, "authorization.superseded"),
        (AuthorizationState.CONSUMED, "authorization.consumed"),
    ],
)
def test_terminal_authorization_state_is_expired_outcome(state, reason):
    result = evaluate_authorization_drift(
        _request(authorization_state=AuthorizationStateEvidence(state))
    )
    assert result.outcome is DriftOutcome.AUTHORIZATION_EXPIRED
    assert result.reason_codes == (reason,)


def test_stale_authorization_applicability_is_expired_outcome():
    result = evaluate_authorization_drift(
        _request(authorization_state=AuthorizationStateEvidence(AuthorizationState.ACTIVE, applicability_current=False))
    )
    assert result.outcome is DriftOutcome.AUTHORIZATION_EXPIRED
    assert result.reason_codes == ("authorization.applicability-stale",)


@pytest.mark.parametrize(
    "case",
    [
        _request(range_evidence=None),
        _request(range_evidence=RangeEvidence(A, B, (), complete=False, provenance_ids=(EVIDENCE,))),
        _request(range_evidence=RangeEvidence(A, B, (), provenance_current=False, provenance_ids=(EVIDENCE,))),
        _request(dependencies=(DependencyEvidence("dep:x", "v1", "v1", None),)),
        _request(schema_version="2.0"),
        _request(current_main_sha="not-a-sha"),
    ],
)
def test_missing_or_untrusted_evidence_fails_closed(case):
    result = evaluate_authorization_drift(case)
    assert result.outcome is DriftOutcome.EVIDENCE_INCOMPLETE


def test_identity_mismatch_fails_closed_before_authorization_state():
    result = evaluate_authorization_drift(
        _request(
            authorization_repository="Other/repo",
            authorization_state=AuthorizationStateEvidence(AuthorizationState.EXPIRED),
        )
    )
    assert result.outcome is DriftOutcome.EVIDENCE_INCOMPLETE
    assert result.reason_codes == ("identity.repository-mismatch",)


def test_complete_unknown_compatibility_requires_manual_decision():
    result = evaluate_authorization_drift(
        _request(contract_compatibility=CompatibilityState.UNKNOWN)
    )
    assert result.outcome is DriftOutcome.MANUAL_DECISION_REQUIRED
    assert result.reason_codes == ("relevance.unresolved",)


def test_reason_codes_are_sorted_and_deduplicated():
    request = _request(
        range_evidence=RangeEvidence(
            A,
            B,
            (
                "scripts/agent_os_issue_acceptance/authorization_drift_review.py",
                "tests/agent_os_issue_acceptance/test_authorization_drift_review.py",
            ),
            provenance_ids=(EVIDENCE,),
        ),
        validation=_validation(current_policy_revision="testing-and-release:2"),
    )
    result = evaluate_authorization_drift(request)
    assert result.reason_codes == tuple(sorted(set(result.reason_codes)))
    assert len(result.reason_codes) == 3


def test_missing_required_governance_revision_set_fails_closed():
    contracts = tuple(
        item for item in _request().governance_contracts if item.kind != "approval"
    )
    result = evaluate_authorization_drift(_request(governance_contracts=contracts))
    assert result.outcome is DriftOutcome.EVIDENCE_INCOMPLETE
    assert result.reason_codes == ("source.range-evidence-incomplete",)


def test_review_identity_binds_full_supplied_input_and_base_branch():
    first = evaluate_authorization_drift(_request())
    changed = evaluate_authorization_drift(
        _request(
            base_branch="release-main",
            range_evidence=RangeEvidence(A, B, ("docs/other.md",), provenance_ids=(EVIDENCE,)),
        )
    )
    assert first.request_fingerprint != changed.request_fingerprint
    assert first.review_id != changed.review_id
    assert first.original_base_branch == "main"
    assert changed.original_base_branch == "release-main"


def test_identical_inputs_produce_identical_serialization_and_identity():
    first = evaluate_authorization_drift(_request())
    second = evaluate_authorization_drift(_request())
    assert first.review_id == second.review_id
    assert first.to_json() == second.to_json()


def test_no_relevant_drift_builds_non_authorizing_refresh_handoff():
    review = evaluate_authorization_drift(_request())
    handoff = build_authorization_refresh_handoff(
        review,
        authorization_decision_target="existing-approval-owner",
    )
    assert not handoff.authorization_granted
    assert not handoff.side_effects_performed
    assert handoff.original_base_branch == "main"
    assert handoff.proposed_refreshed_base_sha == B
    assert handoff.revalidation_evidence_ids == ()


def test_revalidation_handoff_requires_completed_evidence():
    review = evaluate_authorization_drift(
        _request(
            range_evidence=RangeEvidence(
                A,
                B,
                ("scripts/agent_os_issue_acceptance/authorization_drift_review.py",),
                provenance_ids=(EVIDENCE,),
            )
        )
    )
    with pytest.raises(ValueError):
        build_authorization_refresh_handoff(review, authorization_decision_target="approval-owner")
    handoff = build_authorization_refresh_handoff(
        review,
        authorization_decision_target="approval-owner",
        revalidation_complete=True,
        revalidation_evidence_ids=(REVALIDATION,),
    )
    assert handoff.revalidation_evidence_ids == (REVALIDATION,)
    assert not handoff.authorization_granted


def test_blocking_outcomes_cannot_build_refresh_handoff():
    review = evaluate_authorization_drift(_request(forbidden_surface_implicated=True))
    with pytest.raises(ValueError):
        build_authorization_refresh_handoff(review, authorization_decision_target="approval-owner")


def test_module_has_no_external_io_imports():
    from scripts.agent_os_issue_acceptance import authorization_drift_review as module

    tree = ast.parse(inspect.getsource(module))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.add(node.module.split(".", 1)[0])
    assert imports <= {"__future__", "hashlib", "json", "re", "dataclasses", "enum", "typing"}
    assert imports.isdisjoint({"os", "pathlib", "subprocess", "socket", "requests", "urllib", "github"})
