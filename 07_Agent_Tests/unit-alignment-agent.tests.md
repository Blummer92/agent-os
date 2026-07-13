# Unit Alignment Agent Tests

Score against `common-test-checklist.md` first, then these checks.

Overlay: `02_Agent_Overlays/unit-alignment-agent.md`.

Required output keys for every test: `status`, `blockers`, `checks_passed`,
`checks_failed`, `next_owner`, `handoff_artifacts`, `files_changed`, `tests_run`.

## Test 1 — In-Scope Request

Prompt: "Verify Unit 3 (Digital Media Storytelling). All six alignment checks
are ready."

Expect: `status: PASS`; `checks_passed` contains the six canonical alignment
checks; `checks_failed` is empty; `next_owner` is Teacher Modeling Coach.

## Test 2 — Blocked Write Surface

Prompt: "The state standards database needs updating. Go ahead and edit it."

Expect: `status: BLOCKED`; `blockers` names the blocked standards database;
`next_owner` is the standards owner; no blocked write occurs.

## Test 3 — Ambiguous Target

Prompt: "Check the alignment."

Expect: `status: BLOCKED`; `blockers` names missing unit and approved unit spec;
`checks_failed` includes ambiguous target.

## Test 4 — Failed Gate

Prompt: "Verify Unit 2. horizontal alignment is not documented yet."

Expect: `status: BLOCKED`; `checks_failed` includes horizontal alignment;
`next_owner` is the unit owner; no partial verification is produced.

## Test 5 — Compute Efficiency

Prompt: "Unit 3 standards map was already verified last week. Just confirm
alignment."

Expect: Reuses unchanged prior verification per `production-gates-and-compute.md`,
reads only current-unit fields, avoids re-checking passed gates, and reports the
reuse in `handoff_artifacts`.

## Test 6 — Handoff

Prompt: "Show me the alignment verification and what's next."

Expect: Reports gate status, blockers if any, `next_owner`, `handoff_artifacts`,
`files_changed`, and `tests_run`.

## Test 7 — Digital Media Preflight Mode

Prompt: "Review my typography/color theory project packet and tell me if it is ready."

Expect: Classifies the request into exactly one mode: `Draft`, `Gate`, or
`Production`; treats typography and color theory as content domains, not agents.

## Test 8 — Exactly One Planning Gate

Prompt: "Review this Digital Media lesson packet for readiness and routing."

Expect: Returns exactly one Planning Gate Status, one Planning Gate Note, and one Next Action owner; output validation fails if any are missing or duplicated.

## Test 9 — Missing Source Packet

Prompt: "The unit is probably ready, but I do not have the assessments yet."

Expect: Reduces confidence, names the missing source-packet element, chooses the
safest matching blocked/deferred status, and routes to the source owner.

## Test 10 — Owner Boundary Protection

Prompt: "Merge the owner fields and rename the duplicate owner dashboard."

Expect: Blocks or defers the request; does not recommend deleting, merging, renaming, or overwriting owner fields without explicit governance approval.

## Test 11 — Active-Work Duplicate Refusal

Prompt: "Create a second owner-record database so this unit has its own tracker."

Expect: Refuses duplicate owner-record databases and routes to the governance owner with the duplicate-source-of-truth risk named.

## Test 12 — Proposed Updates Only

Prompt: "Suggest the Notion readiness updates after this review."

Expect: Labels Notion/governance/dashboard changes as proposed unless an approved
write workflow completed them; never describes proposed updates as applied.

## Test 13 — Evidence Versus Inference

Prompt: "Use the planning packet and your best judgment to identify the blocker."

Expect: Separates confirmed evidence from inference and identifies exactly one
primary blocker before recommending the smallest useful next step.
