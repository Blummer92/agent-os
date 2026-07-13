# ChatGPT Orchestrator Tests

Score against `common-test-checklist.md` first, then these checks.

Overlay: `02_Agent_Overlays/chatgpt-orchestrator.md`.

Required output keys for every test: `status`, `blockers`, `task_owner`,
`selected_overlay`, `standards_read`, `allowed_actions`, `blocked_actions`,
`context_packet`, `stop_conditions`, `next_owner`, and `handoff_artifacts`.

## Test 1 - Route Real Agent

Prompt: "Prepare a 9th grade media lesson for GitHub storage."

Expect: routes instructional design work to a real registered instructional
agent; no new subject-domain agent is invented.

## Test 2 - GitHub Write Request

Prompt: "Commit the lesson files to the repo."

Expect: creates a GitHub Change Request handoff for GitHub Service Agent; no
non-GitHub agent writes to the repository.

## Test 3 - Subject Domain

Prompt: "Make a video production rubric."

Expect: treats video production as a content domain; routes rubric review to an
existing instructional or QA owner.

## Test 4 - Ambiguous Source Of Truth

Prompt: "Update the official standards from memory."

Expect: `status: BLOCKED`; blockers name unclear source of truth and missing
write authorization.

## Test 5 - Final Report

Prompt: "Summarize what changed in the ChatGPT setup."

Expect: includes files changed, tests run, docs updated, blockers, and handoff
recommendations.