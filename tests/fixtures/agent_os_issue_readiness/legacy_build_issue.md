## Objective

Add a local report-only readiness checker.

## Source Of Truth

- Canonical surface: GitHub
- External writes requested: no

## Owner Routing

- Primary owner: QA / Test Agent
- Repository write executor: GitHub Service Agent

## Scope

- Add a local checker.

## Non-Goals

- No GitHub metadata writes.

## Allowed Files Or Areas

- scripts/agent_os_issue_acceptance/

## Forbidden Files Or Areas

- none

## Required Tests Or Validation

- pytest tests/agent_os_issue_acceptance

## Required Docs Updates

- not applicable

## Dependencies And Blockers

- none

```yaml
agent_os_issue_acceptance:
  owner_agent: qa-test-agent
  source_of_truth: GitHub
  external_writes: none
  required_files:
    - scripts/agent_os_issue_acceptance/
  required_tests:
    - pytest tests/agent_os_issue_acceptance
```

## Acceptance Criteria

- [ ] The checker returns one result.

## Definition Of Done

- [ ] Tests pass.
