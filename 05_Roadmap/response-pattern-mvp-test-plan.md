# Response Pattern MVP Test Plan

## Status

Experimental test plan for PR #134 and the Response Pattern MVP pipeline.

## Purpose

Provide a small, repeatable way to test whether the Response Pattern MVP improves Agent OS responses without adding heavy process or premature governance.

## Test Artifact

Primary test file:

- `07_Agent_Tests/response-pattern-mvp.tests.md`

## What The Test Proves

The MVP is useful only if agents can:

- Select the smallest useful response pattern.
- Avoid long default explanations.
- Include Source Context when an answer depends on connected sources.
- Keep cached Notion information separate from live verification.
- Refuse premature promotion to stable governance.
- Produce usable implementation/review reports when required.

## How To Run

1. Open `07_Agent_Tests/response-pattern-mvp.tests.md`.
2. Run each numbered prompt in an Agent OS session.
3. Score against `07_Agent_Tests/common-test-checklist.md` first.
4. Score against the test-specific expectations second.
5. Record pass/fail results in the Manual Run Record.
6. File or update an RP issue for any failure.

## Minimum MVP Acceptance

Before merging the MVP PR, run at least these three tests manually:

- Test 2 - Lesson Design With Notion-Grounded Context
- Test 3 - Source Context Boundary
- Test 5 - Promotion Discipline

The MVP should not merge if any of those three fail.

## Post-Merge Trial Acceptance

During the one-week trial, run or observe at least five real responses:

- Two curriculum or lesson-design responses.
- Two Notion- or source-grounded responses.
- One GitHub review or implementation response.

At least three should include feedback notes.

## Failure Routing

| Failure | Route |
|---|---|
| Pattern too long | RP4 - revise failed pattern. |
| Source Context too long | RP3 - evaluate Source Context. |
| Source Context missing | RP3 - evaluate Source Context. |
| Cached Notion treated as live verification | Block merge or create urgent RP3 finding. |
| Stable promotion attempted too early | RP5 - promotion decision. |
| Required implementation report missing fields | Review Report pattern revision. |

## Merge Gate

PR #134 may move from draft to review only after:

- The MVP test file exists.
- The test plan exists.
- The PR body lists both test artifacts.
- Manual test status is recorded or explicitly marked pending human run.

## Non-Goals

- No automated testing required for the first MVP.
- No code changes.
- No Notion writes.
- No global agent behavior mandate.
