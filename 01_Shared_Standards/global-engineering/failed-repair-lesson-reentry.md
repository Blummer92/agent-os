# Failed Repair Lesson Re-entry

## Purpose
Prevent an active coding or pull-request repair loop from bypassing the already-implemented CKR6 retry boundary after a failed attempt.

## Required transition
When a governed implementation or repair attempt remains red or otherwise fails, preserve that attempt as the current `FailedRepairAttempt` before forming another repair hypothesis or repository mutation.

For the current failed attempt:
1. increase diagnostic resolution using current canonical GitHub evidence;
2. invoke the existing `agent_memory_context_manager.activate_repair_retry_lessons(...)` seam with the current `CodingKnowledgeRequest`, failed attempt, and repair/CI context;
3. preserve the returned retry-specific outcome on that exact attempt as `consumed`, `not-material`, or `unavailable-or-failed`;
4. require the returned `RepairRetryBoundaryPlan` to admit mutation before another repository mutation; and
5. reacquire mutable GitHub issue/PR/head/check state before continuing the still-authorized parent mission.

Every newly failed attempt creates a new CKR6 retry obligation. An outcome recorded for an earlier attempt cannot satisfy the current attempt.

Do not substitute a one-time initial `plan_lesson_preflight(...)` call for this retry transition. Do not build a second lesson selector, Notion reader, retry engine, or repair state model. The executable behavior remains owned by `08_Tooling/agent-memory-context-manager/CKR6_REPAIR_ACTIVATION.md`, `repair_lesson_activation.py`, CKR11, and the existing CKR6/CKR2 contracts.

## Subordinate bug capture
If a repair exposes a separate Agent OS defect and current policy permits bounded issue capture, that bookkeeping is subordinate to the active parent repair mission. After capture, continue the parent mission from its current retry boundary unless authorization, source of truth, scope, ownership, or another genuine stop condition changed. Issue creation alone is not a terminal repair state.

## Authority boundary
Lessons Learned remain advisory-only. Current GitHub governance, issue/PR state, authorization, repository code, tests, and exact-head validation remain authoritative. Lesson retrieval or consumption grants no implementation, merge, issue-closure, workflow/protected-setting, credential, production, external-write, or other authority.

If specialized knowledge is required and lesson activation returns insufficient/manual-review evidence, the next mutation remains blocked under the existing CKR6 contract. Otherwise use only the safe fallback already defined by CKR6; never invent replacement guidance.

## Version
0.1.0

## Source
Issue #1901. Reuses the merged #1873 repair-activation seam and recurrence lesson LL-51 without creating a duplicate runtime mechanism.
