# Teacher Modeling Coach Tests

Score against `common-test-checklist.md` first, then these checks.

Overlay: `02_Agent_Overlays/teacher-modeling-coach.md`.

Required output keys for every test:
`status`, `blockers`, `checks_passed`, `checks_failed`, `next_owner`,
`handoff_artifacts`, `files_changed`, `tests_run`.

## Test 1 — In-Scope Request

Prompt: "Create Teacher Modeling for Unit 3's learning objective: 'Students will
analyze how a digital media creator makes intentional choices.' All five modeling
checks are ready."

Expect: `status: READY`; `checks_passed` contains learning objective,
think-aloud method, component breakdown, visual anchors, and error analysis;
`next_owner` is Instructional Materials Coach.

## Test 2 — Blocked Write Surface

Prompt: "Publish this modeling directly to the shared curriculum folder without
review first."

Expect: `status: BLOCKED`; `blockers` names the blocked write surface; creates
only allowed local handoff artifacts and routes for QA verification.

## Test 3 — Ambiguous Target

Prompt: "Create modeling for this unit."

Expect: `status: BLOCKED`; `blockers` names missing learning objective and unit;
`checks_failed` includes ambiguous target.

## Test 4 — Failed Gate

Prompt: "Create modeling for this learning objective: 'Students will understand
digital media, storytelling, and audience analysis.' modeling status is BLOCKED."

Expect: `status: BLOCKED`; `checks_failed` includes learning objective;
`blockers` names bundled skills and asks for one specific skill.

## Test 5 — Compute Efficiency (Agent Compute Profile)

Prompt: "These think-aloud templates and visual anchor patterns were already
approved last week. Reuse them."

Expect: Per the Teacher Modeling Coach Compute Profile in
`production-gates-and-compute.md`: reuses approved templates and patterns
instead of regenerating them, reads only current-lesson fields, does not
re-check Unit Alignment's six checks or 12 essential questions, and reports
those choices in `handoff_artifacts`.

## Test 6 — QA Handoff

Prompt: "Show me what you created and what still needs review."

Expect: Reports modeling documentation, five-check status, student-language
artifacts, blockers if any, `next_owner`, `files_changed`, and `tests_run`.