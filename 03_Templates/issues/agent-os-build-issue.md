# Agent OS Build Issue Template

Use `.github/ISSUE_TEMPLATE/agent-os-task.yml` as the canonical entry path for
new Agent OS repository issues. This Markdown template remains a compatibility
and generated-issue surface during migration.

## Issue Tier

- Tier: 0 | 1 | 2

Tier 0 is small safe maintenance. Tier 1 is standard implementation. Tier 2 is
governed or cross-system work.

## Objective And Value

State the outcome and why it matters.

## Owner And Source Of Truth

- Primary owner:
- Supporting agents: none
- Canonical surface: GitHub
- Repository write executor: GitHub Service Agent
- External writes requested: no

## Scope And Non-Goals

### Scope

-

### Non-Goals

-

## Allowed And Protected Areas

- Allowed files or areas:
- Forbidden or protected files, paths, capabilities, or systems: none

## Validation And Documentation

- Required tests or validation:
- Required docs updates: not applicable

## Dependencies And Blockers

- Dependencies: none
- Blockers: none

## Tier 2 Controls

Complete only for Tier 2 work.

- Explicit authorization:
- Governed fields or external surfaces:
- Approval requirements:
- Stop conditions:
- Rollback:
- Migration or compatibility plan:

## Optional Machine-Checkable Metadata

```yaml
agent_os_issue_acceptance:
  tier: 1
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

- [ ] Required tier fields are complete.
- [ ] Scope is satisfied and non-goals are preserved.
- [ ] Required validation and docs are reported.
- [ ] No forbidden or unapproved surface is touched.

## Definition Of Done

- [ ] Readiness result is `ready`, `blocked`, or `needs-decision`.
- [ ] A draft PR links this issue when implementation is authorized.
- [ ] Final reporting includes files changed, tests run, docs updated, blockers,
      handoff recommendations, and remaining risks.
