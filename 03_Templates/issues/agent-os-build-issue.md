# Agent OS Build Issue Template

Use this template when an Agent OS issue should be build-ready for a future PR.

## Objective

State the user-visible or system-visible outcome.

## Source Of Truth

- Canonical surface: GitHub
- Related working surfaces: none unless explicitly approved
- External writes requested: no

## Owner Routing

- Primary owner:
- Supporting agents:
- Repository write executor: GitHub Service Agent

## Scope

- 

## Non-Goals

- 

## Allowed Files Or Areas

- 

## Forbidden Files Or Areas

- 

## Required Tests Or Validation

- 

## Required Docs Updates

- 

## Dependencies And Blockers

- 

## Optional Machine-Checkable Metadata

```yaml
agent_os_issue_acceptance:
  owner_agent:
  source_of_truth: GitHub
  external_writes: none
  required_files: []
  forbidden_paths: []
  required_tests: []
  required_docs: []
  banned_patterns: []
  manual_review: []
```

## Acceptance Criteria

- [ ] Scope is satisfied.
- [ ] Non-goals are preserved.
- [ ] Required tests or validation are reported.
- [ ] Required docs updates are complete or explicitly not applicable.
- [ ] No forbidden files, paths, imports, capabilities, or systems are touched.
- [ ] No external writes or production changes are introduced.

## Definition Of Done

- [ ] Draft PR links this issue.
- [ ] PR includes files changed, tests run, docs updated, unresolved blockers,
      handoff recommendations, and remaining risks.
- [ ] Issue Acceptance Report is included or marked manual-review.
