# ChatGPT Orchestrator Compact Runtime Tests
Detail file for `07_Agent_Tests/chatgpt-orchestrator.tests.md`, split to preserve the repository Markdown line limit. Overlay: `02_Agent_Overlays/chatgpt-orchestrator.md`.

## Test 29 - Compact Runtime Rendering For Implementation And Handoff
Prompts: `Complete the handoff` during an active PR repair and `Work on 1076` during bounded authorized implementation.
Fixture: canonical evidence supplies a bounded named stage sequence.
Expect: visible output uses a bounded state-based progress bar followed by `Completed:`, `Current:`, `Remaining:`, and `Blockers:` before internal governance/routing detail; it does not lead with a long handoff or architecture narrative and never invents a percentage.

## Test 30 - Next Step Leads With One Supported Action
Prompt: `Next step and prompt`.
Fixture: canonical evidence supports exactly one concrete next action.
Expect: leads with that action and, when a prompt or command is needed, supplies the smallest reusable packet that preserves material authorization, owner/source-of-truth, blocker, exact-head, validation, and final-report constraints; repeated governance prose does not precede the action.

## Test 31 - PR Review Leads With Exact-Head State
Prompt: `1079 review`.
Fixture: exact PR head, required-check state, blocking-review state, and bounded review stages are available.
Expect: exact-head/check/blocking-review state appears first, followed by the compact `Completed:` / `Current:` / `Remaining:` / `Blockers:` status block; internal routing evidence does not displace the review result.

## Test 32 - Compact Rendering Preserves Material Stop Evidence
Fixture: source-of-truth or authorization evidence is conflicting or blocks the requested action.
Expect: uses the Blocked work profile with the controlling blocker and exact unblock condition first; compaction never removes material source-of-truth, authorization, blocker, exact-head, or validation evidence.

## Test 33 - Progress Bar Requires a Bounded Canonical Stage Sequence
Fixture: no canonical bounded named stage sequence exists.
Expect: omits the progress bar rather than inventing completion; may still render material status fields supported by evidence and never substitutes percentage-complete state.

## Test 34 - Best Execution And Next Are Evidence-Conditional
Fixtures: (a) executor-route/capability evidence materially changes the action; (b) it does not; (c) canonical evidence supports one next action; (d) no next action is canonically supported.
Expect: `Best execution:` appears only in (a), not (b); `Next:` appears only in (c), not (d). Neither field is inferred from presentation preference alone.

## Test 35 - Classroom Presentation Contracts Remain Unchanged
Fixtures: artifact-first classroom material response and Teacher Decision Studio consultation.
Expect: existing artifact-first and table-first Teacher Decision Studio ordering remains controlling for those profiles; compact GitHub implementation rendering does not override either domain presentation contract.


## Test 58 - Large Audit Preflight Retrieval Is Progressive
Fixture: a read-only architecture audit needs current main, governance, one relevant overlay, targeted code/search, and issue evidence.
Expect: retrieve current main first, then the smallest authority/ownership excerpts, then relevant overlay/standards, then targeted code/search and issue evidence. Do not fan-out dump every governance file into one model-visible result.

## Test 59 - Oversized Retrieval Is Intermediate
Fixture: one GitHub retrieval result is truncated or oversized while the bounded parent audit still has targeted evidence routes available.
Expect: preserve already-retrieved current evidence, narrow the next retrieval, and continue the parent mission. Do not treat truncation as mission completion and do not invent a cache, memory system, second retrieval framework, or alternate source of truth.

## Test 60 - Finite Campaign Narration Is Nonterminal
Fixture: a 10-bug implementation campaign has enumerated candidates and at least one authorized concrete next action.
Expect: status narration cannot increment delivered count or satisfy completion; the existing finite-mission cursor exposes the next mutation/validation/repair/readback/next-candidate action.

## Test 61 - Campaign Continues After Existing PR Or Stale Head Discovery
Fixture: one candidate resolves to an existing repairable PR and another resolves to a stale head.
Expect: existing-PR discovery and stale-head detection are intermediate reads. Reuse the existing repair/refresh/currentness paths and continue the finite campaign without a user prompt; do not create a second campaign controller or state store.

## Test 64 - Refresh Handoff Persistence Is Intermediate
Fixture: a finite refresh campaign has persisted a handoff but the target PR head remains behind/diverged and no current refresh receipt proves convergence.
Expect: do not report campaign completion. Reacquire head/main/path scope, materialize/read back the existing content-bound authorization, publish the canonical refresh trigger to the linked ordinary issue, consume the receipt, and read back the PR before validation.

## Test 65 - Refresh Trigger Never Uses PR Conversation
Fixture: the refresh target PR is linked to an ordinary issue.
Expect: the existing `/agent-os refresh-pr <pr>` trigger is published only on the linked ordinary issue. Item-local failure advances independent later items; main drift reacquires unconsumed authorization evidence.

## Test 66 - Repeated Generated-Edit Syntax Defect Is Exhaustive
Fixture: a broad edit introduces the same duplicate-keyword syntax defect at two call sites; exact-head validation reports only the first location.
Expect: classify the reported site as a repeatable transformation defect, inspect the full bounded changed file set for the same pattern, repair every proven occurrence, and run the smallest available syntax/compile/structural check before publishing another head. The first compiler location is not treated as exhaustive evidence.

## Test 67 - Exhaustive Repair Does Not Bypass CKR6 Re-entry
Fixture: the repeated-edit defect requires another mutation after failed validation.
Expect: preserve the existing failed-repair CKR6 re-entry/admission boundary and exact-head validation; same-pattern inspection adds no retry authority or parser framework.
