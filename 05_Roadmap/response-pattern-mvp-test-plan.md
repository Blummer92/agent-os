# Response Pattern MVP Test Plan

## Status

Experimental test plan for PR #134 and the Response Pattern MVP pipeline.

## Purpose

Provide a small, repeatable way to test whether the Response Pattern MVP improves Agent OS responses without adding heavy process or premature governance.

## Test Artifacts

Primary smoke test file:

- `07_Agent_Tests/response-pattern-mvp.tests.md`

Broader candidate prompt bank:

- `07_Agent_Tests/response-pattern-mvp-candidate-prompt-bank.md`

## What The Test Proves

The MVP is useful only if agents can:

- Select the smallest useful response pattern.
- Avoid long default explanations.
- Include Source Context when an answer depends on connected sources.
- Keep cached Notion information separate from live verification.
- Refuse premature promotion to stable governance.
- Produce usable implementation/review reports when required.
- Handle curriculum planning questions about modeling, lesson names, lesson context, slide images, slide layout, and slide content density without overproducing artifacts.

## How To Run The 10-Test Smoke Suite

1. Open `07_Agent_Tests/response-pattern-mvp.tests.md`.
2. Run each numbered prompt in an Agent OS session.
3. Score against `07_Agent_Tests/common-test-checklist.md` first.
4. Score against the test-specific expectations second.
5. Record pass/fail results in the Manual Run Record.
6. File or update an RP issue for any failure.

## How To Use The 100-Prompt Candidate Bank

Use `07_Agent_Tests/response-pattern-mvp-candidate-prompt-bank.md` after the 10-test smoke suite or during the one-week trial.

Suggested sample sizes:

- 10 prompts for a quick trial.
- 25 prompts for a focused QA pass.
- 100 prompts for a full stress pass.

The candidate bank should help identify which prompts deserve promotion into the formal smoke suite, which should remain trial prompts, and which should be removed.

## MVP Pre-Merge Acceptance

Before merging the MVP PR, run all 10 manual tests in `07_Agent_Tests/response-pattern-mvp.tests.md`.

The following three are critical blockers and must pass:

- Test 2 - Lesson Design With Notion-Grounded Context
- Test 3 - Source Context Boundary
- Test 5 - Promotion Discipline

The remaining tests provide broader confidence across quick decisions, deep research, review reports, implementation reports, feedback revision, and future Notion-backed-library boundaries.

The MVP should not merge if any critical blocker fails. Non-critical failures should either be fixed before merge or explicitly tracked in RP issues.

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
| Source Context added when no source was checked | RP3 - evaluate Source Context. |
| Future Notion-backed library changes source of truth too early | RP6 - research future Notion-backed response pattern library. |
| Lesson context invented instead of sourced or blocked | RP2 or RP4, depending on whether this appears during trial or revision. |
| Slide-image or slide-layout recommendations overproduce a student-facing artifact | RP4 and Instructional Materials Coach review. |

## Merge Gate

PR #134 may move from draft to review only after:

- The MVP test file exists.
- The test plan exists.
- The PR body lists both test artifacts.
- Manual 10-test status is recorded or explicitly marked pending human run.

The 100-prompt candidate bank is not a pre-merge gate. It is a stress-test pool for broader QA and daily iteration.

## Non-Goals

- No automated testing required for the first MVP.
- No code changes.
- No Notion writes.
- No global agent behavior mandate.
- No student-facing artifact generation from candidate prompts unless separately approved and routed to the correct destination.
