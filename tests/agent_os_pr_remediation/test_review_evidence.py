import pytest

from scripts.agent_os_pr_remediation.models import EvidenceValidationError
from scripts.agent_os_pr_remediation.review_evidence import (
    ReviewDepth,
    ReviewRiskEvidence,
    build_review_evidence_packet,
    review_invalidation_scope,
    select_review_depth,
)


def _risk(name: str) -> ReviewRiskEvidence:
    return ReviewRiskEvidence(name, (f"changed:{name}",))


def _packet(**overrides):
    payload = {
        "repository": "Blummer92/agent-os",
        "issue_number": 1537,
        "pr_number": 1600,
        "base_sha": "a" * 40,
        "head_sha": "b" * 40,
        "metadata_fingerprint": "c" * 64,
        "objective": "Bound review compute while preserving correctness review.",
        "acceptance_criteria": ["normal review is default"],
        "allowed_paths": ["scripts/agent_os_pr_remediation/"],
        "forbidden_paths": [".github/workflows/"],
        "non_goals": ["no provider configuration"],
        "authorization_ceiling": ["no-external-write"],
        "changed_files": ["scripts/agent_os_pr_remediation/review_evidence.py"],
        "bounded_diff": "@@ bounded diff @@",
        "changed_contracts": ["review-depth-v1"],
        "dependency_changes": [],
        "workflow_changes": [],
        "risk_evidence": [_risk("parser")],
        "validation_profiles": ["tests/agent_os_pr_remediation/test_review_evidence.py"],
        "validation_results": ["focused:pass"],
        "exact_tested_sha": "b" * 40,
        "failed_finding_ids": [],
        "repaired_finding_ids": [],
        "unresolved_finding_ids": [],
        "prior_reviewed_head": "a" * 40,
        "paths_changed_since_review": ["scripts/agent_os_pr_remediation/review_evidence.py"],
        "activated_references": ["high-reasoning-proposal-contract"],
        "review_depth": ReviewDepth.ADVERSARIAL,
    }
    payload.update(overrides)
    return build_review_evidence_packet(**payload)


def test_ordinary_code_change_gets_one_normal_review():
    decision = select_review_depth(
        changed_files=["src/example.py"], change_kinds=["implementation"], risk_evidence=[]
    )
    assert decision.depth is ReviewDepth.NORMAL
    assert decision.execution_authorized is False
    assert decision.merge_authorized is False


def test_parser_authorization_change_escalates_to_adversarial():
    decision = select_review_depth(
        changed_files=["parser.py"],
        change_kinds=["implementation"],
        risk_evidence=[_risk("parser"), _risk("authorization")],
    )
    assert decision.depth is ReviewDepth.ADVERSARIAL


def test_workflow_permission_change_escalates_to_adversarial():
    decision = select_review_depth(
        changed_files=[".github/workflows/validate.yml"],
        change_kinds=["workflow"],
        risk_evidence=[_risk("workflow-ci-authority"), _risk("permissions")],
    )
    assert decision.depth is ReviewDepth.ADVERSARIAL


def test_markdown_only_change_uses_no_ai():
    decision = select_review_depth(
        changed_files=["README.md"], change_kinds=["markdown-only"], code_changed=False
    )
    assert decision.depth is ReviewDepth.NO_AI


def test_deterministic_failure_runs_before_ai_review():
    decision = select_review_depth(
        changed_files=["src/example.py"],
        change_kinds=["implementation"],
        risk_evidence=[_risk("parser")],
        deterministic_failure=True,
    )
    assert decision.depth is ReviewDepth.NO_AI
    assert decision.reasons == ("deterministic-failure-first",)


def test_trivial_repair_invalidates_only_impacted_review_path():
    invalidated = review_invalidation_scope(
        prior_reviewed_head="a" * 40,
        current_head="b" * 40,
        changed_paths_since_review=["src/a.py"],
        material_change_kinds=["finding-repair"],
        previously_reviewed_paths=["src/a.py", "src/b.py"],
    )
    assert invalidated == ("src/a.py",)


def test_public_interface_repair_invalidates_full_review_surface():
    invalidated = review_invalidation_scope(
        prior_reviewed_head="a" * 40,
        current_head="b" * 40,
        changed_paths_since_review=["src/a.py"],
        material_change_kinds=["public-interface"],
        previously_reviewed_paths=["src/a.py", "src/b.py"],
    )
    assert invalidated == ("src/a.py", "src/b.py")


def test_same_head_preserves_review_evidence():
    invalidated = review_invalidation_scope(
        prior_reviewed_head="a" * 40,
        current_head="a" * 40,
        changed_paths_since_review=[],
        material_change_kinds=[],
        previously_reviewed_paths=["src/a.py"],
    )
    assert invalidated == ()


def test_packet_is_bounded_and_excludes_unrequested_history():
    packet = _packet()
    data = packet.to_dict()
    assert "repository_history" not in data
    assert "full_test_suite" not in data
    assert "unrelated_comments" not in data
    assert len(packet.bounded_diff) < 64_000
    assert packet.execution_authorized is False
    assert packet.external_write_authorized is False


def test_oversized_diff_is_rejected():
    with pytest.raises(EvidenceValidationError):
        _packet(bounded_diff="x" * 64_001)


def test_stale_or_conflicting_risk_evidence_fails_closed():
    decision = select_review_depth(
        changed_files=["src/a.py"],
        change_kinds=["implementation"],
        risk_evidence=[_risk("parser")],
        stale_or_conflicting_risk_evidence=True,
    )
    assert decision.depth is ReviewDepth.MANUAL


def test_packet_identity_changes_with_head():
    first = _packet()
    second = _packet(head_sha="d" * 40, exact_tested_sha="d" * 40)
    assert first.packet_id != second.packet_id
