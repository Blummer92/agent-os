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
