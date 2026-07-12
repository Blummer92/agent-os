# Unit Alignment Agent Tests

Score against `common-test-checklist.md` first, then these checks.

Overlay: `02_Agent_Overlays/unit-alignment-agent.md`.

Required output keys for every test:
`status`, `blockers`, `checks_passed`, `checks_failed`, `next_owner`,
`handoff_artifacts`, `files_changed`, `tests_run`.

## Test 1 — In-Scope Request

Prompt: "Verify Unit 3 (Digital Media Storytelling). standards, learning
objectives, assessments, instructional strategies, horizontal alignment, and
vertical alignment are ready."

Expect: `status: PASS`; `checks_passed` contains all six alignment checks;
`checks_failed` is empty; `next_owner` is Teacher Modeling Coach.

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

## Test 5 — Compute Efficiency (Agent Compute Profile)

Prompt: "Unit 3 standards map was already verified last week. Just confirm alignment."

Expect: Per the Unit Alignment Agent Compute Profile in
`production-gates-and-compute.md`: reuses the existing standards map instead
of regenerating it, reads only current-unit fields (not full unit history),
does not re-check the already-passed six-check/12-question result, and
reports those choices in `handoff_artifacts`.

## Test 6 — QA Handoff

Prompt: "Show me the alignment verification and what's next."

Expect: Reports six-check status, blockers if any, `next_owner`,
`handoff_artifacts`, `files_changed`, and `tests_run`.