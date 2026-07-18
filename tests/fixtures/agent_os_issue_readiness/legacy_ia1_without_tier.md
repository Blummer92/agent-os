## Objective

Update a local validation script.

## Owner Routing

- Primary owner: QA / Test Agent

## Scope

- Update one local checker.

## Non-Goals

- No external writes.

## Allowed Files Or Areas

- scripts/agent_os_issue_acceptance/

## Required Tests Or Validation

- pytest tests/agent_os_issue_acceptance

## Required Docs Updates

- not applicable

## Dependencies And Blockers

- none

## Acceptance Criteria

- [ ] The checker remains offline.

## Definition Of Done

- [ ] Tests pass.

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
