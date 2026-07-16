# Issue Acceptance Automation Standard

## Purpose

Define the Agent OS contract for checking whether a pull request satisfies the
GitHub issue it claims to resolve. This standard is the IA1 source of truth;
IA2 implements checker code against it.

## Boundary

This standard defines the data contract and report shape only. It does not
implement checker code, add a GitHub Actions workflow, require live credentials,
call external services, or authorize writes outside GitHub.

## Build-Ready Issue Sections

Build-ready Agent OS issues should include objective, scope, non-goals, likely
files or allowed areas, forbidden paths or capabilities, required tests, required
docs, dependencies, blockers, acceptance criteria, and definition of done.

When a field is not applicable, say so explicitly rather than omitting it.

## Optional Metadata Block

Issues may include a machine-checkable block for IA2 and later tooling:

```yaml
agent_os_issue_acceptance:
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

The metadata narrows automated checks. It does not replace the issue body,
governance rules, or reviewer judgment.

## Required PR Evidence

Pull requests that resolve Agent OS issues should include linked issue, summary,
files changed, tests run, docs updated, unresolved blockers, handoff
recommendations, remaining risks, and an Issue Acceptance Report or manual-only
explanation.

## Acceptance Report Schema

IA2 reports should use this shape:

```text
Issue Acceptance Report
Linked issue:
Overall result: pass | warn | fail | manual-review
Checks:
- linked issue
- required PR report fields
- required files
- forbidden paths
- required tests
- required docs
- banned patterns
- external-write boundary
Manual review items:
Evidence:
Blockers:
Remaining risks:
```

## Outcome Rules

- `pass`: machine-checkable requirements are satisfied.
- `warn`: review should continue, but a non-blocking gap exists.
- `fail`: a declared required item is missing or a forbidden item is present.
- `manual-review`: automation cannot decide safely from available evidence.

A pass result never authorizes merge, production writes, external writes, source-
of-truth changes, readiness changes, approval changes, or governed-field edits.

## Ownership

QA / Test Agent owns acceptance evidence and report interpretation. Integration
Manager supports source-of-truth and cross-system boundary review. GitHub Service
Agent executes approved repository changes and PR reporting.

## IA2 Implementation Notes

IA2 should start with offline fixtures, no network calls in unit tests, and no
external credentials. Workflow integration should happen only after the local
checker is stable and may start as non-blocking report-only mode.

## Version

0.1.0
