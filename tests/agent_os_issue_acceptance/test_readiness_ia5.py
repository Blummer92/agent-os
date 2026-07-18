from scripts.agent_os_issue_acceptance.models import AcceptanceReport, CheckResult, Status
from scripts.agent_os_issue_acceptance.readiness import (
    ReadinessOutcome,
    evaluate_issue_readiness,
    evaluate_issue_readiness_with_labels,
)


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
{extra}
"""


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
