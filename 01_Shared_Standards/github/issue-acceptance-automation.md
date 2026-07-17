# Issue Acceptance And Readiness Standard

## Purpose
Define one Agent OS contract for designing build-ready issues, deciding issue
readiness, and checking whether a pull request satisfies its linked issue.

## Boundary
This standard defines contracts and report shapes only. It does not authorize
merges, issue closure, production writes, external writes, source-of-truth
changes, readiness-field mutation, approval changes, or governed-field edits.

## Canonical Lifecycle
```text
idea or request
-> structured issue design
-> one readiness decision
-> implementation handoff
-> pull request acceptance evidence
```
ChatGPT Orchestrator owns intake and routing. QA / Test Agent owns readiness and
acceptance evidence. GitHub Service Agent is the sole repository write executor.

## Issue Tiers
### Tier 0 - Small Safe Maintenance
Required: objective, owner, allowed file or area, required validation, and one
completion criterion. Source of truth defaults to GitHub and external writes
default to none.

### Tier 1 - Standard Implementation
Required: objective, value, owner, scope, non-goals, likely files or allowed
areas, required tests, required docs or `not applicable`, dependencies or
`none`, acceptance criteria, and definition of done.

### Tier 2 - Governed Or Cross-System Work
Includes Tier 1 plus source-of-truth analysis, explicit authorization, external
write surfaces, governed fields, support routing, rollback, approval
requirements, stop conditions, and migration or compatibility planning.
Tier selection never weakens write-authorization or source-of-truth rules.

## Readiness Outcomes
The user-facing readiness result is exactly one of:
- `ready`: required information and prerequisites for the tier are satisfied;
- `blocked`: a required item is missing, failed, pending, or explicitly blocked;
- `needs-decision`: human judgment is required for conflicting or unresolved
  requirements, ownership, authorization, or source-of-truth evidence.
Readiness is evidence only. It is not implementation or merge authorization.

## Optional Machine-Checkable Metadata
```yaml
agent_os_issue_acceptance:
  tier: 1
  owner_agent: qa-test-agent
  source_of_truth: GitHub
  external_writes: none
  required_files: []
  forbidden_paths: []
  required_tests: []
  required_docs: []
  banned_patterns: []
  manual_review: []
```
Metadata narrows automated checks. It does not replace the issue body,
governance rules, or reviewer judgment.

## Pull Request Evidence
PRs should include linked issue, summary, files changed, tests run, docs updated,
unresolved blockers, handoff recommendations, remaining risks, and an Issue
Acceptance Report or manual-only explanation.

## Acceptance Report Schema
```text
Issue Acceptance Report
Linked issue:
Overall result: pass | warn | fail | manual-review
Checks:
Manual review items:
Evidence:
Blockers:
Remaining risks:
```
Internal acceptance outcomes retain their existing meanings: `pass` satisfies
machine-checkable requirements, `warn` is advisory, `fail` identifies a missing
required or present forbidden item, and `manual-review` means automation cannot
decide safely. At the readiness boundary, `fail` maps to `blocked` and
`manual-review` maps to `needs-decision`.

## Implementation Rules
Reuse the existing `AcceptanceReport`, `CheckResult`, `Status`, `IssueMetadata`,
renderer, parser, label evidence, and fixture patterns. Start offline with no
network calls or external credentials. Workflow integration begins report-only.
