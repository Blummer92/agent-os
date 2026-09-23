from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.agent_os_issue_acceptance.executor_route import ExecutorRoute
from scripts.agent_os_pr_remediation.high_reasoning_proposal import (
    AUTHORITY_FIELDS,
    EXISTING_EXECUTOR_ROUTES,
    PROPOSAL_SCHEMA_VERSION,
    REQUEST_SCHEMA_VERSION,
    ProposalOutcome,
    ProposalProviderUnavailable,
    ProposalRequest,
    ProposalType,
    evaluate_plan_currentness,
    propose_high_reasoning_plan,
    serialize_frozen_proposal,
)

SHA = "a" * 40
BASE_SHA = "b" * 40
AUTH_FP = "c" * 64
SOURCE_FP = "d" * 64


class FakeAdapter:
    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc
        self.calls = 0

    def propose(self, request_payload):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return self.response


def make_request(**changes):
    values = dict(
        schema_version=REQUEST_SCHEMA_VERSION,
        repository="Blummer92/agent-os",
        issue_number=1257,
        pr_number=None,
        invocation_id="issue-1257",
        source_sha=SHA,
        observed_source_sha=SHA,
        base_branch="main",
        base_sha=BASE_SHA,
        objective="Produce one bounded high-reasoning proposal.",
        non_goals=("No execution.", "No GitHub mutation."),
        allowed_paths=(
            "scripts/agent_os_pr_remediation/high_reasoning_proposal.py",
            "tests/agent_os_pr_remediation/test_high_reasoning_proposal.py",
        ),
        forbidden_paths=(".github/", "00_Governance/"),
        required_validations=("pytest-focused", "aggregate-exact-head"),
        required_prohibited_changes=("No new executor route.", "No external write."),
        blockers=(),
        changed_paths=(),
        compute_route="high-reasoning-required",
        authorization_state="authorized",
        authorization_fingerprint=AUTH_FP,
        proposal_type=ProposalType.EXECUTION,
        contract_versions=("prr2:1.0", "executor-route:1.0"),
        source_fingerprints=(SOURCE_FP,),
        normalized_evidence_refs=("evidence:current",),
        provider_capability_requirements=("high-reasoning",),
        human_evidence_state="clear",
    )
    values.update(changes)
    return ProposalRequest(**values)


def make_response(request, **changes):
    values = dict(
        schema_version=PROPOSAL_SCHEMA_VERSION,
        plan_type=request.proposal_type.value,
        request_fingerprint=request.request_fingerprint,
        provider_identity="fake-provider",
        model_identity="fake-high-reasoning-model",
        evidence_refs=list(request.normalized_evidence_refs),
        non_goals=list(request.non_goals),
        steps=[
            {
                "action": "edit",
                "summary": "Add the bounded proposal verifier.",
                "target_paths": [request.allowed_paths[0]],
                "validation_refs": ["pytest-focused"],
            },
            {
                "action": "validate",
                "summary": "Run the required focused validation.",
                "target_paths": [],
                "validation_refs": ["aggregate-exact-head"],
            },
        ],
        proposed_files=[request.allowed_paths[0]],
        prohibited_changes=list(request.required_prohibited_changes),
        validations=list(request.required_validations),
        blockers=list(request.blockers),
        rollback_concept="Revert the bounded proposal module and its tests.",
        executor_route_requirements=["governed_runner"],
        insufficiency_reason="The task was already classified high-reasoning-required.",
        uncertainty=[],
        expiry_condition="Expires when any bound request evidence changes.",
        invalidation_conditions=["Regenerate after any bound request evidence changes."],
        **{name: False for name in AUTHORITY_FIELDS},
    )
    values.update(changes)
    return values


def test_valid_execution_proposal_is_frozen_and_non_authorizing():
    request = make_request()
    adapter = FakeAdapter(make_response(request))
    result = propose_high_reasoning_plan(request, adapter)
    assert result.outcome is ProposalOutcome.ACCEPTED
    assert result.plan is not None
    assert result.plan.plan_type is ProposalType.EXECUTION
    assert result.plan.plan_id.startswith("high-reasoning-proposal:")
    assert all(getattr(result.plan, name) is False for name in AUTHORITY_FIELDS)
    assert adapter.calls == 1


def test_valid_repair_proposal_preserves_exact_failure_evidence():
    request = make_request(
        proposal_type=ProposalType.REPAIR,
        pr_number=1300,
        normalized_evidence_refs=("failure:abc", "review:def"),
    )
    result = propose_high_reasoning_plan(request, FakeAdapter(make_response(request)))
    assert result.outcome is ProposalOutcome.ACCEPTED
    assert result.plan is not None
    assert result.plan.plan_type is ProposalType.REPAIR
    assert result.plan.evidence_refs == ("failure:abc", "review:def")
    assert all(getattr(result.plan, name) is False for name in AUTHORITY_FIELDS)


def test_identical_evidence_and_fake_response_are_deterministic():
    request = make_request()
    first = propose_high_reasoning_plan(request, FakeAdapter(make_response(request)))
    second = propose_high_reasoning_plan(request, FakeAdapter(make_response(request)))
    assert first.plan == second.plan
    assert first.plan is not None and second.plan is not None
    assert first.plan.plan_id == second.plan.plan_id
    assert serialize_frozen_proposal(first.plan) == serialize_frozen_proposal(second.plan)


def test_non_high_reasoning_route_does_not_invoke_adapter():
    request = make_request(compute_route="no-model")
    adapter = FakeAdapter(make_response(make_request()))
    result = propose_high_reasoning_plan(request, adapter)
    assert result.outcome is ProposalOutcome.NEEDS_DECISION
    assert result.reason_codes == ("route.not-high-reasoning",)
    assert result.plan is None
    assert adapter.calls == 0


@pytest.mark.parametrize(
    ("state", "fingerprint", "reason"),
    [
        ("missing", None, "authorization.missing-evidence"),
        ("ambiguous", AUTH_FP, "authorization.ambiguous"),
        ("stale", AUTH_FP, "authorization.stale"),
        ("not-authorized", AUTH_FP, "authorization.not-authorized"),
        ("authorized", None, "authorization.missing-evidence"),
    ],
)
def test_missing_or_ambiguous_authority_fails_closed_without_adapter(state, fingerprint, reason):
    request = make_request(authorization_state=state, authorization_fingerprint=fingerprint)
    adapter = FakeAdapter(make_response(make_request()))
    result = propose_high_reasoning_plan(request, adapter)
    assert result.outcome is ProposalOutcome.MANUAL_REVIEW
    assert result.reason_codes == (reason,)
    assert result.plan is None
    assert adapter.calls == 0


def test_stale_source_fails_closed_without_adapter():
    request = make_request(observed_source_sha="e" * 40)
    adapter = FakeAdapter(make_response(make_request()))
    result = propose_high_reasoning_plan(request, adapter)
    assert result.outcome is ProposalOutcome.MANUAL_REVIEW
    assert result.reason_codes == ("source.stale",)
    assert adapter.calls == 0


def test_scope_expanding_proposal_is_rejected():
    request = make_request()
    result = propose_high_reasoning_plan(
        request,
        FakeAdapter(make_response(request, proposed_files=["scripts/unrelated.py"])),
    )
    assert result.outcome is ProposalOutcome.REJECTED
    assert result.reason_codes == ("proposal.scope-expansion",)


def test_forbidden_surface_proposal_is_rejected_even_if_allowlisted():
    request = make_request(allowed_paths=(".github/workflows/test.yml",))
    response = make_response(
        request,
        proposed_files=[".github/workflows/test.yml"],
        steps=[
            {
                "action": "edit",
                "summary": "Change workflow behavior.",
                "target_paths": [".github/workflows/test.yml"],
                "validation_refs": ["pytest-focused"],
            }
        ],
    )
    result = propose_high_reasoning_plan(request, FakeAdapter(response))
    assert result.outcome is ProposalOutcome.REJECTED
    assert result.reason_codes == ("proposal.forbidden-surface",)


def test_invented_fifth_executor_route_is_rejected():
    request = make_request()
    result = propose_high_reasoning_plan(
        request,
        FakeAdapter(make_response(request, executor_route_requirements=["claude_engine"])),
    )
    assert result.outcome is ProposalOutcome.REJECTED
    assert result.reason_codes == ("proposal.unknown-executor-route",)


@pytest.mark.parametrize("authority_field", AUTHORITY_FIELDS)
def test_any_claimed_authority_is_rejected(authority_field):
    request = make_request()
    response = make_response(request)
    response[authority_field] = True
    result = propose_high_reasoning_plan(request, FakeAdapter(response))
    assert result.outcome is ProposalOutcome.REJECTED
    assert result.reason_codes == ("proposal.invented-authority",)


def test_shell_like_or_command_shaped_content_is_rejected():
    request = make_request()
    response = make_response(request)
    response["steps"][0]["summary"] = "Run rm -rf /tmp; then continue"
    result = propose_high_reasoning_plan(request, FakeAdapter(response))
    assert result.outcome is ProposalOutcome.REJECTED
    assert result.reason_codes == ("proposal.executable-content",)

    response = make_response(request)
    response["command"] = "pytest"
    result = propose_high_reasoning_plan(request, FakeAdapter(response))
    assert result.outcome is ProposalOutcome.REJECTED
    assert result.reason_codes == ("proposal.malformed",)


@pytest.mark.parametrize(
    ("mutator", "reason"),
    [
        (lambda r: r.update(schema_version="9.9"), "proposal.unsupported-schema"),
        (lambda r: r.pop("steps"), "proposal.malformed"),
        (lambda r: r.update(uncertainty=["x" * 4096 for _ in range(40)]), "proposal.oversized"),
    ],
)
def test_malformed_oversized_or_unknown_schema_response_is_rejected(mutator, reason):
    request = make_request()
    response = make_response(request)
    mutator(response)
    result = propose_high_reasoning_plan(request, FakeAdapter(response))
    assert result.outcome is ProposalOutcome.REJECTED
    assert result.reason_codes == (reason,)


def test_conflicting_human_evidence_routes_to_manual_review():
    request = make_request(human_evidence_state="conflicting")
    adapter = FakeAdapter(make_response(make_request()))
    result = propose_high_reasoning_plan(request, adapter)
    assert result.outcome is ProposalOutcome.MANUAL_REVIEW
    assert result.reason_codes == ("human-evidence.conflicting",)
    assert adapter.calls == 0


def test_provider_unavailability_returns_needs_decision_without_fake_success():
    request = make_request()
    adapter = FakeAdapter(exc=ProposalProviderUnavailable("offline"))
    result = propose_high_reasoning_plan(request, adapter)
    assert result.outcome is ProposalOutcome.NEEDS_DECISION
    assert result.reason_codes == ("provider.unavailable",)
    assert result.plan is None
    assert adapter.calls == 1


def test_repair_evidence_change_invalidates_existing_plan():
    request = make_request(
        proposal_type=ProposalType.REPAIR,
        pr_number=1300,
        normalized_evidence_refs=("failure:abc",),
    )
    result = propose_high_reasoning_plan(request, FakeAdapter(make_response(request)))
    assert result.plan is not None
    changed = replace(request, normalized_evidence_refs=("failure:changed",))
    currentness = evaluate_plan_currentness(result.plan, changed)
    assert currentness.current is False
    assert currentness.reason_codes == ("proposal.stale",)


def test_source_or_head_change_invalidates_existing_plan():
    request = make_request()
    result = propose_high_reasoning_plan(request, FakeAdapter(make_response(request)))
    assert result.plan is not None
    changed_sha = "e" * 40
    changed = replace(request, source_sha=changed_sha, observed_source_sha=changed_sha)
    currentness = evaluate_plan_currentness(result.plan, changed)
    assert currentness.current is False
    assert currentness.reason_codes == ("proposal.stale",)


def test_bound_scope_or_contract_change_invalidates_existing_plan():
    request = make_request()
    result = propose_high_reasoning_plan(request, FakeAdapter(make_response(request)))
    assert result.plan is not None
    changed = replace(request, contract_versions=("prr2:2.0",))
    assert evaluate_plan_currentness(result.plan, changed).current is False


def test_module_is_offline_and_contains_no_runtime_or_write_dependencies():
    module_path = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "agent_os_pr_remediation"
        / "high_reasoning_proposal.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported.update(
        node.module.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0
    )
    assert imported.isdisjoint(
        {"requests", "httpx", "urllib", "socket", "subprocess", "os", "pathlib", "github"}
    )


def test_existing_four_executor_routes_are_semantically_unchanged():
    assert {route.value for route in ExecutorRoute} == EXISTING_EXECUTOR_ROUTES


def test_missing_required_validation_is_rejected():
    request = make_request()
    result = propose_high_reasoning_plan(
        request,
        FakeAdapter(make_response(request, validations=["pytest-focused"])),
    )
    assert result.outcome is ProposalOutcome.REJECTED
    assert result.reason_codes == ("proposal.required-validation-missing",)


def test_frozen_non_goal_or_prohibited_change_cannot_be_omitted():
    request = make_request()
    response = make_response(request, non_goals=["No execution."])
    result = propose_high_reasoning_plan(request, FakeAdapter(response))
    assert result.reason_codes == ("proposal.constraint-missing",)

    response = make_response(request, prohibited_changes=["No new executor route."])
    result = propose_high_reasoning_plan(request, FakeAdapter(response))
    assert result.reason_codes == ("proposal.constraint-missing",)


def test_repair_proposal_cannot_substitute_different_failure_evidence():
    request = make_request(
        proposal_type=ProposalType.REPAIR,
        pr_number=1300,
        normalized_evidence_refs=("failure:abc",),
    )
    response = make_response(request, evidence_refs=["failure:def"])
    result = propose_high_reasoning_plan(request, FakeAdapter(response))
    assert result.outcome is ProposalOutcome.REJECTED
    assert result.reason_codes == ("proposal.repair-evidence-mismatch",)
