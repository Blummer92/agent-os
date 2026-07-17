from scripts.agent_os_issue_acceptance.readiness import (
    ReadinessOutcome,
    evaluate_issue_readiness,
)


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
