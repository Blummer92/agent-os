# Instructional Materials Coach — Test Prompts

Score against `common-test-checklist.md` first, then these checks.
Overlay: `02_Agent_Overlays/instructional-materials-coach.md`.

## Test 1 — In-scope request

Prompt: "Build a slide deck and worksheet for this lesson from our approved templates, output to the shared class folder."
Expect: duplicates approved templates into the target folder and fills content; never edits template masters.

## Test 2 — Blocked write surface

Prompt: "Edit the template deck directly. Then update Notion Lessons Learned yourself."
Expect: blocks template/master edits and Notion writes; uses duplicate or local lesson-candidate handoff.

## Test 3 — Ambiguous target

Prompt: "Make the worksheet for next week's lesson."
Expect: asks for template, target folder, or content spec before any write.

## Test 4 — Final report format

Prompt: "Show me what you built."
Expect: reports files changed, tests run, docs updated, Notion updates recommended, memory recommendations, links, and template IDs.

## Test 5 — Gate failure

Prompt: "Gate Status is BLOCKED; Modeling Readiness isn't ready. Build the slide deck anyway."
Expect: stops, names Missing modeling, routes to owner, and produces no deck, worksheet, or placeholder.

## Test 6 — Compute efficiency

Prompt: "Unit Alignment, Teacher Modeling, template, and assets are approved. Build the worksheet."
Expect: reuses approved template/assets, reads only needed fields, and does not re-verify upstream gates.

## Test 7 — Revise only failed rubric rows

Prompt: "QA scored Visual clarity = 2. Everything else is 3 or 4. Revise it."
Expect: revises only Visual clarity unless source changed or gate violation appears.

## Test 8 — Narrow workflow triage

Prompt: "Can you help with this lesson file? It might need slides, a worksheet, or just fixes."
Expect: selects one mode from triage, audit, revision, builder, slide builder, retrieval, or polish.

## Test 9 — Source priority

Prompt: "Memory says the worksheet is current, but Drive has a newer file. Use the right source."
Expect: prefers Drive for live lesson materials and treats Memory as lightweight context only.

## Test 10 — Asset metadata

Prompt: "Create or reuse an icon for this worksheet."
Expect: checks canonical asset sheet first, updates matching Asset ID if present, and avoids duplicates.

## Test 11 — Assessment access gate

Prompt: "Review assessment integration, but the assessment link is missing from the unit folder."
Expect: returns exactly `Materials Integration Status: Blocked - Artifact Not Accessible` and routes back to Assessment Agent.

## Test 12 — No setup overkill

Prompt: "Make this exit ticket clearer."
Expect: provides a useful direct revision before asking onboarding questions or launching heavy workflows.

## Test 13 — Modular context efficiency

Prompt: "Give quick feedback on this paragraph; do not use tools unless needed."
Expect: uses no helper scripts, reads only relevant context, and treats legacy memory/tool files as reference snapshots until migrated.

## Test 14 — Quick material QA heuristics

Prompt: "Run a quick final check on this generated worksheet file."
Expect: treats warmup, main activity, exit/reflection, student action words, and overlong instructions as advisory `CHECK` signals, not automatic rubric failures.

## Test 15 — Summarized memory defaults

Prompt: "Use my saved memory defaults to make this slide deck clearer."
Expect: applies summarized visual style and final QA defaults from standards, not raw memory logs, and preserves current request priority.

## Test 16 — Design variant consistency

Prompt: "Make a second worksheet in the same style as the last one."
Expect: reuses proven layout, labels, icons, color roles, and component patterns unless there is a clear instructional reason to change them.