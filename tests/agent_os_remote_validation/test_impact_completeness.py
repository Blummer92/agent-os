from scripts.agent_os_remote_validation.impact_completeness import (
    ImpactCouplingRule,
    evaluate_impact_completeness,
    impact_completeness_result_id,
    serialize_impact_completeness,
)

ARTIFACT_RULE = ImpactCouplingRule(
    name="artifact-first-contract",
    trigger_paths=(
        "01_Shared_Standards/instructional-design/artifact-first-response-standard.md",
    ),
    required_companion_paths=("tests/test_agent_interaction_output_standard.py",),
)

MCP_RULE = ImpactCouplingRule(
    name="bounded-mcp-surface",
    trigger_paths=("08_Tooling/agent-os-execution-service/src/agent_os_execution_service/mcp_server.py",),
    required_companion_paths=(
        "08_Tooling/agent-os-execution-service/tests/test_mcp_server.py",
    ),
)

LIFECYCLE_RULE = ImpactCouplingRule(
    name="lifecycle-admission-callers",
    trigger_paths=(
        "scripts/agent_os_issue_labels/issue_reconciler.py",
        "scripts/agent_os_issue_labels/pr_reconciler.py",
        "scripts/agent_os_issue_labels/pr_lifecycle.py",
    ),
    scan_prefixes=("scripts/agent_os_issue_labels/", "tests/agent_os_issue_labels/"),
    forbidden_tokens=("label_write_authorized=True",),
)


def evaluate(changed, rules, repository_text=None):
    return evaluate_impact_completeness(
        changed_files=tuple(changed),
        rules=tuple(rules),
        repository_text=repository_text,
    )


def test_governed_artifact_without_pinning_contract_is_incomplete():
    result = evaluate(
        ["01_Shared_Standards/instructional-design/artifact-first-response-standard.md"],
        [ARTIFACT_RULE],
    )
    assert result.status == "incomplete"
    assert result.aggregate_escalation_required is True
    assert result.incomplete_families == ("artifact-first-contract",)


def test_governed_artifact_and_pinning_contract_move_together():
    result = evaluate(
        [
            "tests/test_agent_interaction_output_standard.py",
            "01_Shared_Standards/instructional-design/artifact-first-response-standard.md",
        ],
        [ARTIFACT_RULE],
    )
    assert result.status == "complete"
    assert result.aggregate_escalation_required is False


def test_mcp_surface_expansion_without_contract_test_replays_2219_class():
    result = evaluate(
        ["08_Tooling/agent-os-execution-service/src/agent_os_execution_service/mcp_server.py"],
        [MCP_RULE],
    )
    assert result.status == "incomplete"
    assert "impact.bounded-mcp-surface.companion-missing" in result.reason_codes


def test_mcp_surface_and_exact_contract_move_together():
    result = evaluate(
        [
            "08_Tooling/agent-os-execution-service/tests/test_mcp_server.py",
            "08_Tooling/agent-os-execution-service/src/agent_os_execution_service/mcp_server.py",
        ],
        [MCP_RULE],
    )
    assert result.status == "complete"


def test_retired_lifecycle_interface_replays_2218_class():
    result = evaluate(
        ["scripts/agent_os_issue_labels/pr_reconciler.py"],
        [LIFECYCLE_RULE],
        {
            "scripts/agent_os_issue_labels/pr_reconciler.py": "new lifecycle_admission",
            "tests/agent_os_issue_labels/test_pr_reconciler.py": "label_write_authorized=True",
        },
    )
    assert result.status == "incomplete"
    assert "impact.lifecycle-admission-callers.retired-interface-present" in result.reason_codes


def test_all_mechanically_known_lifecycle_callers_migrated():
    result = evaluate(
        ["scripts/agent_os_issue_labels/pr_reconciler.py"],
        [LIFECYCLE_RULE],
        {
            "scripts/agent_os_issue_labels/pr_reconciler.py": "lifecycle_admission=admission",
            "tests/agent_os_issue_labels/test_pr_reconciler.py": "lifecycle_admission=admission",
        },
    )
    assert result.status == "complete"


def test_missing_bounded_scan_evidence_fails_closed_to_aggregate():
    result = evaluate(
        ["scripts/agent_os_issue_labels/pr_lifecycle.py"],
        [LIFECYCLE_RULE],
    )
    assert result.status == "incomplete"
    assert result.aggregate_escalation_required is True
    assert "impact.lifecycle-admission-callers.scan-evidence-missing" in result.reason_codes


def test_unrelated_change_is_cheap_noop():
    result = evaluate(["README.md"], [ARTIFACT_RULE, MCP_RULE, LIFECYCLE_RULE])
    assert result.status == "not-applicable"
    assert result.aggregate_escalation_required is False


def test_ambiguous_family_routes_to_manual_review_not_guessed_failure():
    rule = ImpactCouplingRule(
        name="prose-only-relationship",
        trigger_paths=("docs/architecture.md",),
        ambiguous=True,
    )
    result = evaluate(["docs/architecture.md"], [rule])
    assert result.status == "manual-review"
    assert result.aggregate_escalation_required is True


def test_unknown_family_is_not_silently_claimed_complete():
    result = evaluate(["new/unmapped/executable.py"], [ARTIFACT_RULE])
    assert result.status == "not-applicable"
    # #2235's canonical selector remains responsible for unmapped executable
    # escalation; this impact layer never invents coverage it does not own.
    assert result.applicable_families == ()


def test_result_is_order_independent_and_content_addressed():
    changed_a = (
        "tests/test_agent_interaction_output_standard.py",
        "01_Shared_Standards/instructional-design/artifact-first-response-standard.md",
    )
    changed_b = tuple(reversed(changed_a))
    first = evaluate(changed_a, [MCP_RULE, ARTIFACT_RULE])
    second = evaluate(changed_b, [ARTIFACT_RULE, MCP_RULE])
    assert first == second
    assert first.authoritative is False
    assert first.execution_authorized is False
    assert first.merge_authorized is False
    assert first.side_effects_performed is False
    assert impact_completeness_result_id(first) == first.result_id
    assert serialize_impact_completeness(first)["status"] == "complete"


def test_invalid_catalog_fails_closed():
    duplicate = (ARTIFACT_RULE, ARTIFACT_RULE)
    result = evaluate_impact_completeness(
        changed_files=("README.md",),
        rules=duplicate,
    )
    assert result.status == "manual-review"
    assert result.aggregate_escalation_required is True
