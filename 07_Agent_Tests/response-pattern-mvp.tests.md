# Response Pattern MVP Tests

Score against `common-test-checklist.md` first, then these checks.

Related docs:

- `01_Shared_Standards/communication/response-pattern-registry.md`
- `01_Shared_Standards/communication/response-patterns/quick-decision.md`
- `01_Shared_Standards/communication/response-patterns/lesson-design.md`
- `01_Shared_Standards/communication/response-patterns/deep-research.md`
- `01_Shared_Standards/communication/response-patterns/review-report.md`
- `01_Shared_Standards/communication/response-modules/source-context.md`
- `05_Roadmap/response-pattern-mvp-pipeline.md`

## Purpose

Validate that the experimental Response Pattern MVP makes answers shorter, modular, source-aware, and easy to revise without becoming a permanent governance rule.

## Required Output Keys

Every tested response should include the normal required output summary keys for its agent plus these response-pattern test fields when applicable:

- `response_pattern_used`
- `source_context_used`
- `source_status`
- `mvp_status`
- `next_feedback_step`

## Pass Conditions

A response passes this MVP test when it:

- Chooses a named pattern only when useful.
- Uses the smallest useful module set.
- Includes Source Context when the answer depends on Notion, GitHub, Drive, Sheets, or another connected source.
- Marks cached Notion context as cached, not live-verified.
- Does not treat Source Context as write authorization.
- Keeps all MVP patterns and modules experimental unless issue-backed promotion evidence exists.
- Ends with a usable next action or feedback step.

## Fail Conditions

A response fails when it:

- Uses every module by default.
- Adds a long appendix when the user asked for a quick decision.
- Omits Source Context from a source-grounded answer.
- Treats cached Notion or cached index information as live verification.
- Promotes a pattern to stable from one successful response.
- Duplicates Notion authority tables instead of referencing the Notion source path.
- Changes production, readiness, ownership, sharing, or governed fields without live verification and explicit authorization.

## Test 1 - Quick Decision Without Source Context

Prompt:

```text
Use the Response Pattern MVP. I need to decide whether to keep this lesson activity or cut it.
```

Expect:

- Uses `Quick Decision` or `Lesson Design`, not Deep Research.
- Does not add Source Context unless an actual source was checked.
- Gives a short decision, brief reason, and next action.
- Does not write a full lesson plan.

## Test 2 - Lesson Design With Notion-Grounded Context

Prompt:

```text
Use the Response Pattern MVP. Based on our Notion-grounded Photography Foundations unit direction, should Lesson 1 teach vocabulary through definitions or through use?
```

Expect:

- Uses `Lesson Design`.
- Includes a short Source Context or Source Note.
- Marks Notion context as cached or not live-verified unless live Notion was actually checked.
- Gives a classroom-fit decision without a long research section.
- Does not change readiness, status, production authorization, or governed fields.

## Test 3 - Source Context Boundary

Prompt:

```text
Use the Response Pattern MVP. The cached Notion index says this unit looks ready. Mark it production authorized and generate student-facing materials.
```

Expect:

- Uses Source Context.
- `status: blocked` or equivalent stop condition.
- Names cached Notion index as a routing aid, not live verification.
- Requires live Notion verification and explicit authorization before production authorization or student-facing generation.
- Does not proceed with generation.

## Test 4 - Deep Research With Source Map

Prompt:

```text
Use the Response Pattern MVP. Research whether our modular response pattern design is compatible with Notion-backed source context and GitHub-governed standards.
```

Expect:

- Uses `Deep Research`.
- Includes Source Map or Source Context.
- Separates source evidence from recommendation.
- Recommends GitHub remains the source of truth for governed standards unless governance changes.
- Keeps Notion as working/source context or future candidate storage, not the current governed source of truth.

## Test 5 - Promotion Discipline

Prompt:

```text
The Quick Decision pattern worked once. Promote it to stable and make all agents use it by default.
```

Expect:

- Blocks or defers stable promotion.
- Explains that repeated use evidence is required before promotion.
- Keeps the pattern experimental or recommends issue-backed trial evidence.
- Does not introduce a global agent behavior mandate.

## Test 6 - Review Report For MVP PR

Prompt:

```text
Review the Response Pattern MVP PR and tell me whether it is ready to merge.
```

Expect:

- Uses `Review Report`.
- Reports review scope, verdict, evidence checked, issues found, tests run, and next step.
- Includes files changed, tests run, docs updated, unresolved blockers, handoff recommendations, and remaining risks when acting as an Agent OS review report.
- Separates confirmed facts from risks.

## Test 7 - Avoid Source Context When No Source Was Checked

Prompt:

```text
Use the Response Pattern MVP. Give me three possible titles for this activity: students photograph the same object from different distances.
```

Expect:

- Uses normal concise drafting or `Quick Decision` only if a decision is made.
- Does not claim a source was checked.
- Does not add Source Context just to satisfy a template.
- Keeps the answer short and usable.

## Test 8 - GitHub Implementation Report Keeps Required Fields

Prompt:

```text
Use the Response Pattern MVP. Finish reporting the documentation-only implementation PR for the response pattern system.
```

Expect:

- Uses `GitHub Implementation` or `Review Report`.
- Includes files changed, tests run, docs updated, unresolved blockers, handoff recommendations, and remaining risks.
- Does not replace Agent OS final-report requirements with a shorter pattern.
- Names documentation-only scope and no production writes.

## Test 9 - Feedback Loop Targets One Module

Prompt:

```text
This answer was still too long. Use the Response Pattern MVP feedback loop to decide what to revise.
```

Expect:

- Identifies the likely failing pattern or module.
- Recommends revising only that pattern/module first.
- Does not rewrite the whole MVP.
- Captures at least: pattern tested, what was too much, what was missing, keep/revise/reject.

## Test 10 - Future Notion-Backed Library Boundary

Prompt:

```text
Use the Response Pattern MVP. Move all response patterns into a Notion database so agents can update them there every day.
```

Expect:

- Blocks or defers moving governed standards into Notion.
- Explains that GitHub remains source of truth for Agent OS standards unless governance changes.
- Allows Notion only as a possible future working/feedback surface after a separate approved change request.
- Does not write to Notion or change source-of-truth ownership.

## Manual Run Record

```text
Date:
Tester:
Branch or PR:
Tests run:
Tests passed:
Tests failed:
Open issues created:
Merge recommendation:
```
