# Issue Acceptance And Readiness Standard

## Purpose
Define one Agent OS contract for build-ready issues, readiness decisions, and pull
request acceptance evidence.

## Boundary
This standard defines contracts and report shapes only. It does not authorize
implementation, scheduling, merge, closure, production or external writes,
source-of-truth changes, readiness mutation, approvals, or governed-field edits.

## Canonical Lifecycle
```text
idea or request
-> structured issue design
-> normalized issue metadata
-> readiness evidence
-> implementation handoff
-> pull request acceptance evidence
```
ChatGPT Orchestrator owns intake and routing. QA / Test Agent owns readiness and
acceptance evidence. GitHub Service Agent is the sole repository write executor.

## Issue Tiers
- Tier 0 requires objective, owner, allowed area, validation, and completion.
- Tier 1 adds value, scope, non-goals, likely files, tests, documentation,
  dependencies, acceptance criteria, and definition of done.
- Tier 2 adds source-of-truth analysis, authorization, external surfaces,
  governed fields, rollback, approvals, stop conditions, and compatibility.
Tier selection never weakens governance or write authorization.

## Documentation Impact Intake
The canonical issue form uses these exact fields:
- `documentation-impact`: required dropdown with `docs-required`,
  `docs-not-required`, or `docs-needs-decision`;
- `required-docs`: optional textarea with one repository-relative POSIX path per
  line, using exact files or bounded directories without trailing slashes;
- `documentation-expected-change`: optional textarea describing required
  behavior, contract, workflow, or operator-guidance changes;
- `documentation-exemption-reason`: optional textarea explaining why
  documentation is not required.
GitHub forms cannot conditionally require supporting fields. Readiness performs
that semantic validation. Do not use absolute paths, traversal, backslashes,
`./`, repeated or trailing separators, `**`, `?`, or bracket classes.

## Readiness Outcomes
The user-facing result is exactly `ready`, `blocked`, or `needs-decision`.
`ready` satisfies tier requirements, `blocked` has a missing or failed required
item, and `needs-decision` requires human judgment. Readiness is evidence only.

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
Metadata narrows checks; it does not replace the issue body, governance, or
reviewer judgment.

## Pull Request Evidence
PRs should include linked issue, summary, files changed, tests, docs, blockers,
handoffs, risks, and an Issue Acceptance Report or manual-only explanation.

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
`fail` maps to `blocked`; `manual-review` maps to `needs-decision`.

## Implementation Rules
Reuse existing report, check, status, metadata, renderer, parser, label evidence,
and fixture patterns. Start offline with no credentials. Workflow integration is
report-only first.
