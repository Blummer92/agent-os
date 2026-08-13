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
Expect: gives speakable teacher language first, plus teacher does, students notice, and a quick check for understanding.

## Test 9 — Model sequence builder
Prompt: "Use model-sequence-builder to tighten the modeling sequence for this lesson."
Expect: returns a narrow skill focus, steps in student practice order, think-aloud moments, likely error, and student handoff.

## Test 10 — Misunderstanding response designer
Prompt: "What will students probably misunderstand here, and what should I do when they get stuck?"
Expect: separates issue, cause, visible evidence, teacher move, prevention revision, and quick check.

## Test 11 — Formal misunderstanding audit
Prompt: "Audit this lesson model for likely student misunderstandings using the misunderstanding audit template."
Expect: includes current support, gap or problem, stronger modeling move, exact teacher language, and top priorities.

## Test 12 — Workflow separation
Prompt: "Mention the Notion dashboard, but just help me improve the think-aloud."
Expect: does not enter Notion sync; uses lesson-modeling coaching only.

## Test 13 — Read-only Notion audit
Prompt: "Audit the Notion lesson page and related worksheet for modeling alignment. Do not update anything."
Expect: may gather read-only evidence and returns status fields without writing to Notion.

## Test 14 — Explicit Notion synchronization
Prompt: "Reconcile this Unit Alignment Document with the dashboard pages in Notion."
Expect: enters Notion synchronization only after target, evidence, and authorization are clear.

## Test 15 — Memory boundary
Prompt: "Remember this entire lesson transcript forever."
Expect: refuses raw transcript memory and saves only durable preferences, active status, recurring issues, or blockers when warranted.

## Test 16 — Decision Studio explanation-risk analysis
Prompt: "The teacher is deciding between a 3-column and a 5-column rubric. What will students struggle with?"
Expect: assigns Low/Medium/High explanation burden with a stated reason, flags likely student confusion, and does not select an option for the teacher.

## Test 17 — Unit 0 concise rehearsal first
Prompt: "Help me model Unit 0's file-organization routine."
Expect: gives one classroom-ready recommended rehearsal before optional audit or provenance detail; canonical modeling checks remain intact.

## Test 18 — Photography Foundations teacher language first
Prompt: "Help me model choosing a stronger camera angle for Photography Foundations."
Expect: leads with speakable teacher language and visible teacher thinking before technical modeling evidence.

## Test 19 — Known context is reused
Prompt: "Tighten the modeling for the lesson we already resolved."
Fixture: approved lesson, objective, vocabulary, assessment, and prior decision are present.
Expect: reuses the supplied approved context and does not ask the teacher to re-enter it.

## Test 20 — One genuine teacher decision
Prompt: "I can support either a live demo or a worked example, but the lesson evidence does not resolve which one I prefer."
Expect: asks one targeted material teacher choice and does not restart or expose unrelated audit fields.

## Test 21 — Controlling blocker remains blocker-first
Prompt: "Give me the rehearsal even though the required source identity is unresolved."
Expect: returns the controlling blocker first, names the exact unblock condition, and does not bypass readiness/source identity.

## Test 22 — Audit available on request
Prompt: "Show me the full modeling audit behind that rehearsal."
Expect: exposes the detailed evidence from the same modeling record without creating a second schema or restarting the workflow.

## Test 23 — Conversational refinement without restart
Prompt: "Make that rehearsal shorter and make the think-aloud more explicit."
Expect: revises the current rehearsal in place, preserves approved context, and does not rebuild the workflow from the beginning.

## Test 24 — Gradual release when useful
Prompt: "Show me how this modeling moment moves from teacher demonstration into guided and independent practice."
Expect: may use `I DO`, `WE DO`, and `YOU DO`, with teacher thinking visible; does not force all three stages when the lesson does not require them.

## Test 25 — Choice labels preserve teacher agency
Prompt: "What part of this modeling is required and what can I change?"
Expect: distinguishes `Recommended`, `Non-negotiable`, and `Flexible` guidance without changing authority, readiness, or source-of-truth rules.

## Test 26 — Do not overwhelm
Prompt: "I just need the best modeling move for tomorrow."
Expect: useful rehearsal or exact teacher language appears before schemas, audit fields, extracts, provenance, or verification detail unless a controlling blocker requires blocker-first output.
