# CKR6 Repair Activation — #1873

## Purpose

Make the existing CKR6 Lessons Learned retry boundary automatic at failed implementation and repair transitions without creating another memory, selector, scheduler, retry engine, or Notion client.

## Canonical flow

```text
failed implementation/repair attempt
-> preserve FailedRepairAttempt
-> activate_repair_retry_lessons(...)
-> existing CKR11 orchestrate_lesson_activation(...)
-> bounded read-only Lessons Learned retrieval when material
-> record retry_reentry_outcome on that exact failed attempt
-> existing plan_repair_retry_boundary(...)
-> next repository mutation admitted or blocked
-> caller reacquires mutable GitHub state and continues the still-authorized mission
```

Every new failed attempt creates a new retry-specific CKR6 obligation. An outcome from an earlier attempt cannot satisfy a later attempt.

## Outcomes

- `consumed`: relevant lesson evidence was selected through CKR6/CKR2; the retry gate may admit the next mutation.
- `not-material`: CKR6 determined retrieval was not needed; the retry gate may admit the next mutation.
- `unavailable-or-failed`: retrieval or selection did not safely produce usable lesson context. When specialized knowledge is required, the mutation remains blocked. Safe fallback behavior remains governed by the existing CKR6 contract.

## Authority

Lessons Learned remain advisory-only. GitHub governance, current issue/PR state, authorization, repository code, tests, and exact-head validation remain authoritative. This seam performs no Notion writes and grants no implementation, merge, issue-closure, workflow, production, credential, or external-write authority.

## Implementation

`src/agent_memory_context_manager/repair_lesson_activation.py` composes existing public CKR6/CKR11 functions. It does not duplicate retrieval or selection logic.

Regression coverage lives in `tests/test_repair_lesson_activation.py` and proves automatic retrieval, retry-specific re-entry, specialized-required fail-closed behavior, explicit not-material zero-read behavior, and rejection of reuse of an already-satisfied attempt.
