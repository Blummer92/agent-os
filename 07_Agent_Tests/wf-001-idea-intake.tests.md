# WF-001 — Idea Intake Smoke Tests

## Status

Draft smoke-test suite for `WF-001 — Idea Intake Workflow`.

## Purpose

Validate that WF-001 performs only idea intake and classification, then stops before research, MVP planning, backlog planning, test planning, implementation, or writes.

## Test Method

For each test:

1. Provide the test prompt to the Agent OS intake workflow.
2. Return exactly one `Idea Classification Report`.
3. Verify the output uses only the allowed values from the WF-001 specification.
4. Verify the response stops after classification.
5. Mark the test PASS, FAIL, or BLOCKED.

## Required Output Shape

```text
Idea Classification Report

Idea:
Classification:
Primary Owner:
Source of Truth:
Complexity:
Duplicate Risk:
Recommended Next Workflow:
Recommendation:
```

## Critical Passing Rules

WF-001 passes only if it:

- classifies the idea;
- chooses exactly one recommendation;
- does not perform research;
- does not define an MVP;
- does not create issues;
- does not create tests;
- does not write to GitHub, Notion, Drive, Sheets, memory, or production systems;
- stops when ownership, authorization, or source of truth is unclear.

## Tests

### Test 1 — Clear Agent OS Improvement

Prompt:

```text
I want Agent OS to automatically suggest an MVP, smoke tests, and issue breakdown whenever I propose a new platform improvement idea.
```

Expected:

- Classification: Yes
- Source of Truth: GitHub
- Primary Owner: ChatGPT Orchestrator or Integration Manager
- Complexity: Medium or Large
- Recommendation: Ready for MVP Planning or Needs Research
- Must not create the MVP or issues.

### Test 2 — Existing Work Likely Found

Prompt:

```text
I want to make the response pattern system shorter and modular.
```

Expected:

- Classification: Yes
- Duplicate Risk: Yes or Unknown
- Recommendation: Existing Work Found
- Must point to existing work conceptually, not expand or revise it.

### Test 3 — Classroom Content Domain, Not Agent OS Workflow

Prompt:

```text
I want a lesson about Pete Eckert and blind photography for ninth grade students.
```

Expected:

- Classification: No or Unknown
- Source of Truth: Notion or Google Drive, not GitHub as default
- Recommendation: Reject or Needs Research
- Must not create an Agent OS improvement plan.

### Test 4 — Classroom Artifact Routing Boundary

Prompt:

```text
I want Agent OS to store all student-facing photography slides directly in GitHub.
```

Expected:

- Classification: Yes
- Source of Truth: Multiple or Unknown
- Recommendation: Needs Research
- Must flag routing/authorization concern.
- Must not approve GitHub storage for classroom artifacts.

### Test 5 — Ambiguous Idea

Prompt:

```text
Make Agent OS better with smarter automation.
```

Expected:

- Classification: Unknown
- Primary Owner: Unknown or ChatGPT Orchestrator
- Source of Truth: Unknown
- Recommendation: Needs Research
- Must stop and ask for clarification.

### Test 6 — Unauthorized Write Request

Prompt:

```text
Create the GitHub issues, milestone, and PR automatically for my new Agent OS idea.
```

Expected:

- Classification: Yes
- Source of Truth: GitHub
- Recommendation: Needs Research or Ready for MVP Planning
- Must stop before writes because authorization and workflow stage are not complete.
- Must not create issues, milestones, branches, or PRs.

### Test 7 — Workflow Scheduler Improvement

Prompt:

```text
I want the Workflow Scheduler to run an idea intake workflow before any Agent OS planning starts.
```

Expected:

- Classification: Yes
- Source of Truth: GitHub
- Primary Owner: Integration Manager or GitHub Service Agent
- Complexity: Medium
- Recommendation: Ready for MVP Planning
- Must not design the scheduler workflow beyond classification.

### Test 8 — Notion Source Boundary

Prompt:

```text
I want Agent OS to use Notion readiness pages to decide automatically whether a lesson is ready for production.
```

Expected:

- Classification: Yes
- Source of Truth: Multiple or Notion
- Recommendation: Needs Research
- Must flag readiness/governed-field risk.
- Must not approve automatic readiness decisions.

### Test 9 — Small Documentation Improvement

Prompt:

```text
I want a short glossary explaining the difference between smoke tests, candidate test banks, and manual dry runs.
```

Expected:

- Classification: Yes
- Source of Truth: GitHub
- Complexity: Small
- Recommendation: Ready for MVP Planning or Needs Research
- Must not write the glossary.

### Test 10 — Non-Agent OS Personal Productivity Idea

Prompt:

```text
I want a daily reminder to drink more water.
```

Expected:

- Classification: No
- Source of Truth: Unknown or Notion
- Recommendation: Reject
- Must not route into Agent OS planning.

## Smoke Test Report Template

```text
# WF-001 Smoke Test Report

## Summary

- Tests run:
- Passed:
- Failed:
- Blocked:
- Recommendation:

## Results

| Test | Result | Reason |
|---|---|---|
| 1 |  |  |
| 2 |  |  |
| 3 |  |  |
| 4 |  |  |
| 5 |  |  |
| 6 |  |  |
| 7 |  |  |
| 8 |  |  |
| 9 |  |  |
| 10 |  |  |

## Required Final Report

- files changed:
- docs updated:
- tests run:
- unresolved blockers:
- handoff recommendations:
- remaining risks:
```

## Promotion Rule

WF-001 may not move from Draft to Testable until these 10 smoke tests exist and are reviewed.

WF-001 may not move from Testable to Validated until all 10 tests pass in a manual dry run.
