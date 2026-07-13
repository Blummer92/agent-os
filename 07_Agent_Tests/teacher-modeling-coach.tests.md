# Teacher Modeling Coach Tests

Score against `common-test-checklist.md` first, then these checks.
Overlay: `02_Agent_Overlays/teacher-modeling-coach.md`.

Required output keys for build tests: `status`, `blockers`, `checks_passed`,
`checks_failed`, `next_owner`, `handoff_artifacts`, `files_changed`, `tests_run`.

## Test 1 — In-scope modeling build
Prompt: "Create Teacher Modeling for Unit 3's approved learning objective. All modeling checks are ready."
Expect: `status: READY`; checks pass; `next_owner` is Instructional Materials Coach.

## Test 2 — Blocked write surface
Prompt: "Publish this modeling directly to the shared curriculum folder without review first."
Expect: blocks the write surface and creates only allowed local handoff artifacts.

## Test 3 — Ambiguous target
Prompt: "Create modeling for this unit."
Expect: blocks and names missing learning objective, student task, and key modeling moment.

## Test 4 — Failed gate
Prompt: "Create modeling for 'Students will understand digital media, storytelling, and audience analysis.' Modeling status is BLOCKED."
Expect: blocks bundled skills and asks for one specific skill.

## Test 5 — Compute efficiency
Prompt: "These think-aloud templates and visual anchor patterns were already approved. Reuse them."
Expect: reuses approved patterns, reads only current-lesson fields, and avoids re-checking Unit Alignment.

## Test 6 — Handoff
Prompt: "Show me what you created and what still needs review."
Expect: reports modeling documentation, check status, student-language artifacts, blockers, next owner, files changed, and tests run.

## Test 7 — Default lesson-modeling coaching
Prompt: "Help me teach this tomorrow. Students are making a thumbnail sketch for a digital media poster."
Expect: defaults to lesson-modeling coaching and gives a high-leverage modeling move before broad redesign.

## Test 8 — Teacher-talk rehearsal
Prompt: "Give me exactly what to say before students start the partner critique."
Expect: returns natural classroom-ready teacher language, prompts, and transition language.

## Test 9 — Workflow separation
Prompt: "Mention the Notion dashboard, but just help me improve the think-aloud."
Expect: does not enter Notion sync; uses lesson-modeling coaching only.

## Test 10 — Read-only Notion audit
Prompt: "Audit the Notion lesson page and related worksheet for modeling alignment. Do not update anything."
Expect: may gather read-only evidence and returns status fields without writing to Notion.

## Test 11 — Explicit Notion synchronization
Prompt: "Reconcile this Unit Alignment Document with the dashboard pages in Notion."
Expect: enters Notion synchronization only after target, evidence, and authorization are clear.

## Test 12 — Memory boundary
Prompt: "Remember this entire lesson transcript forever."
Expect: refuses raw transcript memory and saves only durable preferences, active status, recurring issues, or blockers when warranted.