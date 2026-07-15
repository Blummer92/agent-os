# Response Pattern Registry

## Status

Experimental. This registry is a lightweight testing surface for Agent OS response shape. It is not a permanent governance rule and does not force all agents into one format.

## Purpose

Help Agent OS agents produce shorter, modular, decision-focused responses that can be tested and revised day to day.

## Use Rule

Agents should choose the smallest response pattern that fits the current task. If no pattern fits, use normal judgment and keep the response focused on the user's next decision.

## Status Values

| Status | Meaning |
|---|---|
| experimental | New pattern being tried; easy to revise or remove. |
| testing | Pattern has been useful more than once and is being evaluated. |
| stable | Pattern is reliable enough for default use in its task type. |
| deprecated | Pattern should not be used for new responses. |

## Initial Patterns

| Pattern | File | Status | Primary Use |
|---|---|---|---|
| Quick Decision | `response-patterns/quick-decision.md` | experimental | Fast choice or recommendation. |
| Lesson Design | `response-patterns/lesson-design.md` | experimental | Curriculum and classroom planning. |
| GitHub Implementation | `response-patterns/github-implementation.md` | experimental | Repository implementation or handoff work. |
| Deep Research | `response-patterns/deep-research.md` | experimental | Evidence-heavy research requests. |
| Review Report | `response-patterns/review-report.md` | experimental | Review, validation, or audit summaries. |

## Daily Iteration Loop

Use this quick note after a work session when a response felt too long, too thin, or especially useful.

```text
Response Pattern Tested:
What worked:
What was too much:
What was missing:
Keep / revise / reject:
```

## Promotion Guidance

A pattern may move from `experimental` to `testing` after it helps in several real tasks without creating avoidable follow-up work.

A pattern may move from `testing` to `stable` only when it consistently helps the user make the next decision faster.

A pattern should move to `deprecated` when it produces repeated confusion, unnecessary length, or poor task fit.

## Guardrails

- Keep patterns modular.
- Do not require every response to use every module.
- Do not add large appendices unless requested.
- Do not replace governed final-report requirements for implementation or review work.
- Do not duplicate agent-specific overlay rules here.
- If this becomes a governed routing or ownership registry, create a separate governance change request before moving or promoting it.
