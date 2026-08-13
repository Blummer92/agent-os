# Teacher Modeling Coach Tests — Details (Tests 17-26)

Detail file for `07_Agent_Tests/teacher-modeling-coach.tests.md`, split out to
keep that index under the 100-line Markdown limit. Score against
`common-test-checklist.md` first, then the checks below.
Overlay: `02_Agent_Overlays/teacher-modeling-coach.md`.

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
Expect: requires `I DO`, `WE DO`, and `YOU DO` for this explicitly three-stage request, with teacher thinking visible in the demonstration.
Companion prompt: "Give me a brief teacher demonstration for a modeling moment that does not need guided practice."
Companion expect: does not force `WE DO` or all three gradual-release stages when the lesson does not require them.

## Test 25 — Choice labels preserve teacher agency
Prompt: "What part of this modeling is required and what can I change?"
Expect: distinguishes `Recommended`, `Non-negotiable`, and `Flexible` guidance without changing authority, readiness, or source-of-truth rules.

## Test 26 — Do not overwhelm
Prompt: "I just need the best modeling move for tomorrow."
Expect: useful rehearsal or exact teacher language appears before schemas, audit fields, extracts, provenance, or verification detail unless a controlling blocker requires blocker-first output.
