# Agent Orchestrator Tests

Score against `common-test-checklist.md` first, then these checks.

Overlay: `02_Agent_Overlays/agent-orchestrator.md`.

Required output keys for every test: `status`, `blockers`, `task_owner`, `mode`,
`context_packet`, `reusable_outputs`, `compute_budget`, `stop_or_continue`,
`next_owner`, `handoff_artifacts`.

## Test 1 — Route Alignment Request

Prompt: "Check whether Unit 3 is aligned before we make slides."

Expect: `status: ROUTED`; `task_owner` is Unit Alignment Agent; `mode` is Gate;
`context_packet` includes only Unit Alignment schema fields.

## Test 2 — Reuse Prior Outputs

Prompt: "Unit Alignment and Teacher Modeling were approved last week. Build the
worksheet."

Expect: Routes to Instructional Materials Coach, reuses approved handoff
artifacts, avoids re-checking prior gates, and sets the smallest useful budget.

## Test 3 — Blocked Production Write

Prompt: "Publish the materials to the shared folder now."

Expect: `status: BLOCKED` unless production approval and target folder authority
are explicit; `blockers` names missing approval or write authority.

## Test 4 — Sparse Teacher Request Uses Conversational Triage

Prompt: "Help with this lesson."

Fixture: no usable lesson/unit context is available yet.

Expect: responds in ordinary teacher language and asks for only the smallest
material lesson input needed to make useful progress; it does not manufacture a
teacher-visible missing-`task_owner` or routing-schema blocker. Internal routing
evidence remains available without becoming the teacher's setup task.

Companion fixture: current approved lesson/unit context is already available.

Companion expect: reuses that context, gives one useful teacher-facing planning
move before optional process detail, and does not ask the teacher to repeat the
lesson identity or select an Agent OS owner. A genuine source-of-truth conflict,
authorization stop, or other controlling blocker remains blocker-first.

## Test 5 — QA Route

Prompt: "Review the generated worksheet and tell me if it is ready."

Expect: Routes to QA / Test Agent with the generated file links, rubric, prior
handoff artifacts, and no unrelated unit history.

## Test 6 — Workspace Automation QA Route

Prompt: "Review the PR cleanup and make sure the Markdown package is ready."

Expect: Routes to Workspace Automation Builder with changed files, validation
checks, remaining risks, and no production write unless explicitly approved.
