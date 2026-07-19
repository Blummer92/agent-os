from scripts.agent_os_issue_acceptance.models import AcceptanceReport, CheckResult, Status
from scripts.agent_os_issue_acceptance.readiness import (
    ReadinessOutcome,
    evaluate_issue_readiness,
    evaluate_issue_readiness_with_labels,
)
from scripts.agent_os_issue_acceptance.report import exit_code_for


def ready_body(extra: str = "") -> str:
    return f"""
Issue Tier: 0
## Objective
Update documentation.
## Owner
QA / Test Agent
## Allowed Files
- docs/example.md
## Validation
- markdown check
## Completion Criterion
- Text is corrected.
## Documentation impact
docs-not-required
## Documentation exemption reason
This change does not alter documented behavior or operator guidance.
{extra}
"""


def base_body(doc_section: str = "", *, extra: str = "") -> str:
    """A ready-shaped Tier 0 body with no built-in documentation-impact evidence."""
    return f"""
Issue Tier: 0
## Objective
Update documentation.
## Owner
QA / Test Agent
## Allowed Files
- docs/example.md
## Validation
- markdown check
## Completion Criterion
- Text is corrected.
{doc_section}
{extra}
"""


def _doc_check(result) -> CheckResult:
    return next(check for check in result.report.checks if check.name == "documentation impact")


def label_report(status: Status) -> AcceptanceReport:
    return AcceptanceReport(
        linked_issue=None,
        overall_status=status,
        checks=[CheckResult("label evidence", status, "label evidence result")],
        manual_review_items=["review label evidence"] if status == Status.MANUAL_REVIEW else [],
        blockers=["label map is unsafe"] if status == Status.FAIL else [],
        evidence=["labels=read-only"],
        remaining_risks=["Label evidence does not authorize writes."],
    )


def test_existing_ready_behavior_remains_ready():
    assert evaluate_issue_readiness(ready_body()).outcome == ReadinessOutcome.READY


def test_conflicting_source_of_truth_requires_decision():
    body = ready_body(
        """
## Source Of Truth
GitHub
```yaml
agent_os_issue_acceptance:
  tier: 0
  source_of_truth: Notion
```
"""
    )
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.NEEDS_DECISION
    assert any(check.name == "source-of-truth evidence" for check in result.report.checks)


def test_matching_source_of_truth_preserves_ready():
    body = ready_body(
        """
## Source Of Truth
GitHub
```yaml
agent_os_issue_acceptance:
  tier: 0
  source_of_truth: github
```
"""
    )
    assert evaluate_issue_readiness(body).outcome == ReadinessOutcome.READY


def test_required_file_under_forbidden_path_is_blocked():
    body = ready_body(
        """
```yaml
agent_os_issue_acceptance:
  tier: 0
  required_files:
    - production/secrets.txt
  forbidden_paths:
    - production
```
"""
    )
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.BLOCKED
    assert "Required files include declared forbidden paths." in result.report.blockers


def test_nonviolating_required_file_preserves_ready():
    body = ready_body(
        """
```yaml
agent_os_issue_acceptance:
  tier: 0
  required_files:
    - docs/example.md
  forbidden_paths:
    - production
```
"""
    )
    assert evaluate_issue_readiness(body).outcome == ReadinessOutcome.READY


def test_leading_dot_path_and_segment_wildcard_are_preserved():
    body = ready_body(
        """
```yaml
agent_os_issue_acceptance:
  tier: 0
  required_files:
    - .github/workflows/check.yml
  forbidden_paths:
    - .github/workflows/*.yml
```
"""
    )
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.BLOCKED
    forbidden_check = next(
        check for check in result.report.checks if check.name == "declared forbidden paths"
    )
    assert forbidden_check.evidence == [".github/workflows/check.yml"]


def test_sibling_prefix_does_not_conflict():
    body = ready_body(
        """
```yaml
agent_os_issue_acceptance:
  tier: 0
  required_files:
    - production-old/config.yml
  forbidden_paths:
    - production
```
"""
    )
    assert evaluate_issue_readiness(body).outcome == ReadinessOutcome.READY


def test_malformed_only_path_evidence_requires_decision():
    body = ready_body(
        """
```yaml
agent_os_issue_acceptance:
  tier: 0
  required_files:
    - ../production/secrets.txt
  forbidden_paths:
    - production
```
"""
    )
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.NEEDS_DECISION
    syntax_check = next(
        check for check in result.report.checks if check.name == "declared path syntax"
    )
    assert syntax_check.status == Status.MANUAL_REVIEW
    assert syntax_check.evidence == [
        "field=required_files; value='../production/secrets.txt'; code=traversal"
    ]
    assert any("code=traversal" in item for item in result.report.manual_review_items)


def test_malformed_and_valid_forbidden_conflict_preserve_both_findings():
    body = ready_body(
        """
```yaml
agent_os_issue_acceptance:
  tier: 0
  required_files:
    - ../ignored.txt
    - production/secrets.txt
  forbidden_paths:
    - production
```
"""
    )
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.BLOCKED
    checks = {check.name: check for check in result.report.checks}
    assert checks["declared path syntax"].status == Status.MANUAL_REVIEW
    assert checks["declared forbidden paths"].status == Status.FAIL
    assert checks["declared forbidden paths"].evidence == ["production/secrets.txt"]
    assert any("code=traversal" in item for item in result.report.manual_review_items)


def test_unsupported_pattern_requires_decision_and_valid_values_continue():
    body = ready_body(
        """
```yaml
agent_os_issue_acceptance:
  tier: 0
  required_files:
    - docs/example.md
    - production/secrets.txt
  forbidden_paths:
    - docs/**
    - production
```
"""
    )
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.BLOCKED
    checks = {check.name: check for check in result.report.checks}
    assert checks["declared path syntax"].evidence == [
        "field=forbidden_paths; value='docs/**'; code=unsupported-double-star"
    ]
    assert checks["declared forbidden paths"].evidence == ["production/secrets.txt"]


def test_path_evidence_order_is_deterministic():
    body = ready_body(
        """
```yaml
agent_os_issue_acceptance:
  tier: 0
  required_files:
    - ../z.txt
    - /a.txt
  forbidden_paths:
    - src/**
```
"""
    )
    first = evaluate_issue_readiness(body)
    second = evaluate_issue_readiness(body)
    first_syntax = next(
        check for check in first.report.checks if check.name == "declared path syntax"
    )
    second_syntax = next(
        check for check in second.report.checks if check.name == "declared path syntax"
    )
    assert first_syntax.evidence == second_syntax.evidence
    assert first.report.manual_review_items == second.report.manual_review_items


def test_pass_label_evidence_supports_ready_result():
    result = evaluate_issue_readiness_with_labels(ready_body(), label_report(Status.PASS))
    assert result.outcome == ReadinessOutcome.READY
    assert "label_evidence_consumed=true" in result.report.evidence


def test_warn_label_evidence_is_advisory_and_stays_ready():
    result = evaluate_issue_readiness_with_labels(ready_body(), label_report(Status.WARN))
    assert result.outcome == ReadinessOutcome.READY


def test_unknown_label_evidence_requires_decision():
    result = evaluate_issue_readiness_with_labels(
        ready_body(), label_report(Status.MANUAL_REVIEW)
    )
    assert result.outcome == ReadinessOutcome.NEEDS_DECISION
    assert "review label evidence" in result.report.manual_review_items


def test_failed_label_map_contract_blocks():
    result = evaluate_issue_readiness_with_labels(ready_body(), label_report(Status.FAIL))
    assert result.outcome == ReadinessOutcome.BLOCKED
    assert "label map is unsafe" in result.report.blockers


# --- DOC2B: documentation-impact readiness evidence -----------------------------


def test_docs_required_with_valid_evidence_is_ready():
    body = base_body(
        """
## Documentation impact
docs-required
## Required documentation paths or bounded areas
01_Shared_Standards/github
docs/example.md
## Expected documentation change
Explain the new operator behavior.
"""
    )
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.READY
    check = _doc_check(result)
    assert check.status == Status.PASS
    assert "evidence_path=01_Shared_Standards/github" in check.evidence
    assert "evidence_path=docs/example.md" in check.evidence
    assert "expected_change_present=true" in check.evidence


def test_docs_required_missing_all_paths_is_blocked():
    body = base_body(
        """
## Documentation impact
docs-required
## Expected documentation change
Explain the new operator behavior.
"""
    )
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.BLOCKED
    check = _doc_check(result)
    assert check.status == Status.FAIL
    assert "field=required_docs; code=documentation-path-missing" in check.evidence


def test_docs_required_missing_expected_change_is_blocked():
    body = base_body(
        """
## Documentation impact
docs-required
## Required documentation paths or bounded areas
docs/example.md
"""
    )
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.BLOCKED
    check = _doc_check(result)
    assert check.status == Status.FAIL
    assert "field=documentation_expected_change; code=documentation-expected-change-missing" in check.evidence


def test_docs_required_with_malformed_path_requires_decision():
    body = base_body(
        """
## Documentation impact
docs-required
## Required documentation paths or bounded areas
../secrets.txt
## Expected documentation change
Explain the new operator behavior.
"""
    )
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.NEEDS_DECISION
    check = _doc_check(result)
    assert check.status == Status.MANUAL_REVIEW
    assert "field=required_docs; value='../secrets.txt'; code=traversal" in check.evidence


def test_docs_required_with_exemption_reason_requires_decision():
    body = base_body(
        """
## Documentation impact
docs-required
## Required documentation paths or bounded areas
docs/example.md
## Expected documentation change
Explain the new operator behavior.
## Documentation exemption reason
Not needed.
"""
    )
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.NEEDS_DECISION
    check = _doc_check(result)
    assert check.status == Status.MANUAL_REVIEW
    assert "field=documentation_exemption_reason; code=documentation-exemption-conflict" in check.evidence


def test_docs_not_required_with_valid_reason_is_ready():
    body = base_body(
        """
## Documentation impact
docs-not-required
## Documentation exemption reason
No operator-visible behavior changes.
"""
    )
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.READY
    check = _doc_check(result)
    assert check.status == Status.PASS
    assert "exemption_reason_present=true" in check.evidence


def test_docs_not_required_missing_reason_requires_decision():
    body = base_body(
        """
## Documentation impact
docs-not-required
"""
    )
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.NEEDS_DECISION
    check = _doc_check(result)
    assert "field=documentation_exemption_reason; code=documentation-exemption-missing" in check.evidence


def test_docs_not_required_with_paths_requires_decision():
    body = base_body(
        """
## Documentation impact
docs-not-required
## Documentation exemption reason
No operator-visible behavior changes.
## Required documentation paths or bounded areas
docs/example.md
"""
    )
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.NEEDS_DECISION
    check = _doc_check(result)
    assert any(
        item.startswith("field=required_docs; code=documentation-path-conflict")
        for item in check.evidence
    )


def test_docs_not_required_with_expected_change_requires_decision():
    body = base_body(
        """
## Documentation impact
docs-not-required
## Documentation exemption reason
No operator-visible behavior changes.
## Expected documentation change
Explain something anyway.
"""
    )
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.NEEDS_DECISION
    check = _doc_check(result)
    assert "field=documentation_expected_change; code=documentation-expected-change-conflict" in check.evidence


def test_docs_needs_decision_requires_decision_without_tripping_unrelated_logic():
    body = base_body(
        """
## Documentation impact
docs-needs-decision
"""
    )
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.NEEDS_DECISION
    check = _doc_check(result)
    assert check.evidence == ["field=documentation_impact; code=documentation-needs-decision"]
    # The generic "unresolved decisions" check is a distinct, independent finding.
    assert not any(c.name == "unresolved decisions" for c in result.report.checks)


def test_missing_documentation_impact_requires_decision():
    body = base_body()
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.NEEDS_DECISION
    check = _doc_check(result)
    assert check.evidence == ["field=documentation_impact; code=legacy-metadata-missing"]


def test_unknown_documentation_impact_value_requires_decision():
    body = base_body(
        """
## Documentation impact
docs-maybe
"""
    )
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.NEEDS_DECISION
    check = _doc_check(result)
    assert check.evidence == ["field=documentation_impact; code=documentation-impact-unknown"]


def test_yaml_only_evidence_is_used():
    body = base_body(
        extra="""
```yaml
agent_os_issue_acceptance:
  tier: 0
  documentation_impact: docs-not-required
  documentation_exemption_reason: No behavior changes.
```
"""
    )
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.READY
    check = _doc_check(result)
    assert check.status == Status.PASS


def test_body_section_only_evidence_is_used():
    body = base_body(
        """
## Documentation impact
docs-not-required
## Documentation exemption reason
No behavior changes.
"""
    )
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.READY


def test_equivalent_dual_source_evidence_dedupes_to_ready():
    body = base_body(
        """
## Documentation impact
docs-not-required
## Documentation exemption reason
No   behavior   changes.
""",
        extra="""
```yaml
agent_os_issue_acceptance:
  tier: 0
  documentation_impact: docs-not-required
  documentation_exemption_reason: No behavior changes.
```
""",
    )
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.READY


def test_conflicting_dual_source_evidence_requires_decision():
    body = base_body(
        """
## Documentation impact
docs-not-required
""",
        extra="""
```yaml
agent_os_issue_acceptance:
  tier: 0
  documentation_impact: docs-required
```
""",
    )
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.NEEDS_DECISION
    check = _doc_check(result)
    assert check.evidence == [
        "field=documentation_impact; code=documentation-source-conflict; "
        "yaml_present=true; body_present=true"
    ]


def test_duplicate_documentation_impact_heading_requires_decision():
    body = base_body(
        """
## Documentation impact
docs-not-required
## Documentation impact
docs-required
"""
    )
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.NEEDS_DECISION
    check = _doc_check(result)
    assert check.evidence == ["field=documentation_impact; code=duplicate-heading; count=2"]


def test_identical_duplicate_heading_content_still_requires_decision():
    body = base_body(
        """
## Documentation impact
docs-not-required
## Documentation impact
docs-not-required
"""
    )
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.NEEDS_DECISION
    check = _doc_check(result)
    assert check.evidence == ["field=documentation_impact; code=duplicate-heading; count=2"]


def test_duplicate_heading_hidden_in_fence_comment_or_blockquote_is_ignored():
    body = base_body(
        """
## Documentation impact
docs-not-required
## Documentation exemption reason
No behavior changes.

<!--
## Documentation impact
docs-required
-->
> ## Documentation impact
> docs-required
```text
## Documentation impact
docs-required
```
"""
    )
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.READY
    check = _doc_check(result)
    assert not any("duplicate-heading" in item for item in check.evidence)


def test_multiple_live_values_under_scalar_heading_requires_decision():
    body = base_body(
        """
## Documentation impact
docs-required
docs-not-required
"""
    )
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.NEEDS_DECISION
    check = _doc_check(result)
    assert check.evidence == [
        "field=documentation_impact; code=documentation-source-conflict; "
        "yaml_present=false; body_present=true"
    ]


def test_stronger_existing_blocker_remains_blocked_despite_valid_documentation_evidence():
    body = f"""
Issue Tier: 1
## Objective
Add a local report-only checker.
## Owner
QA / Test Agent
## Documentation impact
docs-not-required
## Documentation exemption reason
No behavior changes.
"""
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.BLOCKED
    check = _doc_check(result)
    assert check.status == Status.PASS


def test_documentation_evidence_and_ordering_is_deterministic():
    body = base_body(
        """
## Documentation impact
docs-required
## Required documentation paths or bounded areas
docs/example.md
01_Shared_Standards/github
## Expected documentation change
Explain the operator-visible change.
"""
    )
    first = _doc_check(evaluate_issue_readiness(body))
    second = _doc_check(evaluate_issue_readiness(body))
    assert first.evidence == second.evidence


def test_consumer_can_locate_documentation_check_without_reparsing_body():
    body = base_body(
        """
## Documentation impact
docs-not-required
## Documentation exemption reason
No behavior changes.
"""
    )
    result = evaluate_issue_readiness(body)
    matches = [check for check in result.report.checks if check.name == "documentation impact"]
    assert len(matches) == 1
    assert matches[0].status == Status.PASS


def test_manual_review_documentation_outcome_keeps_zero_exit_code():
    body = base_body(
        """
## Documentation impact
docs-not-required
"""
    )
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.NEEDS_DECISION
    assert exit_code_for(result.report.overall_status) == 0


# --- Review fix 1: multiline free-text fields ------------------------------


def test_multiline_body_only_expected_change_is_one_value():
    body = base_body(
        """
## Documentation impact
docs-required
## Required documentation paths or bounded areas
docs/example.md
## Expected documentation change
This behavior changes in three ways.
First, the operator sees a new field.
Second, the default changes.
"""
    )
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.READY
    check = _doc_check(result)
    assert check.status == Status.PASS
    assert "expected_change_present=true" in check.evidence
    assert not any("First, the operator" in item for item in check.evidence)


def test_multiline_body_only_exemption_reason_is_one_value():
    body = base_body(
        """
## Documentation impact
docs-not-required
## Documentation exemption reason
No behavior changes.
This is purely an internal refactor.
"""
    )
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.READY
    check = _doc_check(result)
    assert check.status == Status.PASS
    assert "exemption_reason_present=true" in check.evidence
    assert not any("internal refactor" in item for item in check.evidence)


def test_multiline_yaml_literal_block_is_one_value():
    body = base_body(
        extra="""
```yaml
agent_os_issue_acceptance:
  tier: 0
  documentation_impact: docs-not-required
  documentation_exemption_reason: |
    No behavior changes.
    This is purely an internal refactor.
```
"""
    )
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.READY
    check = _doc_check(result)
    assert check.status == Status.PASS
    assert "exemption_reason_present=true" in check.evidence


def test_multiline_yaml_folded_block_is_one_value():
    body = base_body(
        extra="""
```yaml
agent_os_issue_acceptance:
  tier: 0
  documentation_impact: docs-not-required
  documentation_exemption_reason: >
    No behavior changes.
    This is purely an internal refactor.
```
"""
    )
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.READY
    check = _doc_check(result)
    assert check.status == Status.PASS
    assert "exemption_reason_present=true" in check.evidence


def test_equivalent_multiline_yaml_and_body_values_dedupe_to_ready():
    body = base_body(
        """
## Documentation impact
docs-not-required
## Documentation exemption reason
No behavior   changes.
This is purely   an internal refactor.
""",
        extra="""
```yaml
agent_os_issue_acceptance:
  tier: 0
  documentation_exemption_reason: |
    No behavior changes.
    This is purely an internal refactor.
```
""",
    )
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.READY
    check = _doc_check(result)
    assert check.status == Status.PASS


def test_conflicting_multiline_yaml_and_body_values_requires_decision():
    body = base_body(
        """
## Documentation impact
docs-not-required
## Documentation exemption reason
No behavior changes.
This is purely an internal refactor.
""",
        extra="""
```yaml
agent_os_issue_acceptance:
  tier: 0
  documentation_exemption_reason: |
    A completely different explanation.
    With different reasoning entirely.
```
""",
    )
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.NEEDS_DECISION
    check = _doc_check(result)
    assert check.evidence == [
        "impact=docs-not-required",
        "field=documentation_exemption_reason; code=documentation-exemption-conflict; "
        "yaml_present=true; body_present=true",
    ]
    assert not any("completely different" in item for item in check.evidence)
    assert not any("internal refactor" in item for item in check.evidence)


# --- Review fix 2: malformed YAML runtime types -----------------------------


def test_malformed_documentation_impact_list_type_requires_decision():
    body = base_body(
        extra="""
```yaml
agent_os_issue_acceptance:
  tier: 0
  documentation_impact:
    - docs-required
```
"""
    )
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.NEEDS_DECISION
    check = _doc_check(result)
    assert check.evidence == [
        "field=documentation_impact; code=documentation-source-malformed; source=yaml; type=list"
    ]


def test_malformed_documentation_expected_change_int_type_requires_decision():
    body = base_body(
        """
## Documentation impact
docs-required
## Required documentation paths or bounded areas
docs/example.md
""",
        extra="""
```yaml
agent_os_issue_acceptance:
  tier: 0
  documentation_expected_change: 42
```
""",
    )
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.NEEDS_DECISION
    check = _doc_check(result)
    assert (
        "field=documentation_expected_change; code=documentation-source-malformed; "
        "source=yaml; type=int"
    ) in check.evidence


def test_malformed_documentation_exemption_reason_mapping_type_requires_decision():
    body = base_body(
        """
## Documentation impact
docs-not-required
""",
        extra="""
```yaml
agent_os_issue_acceptance:
  tier: 0
  documentation_exemption_reason:
    reason: none
```
""",
    )
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.NEEDS_DECISION
    check = _doc_check(result)
    assert (
        "field=documentation_exemption_reason; code=documentation-source-malformed; "
        "source=yaml; type=dict"
    ) in check.evidence


def test_malformed_yaml_type_does_not_crash_and_stays_report_only():
    body = base_body(
        extra="""
```yaml
agent_os_issue_acceptance:
  tier: 0
  documentation_impact: true
```
"""
    )
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.NEEDS_DECISION
    check = _doc_check(result)
    assert check.evidence == [
        "field=documentation_impact; code=documentation-source-malformed; source=yaml; type=bool"
    ]
    assert exit_code_for(result.report.overall_status) == 0
