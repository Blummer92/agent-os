from pathlib import Path

from scripts.agent_os_issue_acceptance.readiness import (
    ReadinessOutcome,
    evaluate_issue_readiness,
)


FIXTURES = Path(__file__).parents[1] / "fixtures" / "agent_os_issue_readiness"


def test_tier_zero_maintenance_is_ready():
    body = """
Issue Tier: 0
## Objective
Remove one deprecation warning.
## Owner
QA / Test Agent
## Allowed Files
- src/example.py
## Validation
- pytest tests/test_example.py
## Completion Criterion
- Warning no longer appears.
"""
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.READY


def test_tier_one_standard_issue_is_ready():
    body = """
Issue Tier: 1
## Objective
Add a local report-only checker.
## Value
Make readiness visible.
## Owner
QA / Test Agent
## Scope
- Add local checker.
## Non-Goals
- No writes.
## Allowed Files
- scripts/example/
## Validation
- pytest tests/example
## Documentation
- Update README.
## Dependencies
- none
## Acceptance Criteria
- [ ] Checker reports one result.
## Definition Of Done
- [ ] Tests pass.
"""
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.READY


def test_tier_two_governed_issue_is_ready_evidence_only():
    body = """
Issue Tier: 2
## Objective
Update a governed integration contract.
## Value
Reduce routing ambiguity.
## Owner
Integration Manager
## Scope
- Update the contract.
## Non-Goals
- No production writes.
## Allowed Files
- 01_Shared_Standards/
## Validation
- validate-all.sh
## Documentation
- Update operator guidance.
## Dependencies
- none
## Acceptance Criteria
- [ ] Contract is explicit.
## Definition Of Done
- [ ] Validation passes.
## Authorization
Explicit approval required.
## Source Of Truth
GitHub
## External Write Boundary
None
## Rollback
Revert the PR.
## Approval Requirements
Human approval before merge.
## Stop Conditions
Stop on unclear ownership.
## Migration Or Compatibility Planning
Preserve old issue-form parsing during migration.
"""
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.READY
    assert "does not authorize" in result.report.remaining_risks[0]


def test_missing_required_fields_is_blocked():
    body = """
Issue Tier: 1
## Objective
Add a checker.
## Owner
QA / Test Agent
"""
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.BLOCKED
    assert result.report.blockers


def test_blocked_dependency_is_blocked():
    body = """
Issue Tier: 0
## Objective
Update documentation.
## Owner
GitHub Service Agent
## Allowed Files
- README.md
## Validation
- markdown check
## Completion Criterion
- Text is corrected.
Blocked by: #100
"""
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.BLOCKED


def test_pending_validation_is_blocked_not_needs_decision():
    body = """
Issue Tier: 0
## Objective
Update documentation.
## Owner
GitHub Service Agent
## Allowed Files
- README.md
## Validation
- markdown check
## Completion Criterion
- Text is corrected.
"""
    result = evaluate_issue_readiness(body, validation_pending=True)
    assert result.outcome == ReadinessOutcome.BLOCKED


def test_needs_decision_is_human_decision():
    body = """
Issue Tier: 0
## Objective
Update documentation.
## Owner
needs-decision
## Allowed Files
- README.md
## Validation
- markdown check
## Completion Criterion
- Text is corrected.
"""
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.NEEDS_DECISION


def test_empty_body_requires_decision_without_crashing():
    result = evaluate_issue_readiness("")
    assert result.outcome == ReadinessOutcome.NEEDS_DECISION
    assert not result.report.blockers


def test_invalid_tier_requires_decision():
    result = evaluate_issue_readiness("Issue Tier: 9\n\n## Objective\nDo work.")
    assert result.outcome == ReadinessOutcome.NEEDS_DECISION


def test_malformed_acceptance_yaml_requires_decision():
    body = """
## Objective
Do work.

```yaml
agent_os_issue_acceptance:
  tier: [
```
"""
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.NEEDS_DECISION
    assert any(check.name == "issue metadata" for check in result.report.checks)


def test_manual_review_metadata_requires_decision():
    body = """
Issue Tier: 0
## Objective
Update documentation.
## Owner
GitHub Service Agent
## Allowed Files
- README.md
## Validation
- markdown check
## Completion Criterion
- Text is corrected.

```yaml
agent_os_issue_acceptance:
  tier: 0
  manual_review:
    - confirm ownership
```
"""
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.NEEDS_DECISION
    assert "confirm ownership" in result.report.manual_review_items


def test_legacy_ia_metadata_tier_is_supported():
    body = """
## Objective
Update documentation.
## Owner
GitHub Service Agent
## Allowed Files
- README.md
## Validation
- markdown check
## Completion Criterion
- Text is corrected.

```yaml
agent_os_issue_acceptance:
  tier: 0
  owner_agent: github-service-agent
  source_of_truth: GitHub
  external_writes: none
```
"""
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.READY


def test_unrelated_prose_does_not_satisfy_required_sections():
    body = """
Issue Tier: 1
## Objective
The prose mentions scope, non-goals, files, validation, documentation, dependencies,
acceptance criteria, and definition of done, but those sections do not exist.
## Owner
QA / Test Agent
"""
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.BLOCKED
    assert len(result.report.blockers) >= 5


def test_code_comments_and_quotes_do_not_create_fields_or_decisions():
    body = """
Issue Tier: 0
## Objective
Update documentation.
## Owner
GitHub Service Agent
## Allowed Files
- README.md
## Validation
- markdown check
## Completion Criterion
- Text is corrected.

<!-- needs-decision -->
> needs-decision
```text
## Authorization
needs-decision
Blocked by: #999
```
"""
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.READY


def test_tier_two_combined_controls_require_labeled_values():
    body = """
Issue Tier: 2
## Objective And Value
Update a governed contract and reduce ambiguity.
## Owner And Source Of Truth
- Primary owner: Integration Manager
- Source of truth: GitHub
## Scope And Non-Goals
- Scope: update the contract
- Non-goals: no production writes
## Allowed And Protected Areas
- Allowed: 01_Shared_Standards/
## Validation And Documentation
- Tests: validate-all.sh
- Docs: update guidance
## Dependencies And Blockers
- Dependencies: none
- Blockers: none
## Acceptance Criteria And Definition Of Done
- Acceptance criteria: contract is explicit
- Definition of done: tests pass
## Tier 2 Controls, When Applicable
- Authorization: explicit approval required
- External write: none
- Rollback: revert the PR
- Approval: human approval required
- Stop conditions: stop on unclear ownership
- Compatibility: preserve legacy parsing
"""
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.READY


def test_legacy_issue_form_is_deterministic_needs_decision():
    body = (FIXTURES / "legacy_issue_form.md").read_text()
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.NEEDS_DECISION
    assert any(check.name == "issue tier" for check in result.report.checks)


def test_legacy_build_issue_headings_are_recognized_but_require_tier_decision():
    body = (FIXTURES / "legacy_build_issue.md").read_text()
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.NEEDS_DECISION
    assert any(check.name == "issue tier" for check in result.report.checks)


def test_legacy_ia1_without_tier_requires_tier_decision_not_blocked():
    body = (FIXTURES / "legacy_ia1_without_tier.md").read_text()
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.NEEDS_DECISION
    assert not result.report.blockers


def test_new_tiered_issue_fixture_is_ready():
    body = (FIXTURES / "new_tiered_issue.md").read_text()
    result = evaluate_issue_readiness(body)
    assert result.outcome == ReadinessOutcome.READY
